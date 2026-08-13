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
from src.project.task.task_metadata import TASK_METADATA_KEY_DEV, TASK_METADATA_KEY_TEST
from src.project.task.task_plan import (
    task_plan_goals_close,
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
    """
    kanban = task_state_kanban_status(pipeline_state)
    if not kanban:
        return '', []
    return "status = IF(status = 'cancelled', status, %s)", [kanban]


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


async def task_state_dev_to_testing(task_id: int) -> bool:
    """
    Задача разработки, дошедшая до проверки: тип -> `test`, состояние -> `testing`.

    Зеркало `task_state_plan_to_development` на следующей развилке конвейера. Там человек
    заранее говорит «план утверждать не надо», здесь — «готовую работу на проверку
    отдавать не спрашивая»; разница только в умолчании: пометка `metadata.to_testing`
    считается стоящей, пока её явно не сняли (`<> FALSE`, а не `= TRUE`).

    «Дошла до проверки» — это состояние, которое страница задач и так показывает у
    родителя чипсом: самая отстающая подзадача из плана в `qa_pending`. То есть по всем
    веткам плана разработчик своё закончил и ни одна не осталась в работе, на повторе
    или в сбое. Смотрим детей, а не саму задачу: `qa_pending` — состояние детской ветки,
    родителю его не выставляет никто, у него всё это время `processing`.

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
    kanban = task_state_kanban_status('planned')
    async with mysql_get_db_async() as db:
        for position, item in enumerate(subtasks):
            goals = task_plan_goals_normalize(item.get('goals'))
            plan_text = str(item.get('plan') or '')
            # Пустой план подзадачи оставляем пустой строкой, а не JSON-пустышкой:
            # так поле в форме выглядит незаполненным, а не «планом ни о чём».
            plan_json = task_plan_serialize(plan_text, [], goals) if plan_text or goals else ''
            await db.execute(
                "INSERT INTO project_task "
                "       (project_id, parent_id, title, description, goals, pipeline_plan, "
                "        position, status, task_type_id, pipeline_state, pipeline_from_plan) "
                "SELECT t.project_id, t.id, %s, %s, %s, %s, %s, %s, "
                "       (SELECT id FROM project_task_type WHERE name = 'dev'), 'planned', 1 "
                "  FROM project_task t WHERE t.id = %s",
                (str(item.get('title') or ''), str(item.get('description') or ''),
                 json.dumps(goals, ensure_ascii=False) if goals else '',
                 plan_json, position, kanban, task_id),
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


async def task_state_goals_close(task_id: int) -> int:
    """
    Отметить все цели задачи выполненными. Returns: сколько целей отмечено.

    Зовётся, когда работа принята: QA закрыл подзадачу, финализация закрыла задачу.
    Цели — это список того, что проверялось, и у готовой задачи пустые чекбоксы
    читаются как «ничего не сделано». Ставим все разом, а не по одной: вердикт QA
    в конвейере один на подзадачу — «прошло» или «на доработку», и разбирать, какая
    именно цель закрылась, нечем.

    Отдельным UPDATE, а не внутри перевода состояния: закрывают цели два разных
    места, а состояние там меняется по-своему.
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT goals FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()
        goals_json = task_plan_goals_close((row or {}).get('goals'))
        if goals_json is None:
            return 0
        await db.execute("UPDATE project_task SET goals = %s WHERE id = %s", (goals_json, task_id))
        await db.connection.commit()
    count = len(task_plan_goals_normalize(goals_json))
    logger_info(f'[task] task#{task_id}: цели отмечены выполненными ({count})')
    return count


async def task_state_task_requeue(task_id: int, state: str, error: str) -> None:
    """
    Вернуть задачу в состояние, из которого её снова подберёт тик, и снять блокировку.

    Нужна для повтора сорвавшегося прогона (`task_retry`): менеджер не ответил, но
    работы он и не сделал — хоронить задачу в `failed` не за что, её надо просто
    отдать следующему тику. Состояние выбирает вызывающий, и оно то же, что у возврата
    брошенной блокировки (`task_claim._TASK_STATE_RECLAIM`): планирование -> `new`,
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
            "       SUM(c.pipeline_state NOT IN ('done','blocked','failed')) AS pending_cnt, "
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


async def task_state_subtask_set(subtask_id: int, state: str, last_error: str | None = None,
                                 attempt_count: int | None = None) -> None:
    """
    Новое состояние подзадачи со снятием блокировки.

    `parent_id IS NOT NULL` в условии — та же страховка, что и в `task_state_subtask_get`:
    детские состояния родителю выставлять нельзя, иначе ветки конвейера перепутаются.
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

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET {', '.join(s for s in sets if s)} "
            "WHERE id = %s AND parent_id IS NOT NULL",
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
    await task_state_subtask_set(subtask_id, state, last_error=error, attempt_count=attempt_no)
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
# хотя бы один ребёнок в `qa_pending` и ни одного, который ещё в работе, на повторе или
# в сбое. Это ровно то, что страница задач показывает чипсом родителя (самая отстающая
# подзадача), поэтому и условие тут повторяет её порядок состояний.
#
# Считаем только детей из плана (`pipeline_from_plan`): подзадачи, заведённые человеком
# руками, живут своей жизнью — по той же причине их не ждёт и финализация.
_KIDS_AWAITING_QA_SQL = (
    "(SELECT pid FROM ("
    "    SELECT parent_id AS pid FROM project_task "
    "     WHERE parent_id IS NOT NULL AND pipeline_from_plan = 1 "
    "     GROUP BY parent_id "
    "    HAVING SUM(pipeline_state = 'qa_pending') > 0 "
    "       AND SUM(pipeline_state IN ('planned','failed_qa','developing','blocked','failed')) = 0"
    ") AS _t)"
)

# Человеческий kanban-статус под каждое состояние конвейера. Переходных состояний
# больше, чем kanban-статусов, поэтому соответствие не взаимно однозначное:
# `active` — над задачей прямо сейчас работает агент,
# `blocked` — работа встала и нужен человек разобрать сбой,
# `queued` — план утверждён, задача ждёт следующего шага конвейера.
#
# Таблица одна на обе ветки: и родительские состояния, и детские. Ветки не пересекаются
# по значениям, так что развилка по `parent_id` здесь не нужна. `failed_qa` — это
# `queued`, а не `blocked`: круг повторится сам, человека звать пока не за чем.
# `plan_approval` — `pending`, а не `blocked`: план готов, ничего не сломалось,
# задача просто ждёт решения человека — это и есть «Ожидает».
# `qa_pending` — тоже `pending`: разработчик своё уже сделал, задача лежит в очереди
# к QA, и никто над ней прямо сейчас не работает. «В работе» здесь врал бы о ходе дел.
_TASK_STATE_KANBAN = {
    'new':              'pending',
    'planning':         'active',
    'plan_approval':    'pending',
    'reviewing':        'active',
    'approved':         'queued',
    'processing':       'active',
    'testing':          'active',
    'planned':          'queued',
    'developing':       'active',
    'qa_pending':       'pending',
    'failed_qa':        'queued',
    'blocked':          'blocked',
    'done':             'done',
    'failed':           'blocked',
}
