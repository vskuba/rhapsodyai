"""
Запись результатов конвейера в БД: состояния задачи и подзадач, история попыток.

Чтение и захват работы — в `task_claim.py`; здесь только фиксация того,
что уже произошло.

Подзадача конвейера — это обычная строка `project_task` с `parent_id` родителя.
Отдельной таблицы у конвейера нет, поэтому «состояние подзадачи» — тот же
`pipeline_state`, а «попытки» — `pipeline_attempt_count`. Ветку задаёт `parent_id`:
у родителя состояния планирования, у ребёнка — круг Developer → QA.
"""
import json
import time

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_CONTEXT,
    TASK_METADATA_KEY_SPLIT_MORE,
    TASK_METADATA_KEY_DEV,
    TASK_METADATA_KEY_TEST,
    task_metadata_stop_sql,
)
from src.project.task.task_plan import (
    task_plan_goals_normalize,
    task_plan_serialize,
)
from src.project.task.task_report import task_report_write


def task_state_kanban_sql(pipeline_state: str | None) -> tuple[str, list]:
    """
    Кусок `SET` для человеческого статуса под новое состояние конвейера.

    Оси остаются двумя независимыми колонками — `status` человек правит руками, и отбор
    задач в конвейер его по-прежнему не смотрит, — но врать друг другу они не должны:
    задача, которую менеджер уже взял в планирование, не может висеть «Ожидает».

    Возвращает ('', []) для состояний вне таблицы: тогда `status` не трогаем вовсе.

    `cancelled` не перезаписываем. Это единственный статус, которым человек говорит «не
    делать»; молча вернуть отменённую задачу в работу хуже, чем разойтись с осью конвейера.

    По той же причине не трогаем статус остановленной строки (снятый флажок
    «в разработку», `task_stop`): прогон, которому её остановили на ходу, доигрывает
    свой конец в воркере и пишет результат уже после стопа — без этой оговорки он
    вернул бы задаче «В очереди» поверх «Ожидает», и человек увидел бы, что флажок
    не сработал.
    """
    kanban = task_state_kanban_status(pipeline_state)
    if not kanban:
        return '', []
    return f"status = IF(status = 'cancelled' OR {task_metadata_stop_sql()}, status, %s)", [kanban]


def task_state_kanban_status(pipeline_state: str | None) -> str:
    """Человеческий статус под состояние конвейера; '' — соответствия нет.

    Нужен отдельно от `task_state_kanban_sql`: подзадачи создаются INSERT-ом, а там
    `SET`-фрагмент не к чему приложить — нужно само значение колонки.
    """
    return _TASK_STATE_KANBAN.get(pipeline_state or '', '')


async def task_state_task_get(task_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()
    return dict(row) if row else {}


async def task_state_subtask_get(subtask_id: int) -> dict:
    """
    Перечитать подзадачу по id.

    Нужна воркеру: тик захватил строку и положил в очередь только её id, а к моменту
    выполнения состояние могло измениться. Пустой dict — строки больше нет.

    `parent_id IS NOT NULL` — страховка от чужого id: работа Developer/QA идёт только
    по детям, и корневая задача сюда попасть не должна ни при какой гонке.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM project_task WHERE id = %s AND parent_id IS NOT NULL", (subtask_id,))
        row = await db.fetchone()
    return dict(row) if row else {}


async def task_state_plan_save(task_id: int, plan_json: str, goals_json: str | None = None) -> None:
    """
    planning | reviewing -> plan_approval. Подзадачи не создаём: сначала утверждение
    человеком.

    `reviewing` — пересмотр плана по кнопке «Обновить план»; на выходе у него ровно то же
    самое, что у первого планирования, поэтому и запись одна. Без него в условии
    результат пересмотра молча не сохранялся бы.

    Цели, наоборот, пишем тем же UPDATE — это чек-лист, а не работа для агентов,
    и утверждать его отдельно нечего. Одним запросом, чтобы не осталось задачи с
    планом, но без целей, если второй запрос не дойдёт.
    """
    kanban_sql, kanban_params = task_state_kanban_sql('plan_approval')
    sets   = ["pipeline_state = 'plan_approval'", kanban_sql, "pipeline_plan = %s", "pipeline_error = ''",
              "pipeline_locked_at = NULL", "pipeline_locked_by = ''"]
    params: list = kanban_params + [plan_json]
    if goals_json is not None:
        sets.append("goals = %s")
        params.append(goals_json)
    params.append(task_id)

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET {', '.join(s for s in sets if s)} "
            "WHERE id = %s AND pipeline_state IN ('planning', 'reviewing')",
            params,
        )
        await db.connection.commit()


async def task_state_type_to_plan(task_id: int) -> bool:
    """
    Задача взята в планирование: тип -> `plan`.

    Тип задачи здесь — отметка текущей фазы, а не природы работы: план утверждают —
    тип уходит в `dev` (`task_state_type_to_dev`), работа доходит до проверки — в
    `test` (`task_state_dev_to_testing`). Одного звена в этой цепочке не хватало —
    входа: заведённая человеком задача типа `dev` уезжала планироваться, оставаясь
    `dev`. А по типу выбирается роль-планировщик (`task_role_by_type`), и план такой
    задачи писала карточка разработчика вместо менеджера.

    Подзадачи переводим наравне с корневыми. Планирование берёт не только их:
    подзадача уходит туда двумя дорогами — помеченная менеджером «дробить дальше»
    (`_subtask_state`) и возвращённая из тупика (`task_goal_replan`). Рождается она
    всегда типом `dev` (`task_state_subtasks_create`), и без перевода её план писала
    бы карточка разработчика — ровно та подмена роли, от которой уводит эта функция.
    Поймано живьём на #1628: «Задача взята в планирование (Разработчик)».

    Раньше подзадачи здесь исключались из опасения, что тип `plan` останется на них
    навсегда. Опасение снято с двух сторон: обратный перевод (`task_state_type_to_dev`)
    теперь тоже берёт подзадачи, а работу они получают не по типу вовсе —
    `task_claim_subtask_developable` и `task_claim_subtask_testable` отбирают по
    состоянию и проекту. То есть даже застрявший тип не остановил бы конвейер, он
    показал бы строку не на той вкладке.

    `bug` не трогаем: багфиксер плана не пишет вовсе (`TASK_ROLE_PLANNERS`), и перевод
    увёл бы баг с его собственного пути. Сюда он попасть и не может — отбор
    планирования отсеивает багфиксера раньше, — но функция публичная, и полагаться на
    осторожность будущего вызывающего не за чем.

    `COALESCE` на типе — ради задач без типа вообще: `NULL NOT IN (...)` дало бы NULL,
    и строка не обновилась бы, хотя ей-то тип как раз и нужен.

    Returns:
        True — тип сменён. False — задача уже `plan`, это баг или строки типа `plan`
        в установке нет; это норма, а не ошибка.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            "   SET task_type_id = (SELECT id FROM project_task_type WHERE name = 'plan') "
            " WHERE id = %s "
            "   AND COALESCE(task_type_id, 0) NOT IN "
            "       (SELECT id FROM project_task_type WHERE name IN ('plan', 'bug')) "
            "   AND EXISTS (SELECT 1 FROM project_task_type WHERE name = 'plan')",
            (task_id,),
        )
        moved = db.rowcount > 0
        await db.connection.commit()

    if moved:
        logger_info(f'[task] task#{task_id} взята в планирование: тип -> plan')
    return moved


async def task_state_plan_to_development(task_id: int) -> bool:
    """
    Задача планирования с пометкой «в разработку»: тип -> `dev`, состояние -> `approved`.

    Пометку (`metadata.to_development`) человек ставит флажком заранее, ещё до того, как
    менеджер напишет план: этим он говорит, что решение «делаем» принято. Ждать после
    этого второго нажатия «Утвердить» не за чем — план готов, и задача сама переходит из
    планирования в разработку и встаёт в `approved`, откуда её подберёт разбор плана на
    подзадачи.

    Тип ищем по имени: id типов зависят от установки. Меняем только `plan` — у задач
    других типов вкладка «Планирование» флажка не рисует, и попасть сюда они могут
    только пометкой, оставшейся от прежнего типа.

    Пометку снимаем тем же запросом, она одноразовая. Флажок есть только на вкладке
    «Планирование», а задача с этого шага уходит на «Разработку», и снять его человек
    больше не смог бы: невидимая пометка молча утверждала бы и все следующие планы,
    если задачу вернуть в планирование.

    Returns:
        True — задача переведена. False — пометки не было, тип другой или состояние
        успел изменить кто-то ещё; это норма, а не ошибка.
    """
    kanban_sql, kanban_params = task_state_kanban_sql('approved')
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            "   SET task_type_id = (SELECT id FROM project_task_type WHERE name = 'dev'), "
            f"       pipeline_state = 'approved', {kanban_sql + ', ' if kanban_sql else ''}"
            f"       metadata = JSON_REMOVE(metadata, '$.{TASK_METADATA_KEY_DEV}') "
            " WHERE id = %s AND pipeline_state = 'plan_approval' "
            "   AND task_type_id = (SELECT id FROM project_task_type WHERE name = 'plan') "
            f"   AND JSON_EXTRACT(metadata, '$.{TASK_METADATA_KEY_DEV}') = TRUE",
            kanban_params + [task_id],
        )
        moved = db.rowcount > 0
        await db.connection.commit()

    if moved:
        logger_info(f'[task] task#{task_id} по пометке «в разработку»: тип -> dev, состояние -> approved')
    return moved


async def task_state_type_to_dev(task_id: int) -> bool:
    """
    План утверждён кнопкой «Утвердить»: тип -> `dev`. Состояние меняет сам эндпоинт.

    Тот же переезд с вкладки «Планирование» на «Разработку», что делает пометка
    «в разработку», только по нажатию человека. Без него задача, утверждённая руками,
    оставалась бы типом `plan` навсегда: тип меняли только два места, и оба —
    по пометкам. Задача при этом уходила разрабатываться и проверяться, но висела на
    вкладке «Планирование», а флажок «в тестирование» рисуется на «Разработке» — и
    поставить его человеку было негде.

    Состояние здесь не трогаем намеренно: его переводит `_pipeline_state_set` со
    сверкой `plan_approval`, и второй писатель состояния в том же нажатии разошёлся бы
    с его проверкой гонки. Зовут отсюда только после удавшегося перехода.

    Наличие типа `dev` проверяем отдельно: без строки типа подзапрос дал бы NULL и
    задача пропала бы со всех вкладок.

    Подзадачи переводим наравне с корневыми — иначе разложенная подзадача осталась бы
    типом `plan` и висела на вкладке «Планирование», хотя её дети уже пишут код.
    Парность обязательна: вход в планирование (`task_state_type_to_plan`) подзадачи
    берёт, и односторонний перевод оставлял бы их с типом фазы, которая закончилась.

    Returns:
        True — тип сменён. False — задача уже не `plan` (утвердили дважды, тип сменила
        пометка); это норма, а не ошибка.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            "   SET task_type_id = (SELECT id FROM project_task_type WHERE name = 'dev') "
            " WHERE id = %s "
            "   AND task_type_id = (SELECT id FROM project_task_type WHERE name = 'plan') "
            "   AND EXISTS (SELECT 1 FROM project_task_type WHERE name = 'dev')",
            (task_id,),
        )
        moved = db.rowcount > 0
        await db.connection.commit()

    if moved:
        logger_info(f'[task] task#{task_id} план утверждён человеком: тип -> dev')
    return moved


async def task_state_dev_to_testing(task_id: int) -> bool:
    """
    Задача разработки, дошедшая до проверки: тип -> `test`, состояние -> `testing`.

    Зеркало `task_state_plan_to_development` на следующей развилке конвейера. Там человек
    заранее говорит «план утверждать не надо», здесь — «готовую работу на проверку
    отдавать не спрашивая»; разница только в умолчании: пометка `metadata.to_testing`
    считается стоящей, пока её явно не сняли (`<> FALSE`, а не `= TRUE`).

    «Дошла до проверки» — это состояние, которое страница задач и так показывает у
    родителя чипсом: самая отстающая подзадача из плана в `qa_pending` или `testing`.
    То есть по всем веткам плана разработчик своё закончил и ни одна не осталась в
    работе, на повторе или в сбое. Смотрим детей, а не саму задачу: очередь к QA и сама
    проверка — состояния детской ветки, родителю их не выставляет никто, у него всё это
    время `processing`.

    Подзапрос обёрнут в производную таблицу — MySQL 1093 запрещает читать в UPDATE ту же
    таблицу, которую пишет. Наличие типа `test` проверяем отдельно: без строки типа
    подзапрос дал бы NULL и задача пропала бы со всех вкладок.

    Состояние `testing` — рабочее (`active`): круг QA по подзадачам продолжается, просто
    идёт он уже под вкладкой «Тестирование». Закрывает такую задачу та же финализация,
    что и `processing`, — когда все дети станут терминальными.

    Returns:
        True — задача переведена. False — пометка снята, тип другой, дети ещё не готовы
        или состояние успел изменить кто-то ещё; это норма, а не ошибка.
    """
    kanban_sql, kanban_params = task_state_kanban_sql('testing')
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            "   SET task_type_id = (SELECT id FROM project_task_type WHERE name = 'test'), "
            f"       pipeline_state = 'testing'{', ' + kanban_sql if kanban_sql else ''} "
            " WHERE id = %s AND parent_id IS NULL AND pipeline_state = 'processing' "
            "   AND task_type_id = (SELECT id FROM project_task_type WHERE name = 'dev') "
            "   AND EXISTS (SELECT 1 FROM project_task_type WHERE name = 'test') "
            f"   AND (JSON_EXTRACT(metadata, '$.{TASK_METADATA_KEY_TEST}') IS NULL "
            f"        OR JSON_EXTRACT(metadata, '$.{TASK_METADATA_KEY_TEST}') <> FALSE) "
            f"   AND id IN {_KIDS_AWAITING_QA_SQL}",
            kanban_params + [task_id],
        )
        moved = db.rowcount > 0
        await db.connection.commit()

    if moved:
        logger_info(f'[task] task#{task_id} по пометке «в тестирование»: тип -> test, состояние -> testing')
    return moved


async def task_state_subtasks_create(task_id: int, subtasks: list) -> int:
    """
    Материализовать утверждённый план и снять блокировку с задачи.

    Подзадача — строка того же дерева: `project_id` и вкладку берём у родителя одним
    `INSERT ... SELECT`, чтобы ребёнок не оказался в другом проекте, если родителя
    переносят параллельно. Тип фиксируем `dev`: круг по подзадаче всегда
    Developer → QA, каким бы ни был тип родителя.

    `pipeline_from_plan = 1` — метка происхождения. По ней сброс и пересмотр плана
    находят свои строки и не сносят подзадачи, которые человек завёл руками.

    План и цели у подзадачи свои (`item['plan']`, `item['goals']`), а не унаследованные
    от родителя: подзадач бывает несколько, и общий план родителя, показанный в каждой,
    не отвечает на вопрос «что делать именно здесь». В `pipeline_plan` ребёнка кладём
    тот же JSON, что и у родителя, но с пустым списком подзадач — детей у ребёнка нет,
    зато форма колонки одна на всё дерево, и `task_plan_parse` читает её везде одинаково.
    """
    # Канбан-статус считаем на каждую подзадачу: крупная уходит в `new`
    # (человеку — «Ожидает»), обычная в `planned` («В очереди»). Одно значение на
    # всех показало бы крупную стоящей в очереди к разработчику, хотя её ждёт
    # менеджер.
    async with mysql_get_db_async() as db:
        for position, item in enumerate(subtasks):
            goals = task_plan_goals_normalize(item.get('goals'))
            plan_text = str(item.get('plan') or '')
            # Пустой план подзадачи оставляем пустой строкой, а не JSON-пустышкой:
            # так поле в форме выглядит незаполненным, а не «планом ни о чём».
            plan_json = task_plan_serialize(plan_text, [], goals) if plan_text or goals else ''
            # Пометка приёмки едет из плана менеджера в мешок подзадачи: по ней
            # отбор не берёт её в работу, пока соседи не закрыты
            # (`task_metadata_final_wait_sql`). У обычной подзадачи мешок пуст —
            # ключа нет вовсе, а не `false`: так же, как у флажков фаз.
            metadata = _subtask_metadata(item)
            await db.execute(
                "INSERT INTO project_task "
                "       (project_id, parent_id, title, description, goals, pipeline_plan, "
                "        position, status, task_type_id, pipeline_state, pipeline_from_plan, "
                "        metadata) "
                "SELECT t.project_id, t.id, %s, %s, %s, %s, %s, %s, "
                "       (SELECT id FROM project_task_type WHERE name = 'dev'), %s, 1, %s "
                "  FROM project_task t WHERE t.id = %s",
                (str(item.get('title') or ''), str(item.get('description') or ''),
                 json.dumps(goals, ensure_ascii=False) if goals else '',
                 plan_json, position, task_state_kanban_status(_subtask_state(item)),
                 _subtask_state(item), metadata, task_id),
            )
        await db.execute(
            "UPDATE project_task SET pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            (task_id,),
        )
        await db.connection.commit()
    return len(subtasks)


async def task_state_task_fail(task_id: int, error: str) -> None:
    kanban_sql, kanban_params = task_state_kanban_sql('failed')
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = 'failed', {kanban_sql}, pipeline_error = %s, "
            "pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            kanban_params + [error, task_id],
        )
        await db.connection.commit()
    # Отчёт пишем здесь, а не у каждого вызывающего: в `failed` задача попадает из
    # четырёх мест, и человеку в любом из них нужна одна и та же причина.
    await task_report_write(task_id, f'Сбой конвейера: {error}', ok=False)
    logger_info(f'[task] task#{task_id} -> failed: {error}')


async def task_state_task_done(task_id: int, report: str) -> None:
    """
    Закрыть корневую задачу как выполненную: `pipeline_state = done`, `status = done`.

    Отдельно от `task_state_task_finalize()`: та закрывает задачу по терминальности её
    подзадач, а у бага подзадач нет вовсе — финализация его просто не увидит.

    Обе оси ставим разом, потому что решение об этом принял агент: у бага нет ни
    утверждения плана человеком, ни приёмки QA, и «конвейер закончил, а человек ещё
    нет» здесь означало бы просто забытую строку.

    Блокировку снимаем той же правкой, а `pipeline_error` чистим: у бага, дошедшего до
    `done` со второго захода, там осталась бы причина прошлого срыва.

    `task_state_kanban_sql` не даёт перебить статус отменённой и остановленной строки —
    прогон, доигрывающий свой конец в воркере, не воскресит их своим `done`.
    """
    kanban_sql, kanban_params = task_state_kanban_sql('done')
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = 'done', {kanban_sql}, pipeline_error = '', "
            "pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            kanban_params + [task_id],
        )
        await db.connection.commit()

    await task_report_write(task_id, report)
    logger_info(f'[task] task#{task_id} -> done')


async def task_state_goals_inherit(task_id: int) -> int:
    """
    Перенести на задачу отметки её же целей, закрытых в подзадачах.
    Returns: сколько целей отмечено этим вызовом.

    Галочку ставит только QA и только по отдельному ответу про эту цель
    (`src/tool/project/task_goal.py`), поэтому у родителя своих отметок не
    появляется: проверяют подзадачи. Но цели плана менеджер раздаёт детям теми же
    словами, что и родителю, — совпадение формулировок и есть тот самый
    подтверждённый ответ QA, только записанный строкой ниже.

    Что не совпало — остаётся незакрытым. Готовая задача с пустым чекбоксом
    честнее, чем галочка без проверки: именно она в прошлый раз выдала за
    проверенное то, чего никто не открывал.
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT goals FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()
        goals = task_plan_goals_normalize((row or {}).get('goals'))
        if not goals or all(g['done'] for g in goals):
            return 0

        await db.execute("SELECT goals FROM project_task WHERE parent_id = %s", (task_id,))
        children = await db.fetchall()
        closed = set()
        for child in children or []:
            closed |= {g['text'].lower() for g in task_plan_goals_normalize(child.get('goals')) if g['done']}

        count = 0
        for goal in goals:
            if goal['done'] or goal['text'].lower() not in closed:
                continue
            goal['done'] = True
            count += 1
        if not count:
            return 0

        await db.execute("UPDATE project_task SET goals = %s WHERE id = %s",
                         (json.dumps(goals, ensure_ascii=False), task_id))
        await db.connection.commit()

    logger_info(f'[task] task#{task_id}: цели отмечены по проверкам подзадач ({count} из {len(goals)})')
    return count


async def task_state_task_requeue(task_id: int, state: str, error: str) -> None:
    """
    Вернуть задачу в состояние, из которого её снова подберёт тик, и снять блокировку.

    Нужна для повтора сорвавшегося прогона (`task_retry`): менеджер не ответил, но
    работы он и не сделал — хоронить задачу в `failed` не за что, её надо просто
    отдать следующему тику. Состояние выбирает вызывающий, и оно то же, что у возврата
    брошенной блокировки (`task_claim.TASK_CLAIM_STATE_RECLAIM`): планирование -> `new`,
    пересмотр -> `reviewing`.

    Причину кладём в `pipeline_error`: состояние снова рабочее, и без неё на странице
    задач не осталось бы следа, почему задача пошла по второму кругу.
    """
    kanban_sql, kanban_params = task_state_kanban_sql(state)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, {kanban_sql}, pipeline_error = %s, "
            "pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            [state] + kanban_params + [error, task_id],
        )
        await db.connection.commit()
    logger_info(f'[task] task#{task_id} -> {state} (повтор после срыва): {error}')


async def task_state_task_finalize() -> tuple[int, str] | None:
    """
    processing | testing -> done | failed, когда все подзадачи терминальны.
    Returns: (task_id, final_state) либо None, если финализировать нечего.

    Считаем только детей из плана (`pipeline_from_plan`): дерево общее, и под задачей
    могут висеть подзадачи, заведённые человеком руками, — они живут своей жизнью, и
    ждать их конвейеру нечего. Всё, что разложено из плана, финализацию задерживает,
    даже если состояние из родительской ветки: ждать лишнее безопаснее, чем закрыть
    задачу раньше времени.

    `testing` закрываем наравне с `processing`: пометка «в тестирование» переводит
    задачу туда, когда разработка кончилась, но круг QA по подзадачам продолжается —
    это то же выполнение под другой вкладкой, и закрывать его больше некому.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT t.id, t.pipeline_state, "
            "       SUM(c.pipeline_state NOT IN ('done','no_code_for_testing','blocked','failed')) AS pending_cnt, "
            "       SUM(c.pipeline_state IN ('blocked','failed')) AS blocked_cnt "
            "  FROM project_task t "
            "  JOIN project_task c ON c.parent_id = t.id AND c.pipeline_from_plan = 1 "
            " WHERE t.pipeline_state IN ('processing', 'testing') "
            " GROUP BY t.id HAVING pending_cnt = 0 LIMIT 1"
        )
        row = await db.fetchone()
        if not row:
            return None

        final = 'failed' if int(row['blocked_cnt'] or 0) else 'done'
        kanban_sql, kanban_params = task_state_kanban_sql(final)
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, {kanban_sql} "
            " WHERE id = %s AND pipeline_state = %s",
            [final] + kanban_params + [row['id'], row['pipeline_state']],
        )
        claimed = db.rowcount
        await db.connection.commit()

    if not claimed:
        return None
    logger_info(f'[task] task#{row["id"]} -> {final}')
    return int(row['id']), final


async def task_state_task_revive() -> tuple[int, str] | None:
    """
    failed -> processing | testing | done, когда среди подзадач не осталось упавших.
    Returns: (task_id, new_state) либо None, если возвращать нечего.

    Зачем. Финализация закрывает задачу по **мгновенному** состоянию детей: хватает
    одного ребёнка в `blocked`/`failed`, чтобы вся задача стала `failed`. Но ребёнок
    из этих состояний возвращается — его перезапускает человек, оживляет ответ на
    вопрос, забирает следующий круг. Родитель при этом оставался закрытым навсегда:
    финализация ищет только `processing`/`testing` и мимо `failed` уже не проходит.

    Поймано живьём на #1027: восемь подзадач из девяти готовы, девятая на минуту
    упала, задачу закрыли как провалившуюся — а через четверть часа подзадача
    отчиталась `ok` и продолжила работу под «заблокированной» задачей.

    Куда возвращаем. Дети ещё работают — в рабочее состояние; все закрылись, пока
    родитель лежал, — сразу в `done`, иначе задача осталась бы `failed` при всех
    готовых детях, и закрыть её было бы уже некому.

    Рабочее состояние берём **из типа задачи**, а не угадываем: на вкладку
    «Тестирование» задачу переводит `task_state_task_testing` вместе со сменой
    `task_type_id`, и вернуть `processing` строке с типом `test` значило бы
    рассогласовать состояние с вкладкой, на которой она видна.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT t.id, "
            "       (t.task_type_id = (SELECT id FROM project_task_type WHERE name = 'test')) AS is_test, "
            "       SUM(c.pipeline_state NOT IN ('done','no_code_for_testing','blocked','failed')) AS pending_cnt, "
            "       SUM(c.pipeline_state IN ('blocked','failed')) AS blocked_cnt "
            "  FROM project_task t "
            "  JOIN project_task c ON c.parent_id = t.id AND c.pipeline_from_plan = 1 "
            " WHERE t.pipeline_state = 'failed' "
            " GROUP BY t.id HAVING blocked_cnt = 0 LIMIT 1"
        )
        row = await db.fetchone()
        if not row:
            return None

        if int(row['pending_cnt'] or 0):
            state = 'testing' if int(row['is_test'] or 0) else 'processing'
        else:
            state = 'done'

        kanban_sql, kanban_params = task_state_kanban_sql(state)
        # `pipeline_state = 'failed'` в условии — та же защита от гонки, что и у
        # финализации: пока мы считали, строку мог тронуть человек кнопкой.
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, {kanban_sql}, pipeline_error = '' "
            " WHERE id = %s AND pipeline_state = 'failed'",
            [state] + kanban_params + [row['id']],
        )
        claimed = db.rowcount
        await db.connection.commit()

    if not claimed:
        return None
    logger_info(f'[task] task#{row["id"]} failed -> {state} (упавших подзадач не осталось)')
    return int(row['id']), state


async def task_state_subtask_set(subtask_id: int, state: str, last_error: str | None = None,
                                 attempt_count: int | None = None,
                                 unless_done: bool = False) -> None:
    """
    Новое состояние подзадачи со снятием блокировки.

    `parent_id IS NOT NULL` в условии — та же страховка, что и в `task_state_subtask_get`:
    детские состояния родителю выставлять нельзя, иначе ветки конвейера перепутаются.

    `unless_done` — не трогать закрытую подзадачу. Ставят его те, кто пишет
    **итог круга**: круг мог отвалиться по таймауту и вернуться с ответом, когда
    строку уже закрыли другим путём. Поймано живьём: #1028 закрылась пропуском по
    целям, а через десять минут вернулся оборванный круг QA и увёл её в
    `failed_qa` — воскресив работу, которой не было.

    Человеческие переходы флаг не ставят: «Перезапустить» и ответ на вопрос
    возвращают в работу осознанно, и запрещать это было бы враньём про то, кто
    здесь решает.
    """
    kanban_sql, kanban_params = task_state_kanban_sql(state)
    sets = ["pipeline_state = %s", kanban_sql, "pipeline_locked_at = NULL", "pipeline_locked_by = ''"]
    params: list = [state] + kanban_params
    if last_error is not None:
        sets.append("pipeline_error = %s")
        params.append(last_error)
    if attempt_count is not None:
        sets.append("pipeline_attempt_count = %s")
        params.append(attempt_count)
    params.append(subtask_id)

    # Терминальных состояний два, и оба защищаем: круг, оборвавшийся по таймауту,
    # возвращается с ответом уже после того, как строку закрыли, — и без этого
    # воскресил бы работу, которой не было.
    guard = (" AND pipeline_state NOT IN ('done','no_code_for_testing')"
             if unless_done else '')
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET {', '.join(s for s in sets if s)} "
            f"WHERE id = %s AND parent_id IS NOT NULL{guard}",
            params,
        )
        await db.connection.commit()


async def task_state_subtask_fail(subtask_id: int, attempt_no: int, error: str, max_attempts: int) -> str:
    """
    Провал круга Developer/QA. Исчерпанные попытки уводят подзадачу в `blocked` —
    дальше её никто не берёт, нужен человек.

    Returns: новое состояние подзадачи.
    """
    state = 'blocked' if attempt_no >= max_attempts else 'failed_qa'
    await task_state_subtask_set(subtask_id, state, last_error=error, attempt_count=attempt_no,
                                 unless_done=True)
    logger_info(f'[task] subtask#{subtask_id} -> {state} (попытка {attempt_no}): {error}')
    return state


async def task_state_attempt_log(subtask_id: int, attempt_no: int, role: str,
                                 result: dict, started: float) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_task_attempt (task_id, attempt_no, role, status, output, error, duration_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (subtask_id, attempt_no, role,
             'ok' if result.get('ok') else 'error',
             str(result.get('output') or ''), str(result.get('error') or ''),
             int((time.monotonic() - started) * 1000)),
        )
        await db.connection.commit()


# Родители, у которых разработка по плану закончена и всё упёрлось в проверку: есть
# хотя бы один ребёнок в `qa_pending` или `testing` и ни одного, который ещё в работе,
# на повторе или в сбое. Это ровно то, что страница задач показывает чипсом родителя
# (самая отстающая подзадача), поэтому и условие тут повторяет её порядок состояний.
#
# `testing` у ребёнка — та же фаза, что и `qa_pending`, только проверка уже началась:
# QA взял подзадачу в работу. Разработчику там делать нечего, и ждать перевода
# родителя до конца проверки значило бы держать задачу на вкладке «Разработка»,
# когда разработка кончилась.
#
# Считаем только детей из плана (`pipeline_from_plan`): подзадачи, заведённые человеком
# руками, живут своей жизнью — по той же причине их не ждёт и финализация.
_KIDS_AWAITING_QA_SQL = (
    "(SELECT pid FROM ("
    "    SELECT parent_id AS pid FROM project_task "
    "     WHERE parent_id IS NOT NULL AND pipeline_from_plan = 1 "
    "     GROUP BY parent_id "
    "    HAVING SUM(pipeline_state IN ('qa_pending','testing')) > 0 "
    "       AND SUM(pipeline_state IN ('planned','failed_qa','developing','blocked','failed')) = 0"
    ") AS _t)"
)

# Человеческий kanban-статус под каждое состояние конвейера. Переходных состояний
# больше, чем kanban-статусов, поэтому соответствие не взаимно однозначное:
# `active` — над задачей прямо сейчас работает агент,
# `blocked` — работа встала и нужен человек разобрать сбой,
# `queued` — план утверждён, задача ждёт следующего шага конвейера.
#
# Таблица одна на обе ветки: и родительские состояния, и детские. Развилка по
# `parent_id` не нужна: единственное общее значение — `testing`, и означает оно в обеих
# ветках одно и то же (идёт проверка), то есть и kanban-статус у него один. `failed_qa` — это
# `queued`, а не `blocked`: круг повторится сам, человека звать пока не за чем.
# `plan_approval` — `pending`, а не `blocked`: план готов, ничего не сломалось,
# задача просто ждёт решения человека — это и есть «Ожидает».
# `qa_pending` — тоже `pending`: разработчик своё уже сделал, подзадача лежит в очереди
# к QA, и никто над ней прямо сейчас не работает. «В работе» здесь врал бы о ходе дел.
# Как только QA её берёт, состояние становится `testing` — вот оно уже `active`.
_TASK_STATE_KANBAN = {
    'new':              'pending',
    'planning':         'active',
    'plan_approval':    'pending',
    'reviewing':        'active',
    # Баг у багфиксера: работа идёт прямо сейчас, значит «В работе». Своё состояние,
    # а не `developing`, потому что `developing` бывает только у подзадач плана, и
    # карты реклейма у корневых строк и подзадач разные.
    'bugfixing':        'active',
    'approved':         'queued',
    'processing':       'active',
    'testing':          'active',
    'planned':          'queued',
    'developing':       'active',
    'qa_pending':       'pending',
    'failed_qa':        'queued',
    'blocked':          'blocked',
    'done':             'done',
    # Проверять было нечего — для человека это тот же «Готово»: работа
    # закрыта, разница только в том, чем она закрыта, и она видна в
    # состоянии конвейера. Отдельного kanban-статуса под это нет и не нужно:
    # колонок на доске и так больше, чем человек различает на глаз.
    'no_code_for_testing': 'done',
    'failed':           'blocked',
}


def _subtask_state(item: dict) -> str:
    """
    Состояние новой подзадачи: обычная — `planned`, крупная — `new`.

    Тут и включается дробление в глубину. `planned` — начало круга
    Developer → QA, туда идёт подзадача, помещающаяся в память исполнителя.
    А `new` — состояние, из которого работу забирает планирование
    (`task_claim_task_unplanned`: нет своих подзадач, состояние `new`, сама не
    родитель). Никакой отдельной ветки для рекурсии не нужно — подзадача,
    помеченная `split_more`, просто попадает менеджеру как обычная задача, и
    он раскладывает её своим заходом.

    Глубина от этого не ограничена: разложенная подзадача может снова
    оказаться крупной, снова получить `new` и уехать на планирование ещё раз.
    Останавливает это не счётчик уровней, а сам объём — дробить бесконечно
    нечего, куски кончаются.
    """
    return 'new' if item.get('split_more') else 'planned'


def _subtask_metadata(item: dict) -> str | None:
    """
    Мешок новой подзадачи из строки плана менеджера. Пусто — `None`.

    Две пометки, обе ставит менеджер при разбиении:

    * `split_more` — не влезает в память исполнителя, дробить дальше;
    * `context_lines` — его оценка объёма чтения, для разбора провалов.

    Ложь и ноль не пишем: ключа нет — пометки нет, как у флажков фаз. Иначе
    в мешке копился бы след от каждой подзадачи, которую менеджер посмотрел
    и признал обычной.

    **`final` не пишем никогда, что бы менеджер ни прислал.** Подзадача-приёмка
    проверяла сумму работы соседей, а суммы не существует ни в одном дереве: ветки
    режутся от главной, а вливает их человек уже после конвейера. Приёмка стартовала
    до слияния и проверяла то, чего ещё нет, — любой её круг кончался «не сошлось»
    (#1631, три круга подряд). Промпт разбиения это запрещает (миграция
    `20260827140000`), но запрет словами держится ровно до первой невнимательности
    модели, а цена — подзадача, которая не может закрыться никогда. Результат задачи
    целиком принимает человек при слиянии.
    """
    data = {}
    if item.get('split_more'):
        data[TASK_METADATA_KEY_SPLIT_MORE] = True

    lines = item.get('context_lines')
    if isinstance(lines, (int, float)) and lines > 0:
        data[TASK_METADATA_KEY_CONTEXT] = int(lines)

    return json.dumps(data, ensure_ascii=False) if data else None
