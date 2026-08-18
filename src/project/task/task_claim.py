"""
Захват работы конвейера и возврат брошенных блокировок.

Запуски крона могут накладываться, поэтому захват — условный `UPDATE` с проверкой
`rowcount`, а не `SELECT ... FOR UPDATE`: два воркера не должны взять одну строку.
Если воркер умрёт посреди перехода, строка залипнет в переходном состоянии —
`task_claim_locks_reclaim()` возвращает такие строки в работу, как только видит,
что job'а за ними в очереди больше нет.
"""
import os
import socket

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_metadata import (
    task_metadata_bugfix_free_sql,
    task_metadata_plan_free_sql,
    task_metadata_stop_free_sql,
    task_metadata_test_free_sql,
)
from src.project.task.task_role import (TASK_ROLE_BUGFIXER, task_role_project_sql,
                                        task_role_project_type_sql, task_role_type_sql)
from src.project.task.task_state import task_state_kanban_sql, task_state_subtask_set
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_TASK_LOCK,
    task_setting_timeout_get)
from src.worker.project.task_worker import TASK_WORKER_ENQUEUE_GRACE_SEC, task_worker_live_targets

# Срок блокировки — настройка `timeout_task_lock` (правится на `/admin/team`, см.
# `task_setting_timeout`). Он заведомо больше ожидания агента: те работают через живые
# shell-оболочки и думают минутами, а блокировку нельзя признать протухшей раньше,
# чем прогон сам сорвётся по своему таймауту. Признак запасной — основной (пропал
# job) срабатывает куда раньше, см. `task_claim_locks_reclaim`.

# Строку, чей job из очереди пропал, ждать полный срок блокировки незачем —
# доводить её до конца уже некому. Запас нужен только на разрыв между захватом
# строки и постановкой сообщения в очередь.
LOCK_ORPHAN_GRACE_SEC = TASK_WORKER_ENQUEUE_GRACE_SEC

# Как часто работающий job подновляет свою блокировку (`task_claim_lock_touch`).
# Заведомо меньше `LOCK_ORPHAN_GRACE_SEC`: пока job жив, его строка не должна
# доживать до возраста, при котором реклейм вправе счесть её брошенной, — иначе
# сбой опроса очереди отбирает работу у живого агента.
TASK_CLAIM_LOCK_TOUCH_SEC = 45

# Переходные состояния и то, куда их возвращать при брошенной блокировке.
# Для reviewing состояние то же — снимается только сама блокировка.
#
# `reviewing` нельзя возвращать в `new`, как `planning`: план у такой задачи есть, и
# `task_claim_task_unplanned` её не подберёт — задача залипла бы навсегда. Оставляем
# ждать пересмотра, за ней придёт следующий тик.
#
# `testing` возвращается в `qa_pending`: брошенная проверка — это работа, которой не
# было, и подзадача снова становится в очередь к QA, а не считается проверенной.
#
# Карты разделены по ветке дерева: `testing` бывает и у корневой задачи, но там это
# фаза «задача на проверке», а не захваченная работа, и возвращать её в `qa_pending`
# нельзя. Кто отменяет работу на ходу (реклейм, снятый флажок «в разработку» —
# `task_stop`), берёт карту по наличию `parent_id`.
# `bugfixing` возвращается в `new`: брошенная починка — это работа, которой не было,
# и баг снова встаёт в очередь к багфиксеру. В `failed` его такой возврат уводить не
# должен — там баг ждал бы человека из-за упавшего воркера, а не из-за самого бага.
TASK_CLAIM_STATE_RECLAIM = {'planning': 'new', 'reviewing': 'reviewing', 'bugfixing': 'new'}
TASK_CLAIM_SUBTASK_STATE_RECLAIM = {'developing': 'planned', 'testing': 'qa_pending'}

# Состояния «работа в полёте»: строка захвачена, и за ней прямо сейчас думает агент
# в живой оболочке. Это ровно те же переходные состояния, что возвращает реклейм, —
# список один, чтобы новое переходное состояние не пришлось помнить в двух местах.
# Разбор плана (`approved` -> `processing`) сюда не входит: он идёт в воркере без
# похода в LLM и карточку команды не занимает.
TASK_CLAIM_INFLIGHT_STATES = tuple(TASK_CLAIM_STATE_RECLAIM) + tuple(TASK_CLAIM_SUBTASK_STATE_RECLAIM)

# Родители, у которых уже есть подзадачи из плана. Обёртка в производную таблицу —
# MySQL 1093 запрещает читать в UPDATE ту же таблицу, которую пишет.
_SPLIT_PARENTS_SQL = (
    "(SELECT pid FROM ("
    "    SELECT DISTINCT parent_id AS pid FROM project_task "
    "    WHERE parent_id IS NOT NULL AND pipeline_from_plan = 1"
    ") AS _t)"
)


def task_claim_worker_id() -> str:
    return f'{socket.gethostname()}:{os.getpid()}'[:64]


async def task_claim_task(state_from: str, state_to: str, worker: str) -> dict | None:
    """
    Перевести одну задачу state_from -> state_to и вернуть её.
    None, если подходящих нет или строку увёл параллельный воркер.
    """
    return await _task_claim(
        "pipeline_state = %s", [state_from], state_to, worker)


async def task_claim_task_unplanned(worker: str, roles_by_project) -> dict | None:
    """
    Захватить задачу без плана и увести её в `planning`.

    `roles_by_project` — живые оболочки в разрезе проектов (`task_role`). Берём
    только задачи своего проекта и только тех типов, которые эти роли планируют:
    план багу пишет карточка QA, а не менеджер, и карточка чужого проекта не
    забирает задачу соседнего. Пустой словарь — не берём ничего.

    Человеческий `status` при отборе не смотрим: критерий — плана нет ИЛИ
    целей нет. Задача может и не быть заведена в конвейер явно (`pipeline_state IS
    NULL`) — план менеджер пишет всё равно.

    «Плана нет» — это ноль подзадач в `pipeline_plan`. Битый JSON приравниваем
    к пустому плану (через `JSON_VALID`). «Целей нет» — пустой массив в колонке
    `goals`. Если план есть, а целей нет — задача тоже попадает к менеджеру,
    чтобы дописать цели.

    `failed` сюда не попадает намеренно: у сорвавшегося менеджера план так и
    остался пустым, и без этого фильтра тик подбирал бы такую задачу вечно.

    Задачи с подзадачами тоже не берём: родитель — контейнер, его планом уже
    является список детей. Иначе эпик с пятью подзадачами дал бы шесть походов в
    LLM, а план родителя пересказывал бы то, что и так разложено по детям.
    Подзапрос обёрнут в производную таблицу — MySQL не даёт читать в UPDATE ту же
    таблицу, которую пишет (ошибка 1093).

    Подзадачи, разложенные конвейером, отдельно исключать не нужно: у них
    `pipeline_state = 'planned'`, а фильтр берёт только NULL и `new`.

    Снятый флажок «в планирование» (`metadata.to_planning = false`) задачу отсюда
    убирает: человек завёл её, но плана пока не просит. Проверка стоит только в этом
    отборе, а не в общем `_task_claim`, — пометка запрещает написание плана, а не
    работу вообще, и задачу, у которой план уже есть, тормозить ей нечего.
    """
    # Родительские задачи (их не берёт ни один шаг).
    # Обёртка в derived table — MySQL 1093 запрещает читать из UPDATE ту же таблицу.
    subparents = (
        "(SELECT pid FROM ("
        "    SELECT DISTINCT parent_id AS pid FROM project_task "
        "    WHERE parent_id IS NOT NULL"
        ") AS _t)"
    )
    role_sql, role_params = task_role_project_type_sql(roles_by_project)
    return await _task_claim(
        # (Нет подзадач в pipeline_plan ИЛИ goals пустой/битый)
        # pipeline_state новый или NULL, не родитель, проект и тип — за живой карточкой
        f"(COALESCE(JSON_LENGTH(JSON_EXTRACT("
        "    IF(JSON_VALID(pipeline_plan), pipeline_plan, '{}'), '$.subtasks')), 0) = 0 "
        " OR JSON_LENGTH(COALESCE("
        "    IF(JSON_VALID(goals), goals, '[]'), '$')) = 0) "
        " AND (pipeline_state IS NULL OR pipeline_state = 'new') "
        f" AND id NOT IN ({subparents} ) AND {task_metadata_plan_free_sql()} AND {role_sql}",
        role_params, 'planning', worker)


async def task_claim_task_review(worker: str, roles_by_project) -> dict | None:
    """
    Захватить задачу, отправленную человеком на пересмотр плана.

    Состояние не меняется — `reviewing` остаётся `reviewing`, ставится только блокировка.
    Из-за этого условие на свободную блокировку
    обязано быть в самом `where`: в `_task_claim` от второго воркера защищает переход
    состояния, а здесь перехода нет, и без проверки задачу взяли бы двое.

    `roles_by_project` — то же, что и в `task_claim_task_unplanned`: пересмотр плана
    делает та же карточка того же проекта, что писала план, поэтому фильтр здесь тот же.
    """
    role_sql, role_params = task_role_project_type_sql(roles_by_project)
    return await _task_claim(
        "pipeline_state = 'reviewing' AND (pipeline_locked_at IS NULL OR pipeline_locked_by = '') "
        f"AND {role_sql}",
        role_params, 'reviewing', worker)


async def task_claim_task_bug(worker: str, roles_by_project) -> dict | None:
    """
    Захватить баг и увести его в `bugfixing`.

    Вход в работу у бага автоматический: заведённая строка типа `bug` уходит
    багфиксеру ближайшим тиком. Плана он не пишет и утверждения не ждёт — чинить
    начинают сразу, поэтому и состояние тут одно, рабочее.

    Отбираем только корневые строки: подзадач у бага не бывает, а `parent_id IS NOT NULL`
    в этом состоянии означало бы строку чужого плана.

    `status <> 'cancelled'` стоит здесь явно, в отличие от остальных шагов. Те смотрят
    только на `pipeline_state`, и отменённая задача им не попадается по другой причине:
    у неё либо уже есть план, либо человек её в конвейер не заводил. У бага же по пути
    нет ни одного человеческого решения — без этого условия отменённый баг ушёл бы
    чиниться молча.

    Тип отбираем через `task_role_type_sql`, а не руками: условие по именам типов уже
    описано там, и второй его экземпляр разошёлся бы с первым при первой же правке карты.

    `roles_by_project` — живые оболочки в разрезе проектов (`task_role`). Роль здесь
    одна, `bugfixer`, и тип задан отдельным условием, поэтому берём
    `task_role_project_sql` (только проект), а не `task_role_project_type_sql`.
    Нет живой карточки — не берём вовсе: прогон сорвался бы на первом же обращении к
    оболочке, а баг ушёл бы в `failed` и потребовал человека на ровном месте.

    Снятый флажок «в багфикс» (`metadata.to_bugfix = false`) баг отсюда убирает: человек
    завёл его, но чинить пока не просит.
    """
    type_sql, type_params = task_role_type_sql([TASK_ROLE_BUGFIXER])
    role_sql, role_params = task_role_project_sql(roles_by_project, TASK_ROLE_BUGFIXER)
    return await _task_claim(
        "parent_id IS NULL AND (pipeline_state IS NULL OR pipeline_state = 'new') "
        f"AND status <> 'cancelled' AND {type_sql} "
        f"AND {task_metadata_bugfix_free_sql()} AND {role_sql}",
        type_params + role_params, 'bugfixing', worker)


async def task_claim_subtask(state_from: str, state_to: str, worker: str,
                             where_extra: str = '', params_extra: list | None = None) -> dict | None:
    """
    То же для подзадачи. state_to может совпадать с state_from — тогда это только блокировка.

    Подзадача — строка того же `project_task` с непустым `parent_id`, поэтому захват общий;
    отличается только порядок: внутри родителя идём по `position`, чтобы шаги плана
    выполнялись в том порядке, в каком их написал менеджер.

    Свободная блокировка проверяется прямо в условии: при state_to == state_from перехода
    состояния нет, и без этой проверки строку взяли бы двое.

    `where_extra` — дополнительное условие отбора (`task_role_project_sql`: проект
    строки за живой оболочкой). Пустое — берём подзадачу любого проекта.
    """
    where = ("parent_id IS NOT NULL AND pipeline_state = %s "
             "AND (pipeline_locked_at IS NULL OR pipeline_locked_by = '')")
    params = [state_from]
    if where_extra:
        where += f' AND {where_extra}'
        params += list(params_extra or [])

    return await _task_claim(where, params, state_to, worker, order='parent_id, position, id')


async def task_claim_subtask_developable(worker: str, roles_by_project, max_attempts: int) -> dict | None:
    """
    Свежая подзадача либо возврат от QA, у которого ещё остались попытки.
    Исчерпавшие лимит лежат в `blocked` и сюда не попадают.

    `roles_by_project` — живые оболочки в разрезе проектов (`task_role`). Разработчик
    работает в живом Claude Code каталога своего проекта, поэтому подзадача чужого
    проекта или проекта с погасшей карточкой не берётся вовсе: захват сжёг бы попытку
    из отведённых `max_attempts` на прогоне, который заведомо сорвётся. Пустой
    словарь — не берём ничего, подзадачи ждут запуска оболочки.
    """
    role_sql, role_params = task_role_project_sql(roles_by_project, 'developer')
    for state_from in ('planned', 'failed_qa'):
        subtask = await task_claim_subtask(state_from, 'developing', worker, role_sql, role_params)
        if not subtask:
            continue
        if int(subtask['pipeline_attempt_count']) < max_attempts:
            return subtask
        # Лимит исчерпан уже после захвата — вернуть в blocked, дальше не крутить.
        await task_state_subtask_set(subtask['id'], 'blocked')
    return None


async def task_claim_subtask_testable(worker: str, roles_by_project) -> dict | None:
    """
    Подзадача, дождавшаяся проверки, — но только там, где жива оболочка QA.

    Фильтр тот же, что у разработчика, и по той же причине: QA проверяет чужую
    работу живым Claude Code в каталоге проекта, и без карточки прогон сорвался бы
    на первом шаге. Разница в роли: `qa`, а не `developer` — проверять обязана
    оболочка, которая код не писала, иначе самопроверка разработчика и проверка QA
    сходятся в один контекст.

    Второй фильтр — флажок «в тестирование» родителя (`task_metadata_test_free_sql`):
    снятый флажок запрещает проверку, и подзадача ждёт в `qa_pending`, пока человек
    не вернёт галку.

    Захват меняет состояние: `qa_pending` -> `testing`. Разница между «ждёт очереди
    к QA» и «QA проверяет прямо сейчас» видна человеку только по состоянию —
    блокировку страница задач не показывает, и подзадача под живой проверкой
    выглядела бы застрявшей в очереди. Своё состояние заодно защищает строку от
    второго воркера самим переходом, как у разработчика.
    """
    role_sql, role_params = task_role_project_sql(roles_by_project, 'qa')
    where = ' AND '.join(part for part in (role_sql, task_metadata_test_free_sql()) if part)
    return await task_claim_subtask('qa_pending', 'testing', worker, where, role_params)


async def task_claim_locks_reclaim() -> int:
    """
    Вернуть в работу строки, чей воркер умер, не доведя переход до конца.

    Признаков брошенной блокировки два, и главный из них — пропавший job.
    Переходное состояние держится сообщением в очереди: нет job'а — нет и того, кто
    доведёт переход, ждать нечего, и строка возвращается сразу по истечении запаса
    на постановку в очередь (`TASK_WORKER_ENQUEUE_GRACE_SEC`). Это основной случай:
    контейнеры перезапускают после каждой правки `.py`, и всё, что было в полёте,
    иначе простояло бы больше часа.

    Таймаут (`timeout_task_lock`) остаётся запасным признаком — на случай, когда
    очередь недоступна и проверить job нечем, или когда job жив, а работа в нём
    встала намертво.

    Оба признака смотрят на возраст блокировки, а живой job подновляет её сам
    (`task_claim_lock_touch`), поэтому строка под работающим агентом до возраста
    `LOCK_ORPHAN_GRACE_SEC` не доживает и под реклейм не попадает, даже если
    очередь на секунду перестала показывать её job. Так и должно быть: сведения
    из Redis о часовом прогоне живут минутами и обновляются самим rq, а цена
    ошибки здесь — снятая блокировка у работающего агента и, следом, лишний
    прогон сверх предела «Parallel LLM».

    Хозяина блокировки (`pipeline_locked_by`) не проверяем вовсе: строку блокирует
    тик внутри uvicorn, а выполняет её job в контейнере воркера, и по имени хоста
    в блокировке живость исполнителя не определяется — это разные процессы.
    """
    live = task_worker_live_targets()
    live_tasks = None if live is None else live['task_id']
    live_subtasks = None if live is None else live['subtask_id']
    lock_timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_TASK_LOCK)

    total = 0
    async with mysql_get_db_async() as db:
        for state_from, state_to in TASK_CLAIM_STATE_RECLAIM.items():
            total += await _lock_reclaim(db, state_from, state_to, live_tasks, lock_timeout)

        # Разбор плана на подзадачи: состояние `processing` задача не покидает и после
        # успеха, поэтому по нему одному брошенность не видна — отличает её пустой
        # список детей из плана. Job'а нет, детей нет: подзадачи создаются одной
        # транзакцией, значит не создалась ни одна, и повтор ничего не задвоит.
        total += await _lock_reclaim(
            db, 'processing', 'approved', live_tasks, lock_timeout,
            extra=f' AND id NOT IN {_SPLIT_PARENTS_SQL}')

        for state_from, state_to in TASK_CLAIM_SUBTASK_STATE_RECLAIM.items():
            total += await _lock_reclaim(db, state_from, state_to, live_subtasks, lock_timeout,
                                         extra=' AND parent_id IS NOT NULL')

        await db.connection.commit()

    if total:
        logger_info(f'[task] сброшено брошенных блокировок: {total}')
    return total


async def task_claim_lock_touch(row_id: int) -> bool:
    """
    Подновить блокировку строки: «job ещё жив, работа идёт».

    Зовёт сам работающий job раз в `TASK_CLAIM_LOCK_TOUCH_SEC` секунд
    (`task_pipeline_action_run`). Блокировка от этого перестаёт стареть, а вместе
    с ней перестаёт стареть и признак брошенности: реклейм судит по возрасту.

    False — подновлять больше нечего: блокировку уже сняли (реклейм, ручной
    повтор, человек на странице задач). Для зовущего это сигнал прекратить —
    строка больше не его, и ставить на неё чужую метку времени нельзя.
    """
    if not row_id:
        return False

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task SET pipeline_locked_at = NOW() "
            " WHERE id = %s AND pipeline_locked_at IS NOT NULL AND pipeline_locked_by <> ''",
            (int(row_id),))
        touched = db.rowcount
        await db.connection.commit()

    return bool(touched)


async def task_claim_inflight_by_project() -> dict[int, int]:
    """
    Сколько прогонов агента уже идёт у каждого проекта: `{project_id: число}`.

    Это счётчик для предела «Parallel LLM» (`task_setting_parallel`). Работа в полёте —
    строка в переходном состоянии (`TASK_CLAIM_INFLIGHT_STATES`) с занятой
    блокировкой: её захватил тик, за ней стоит job, и агент в оболочке проекта либо
    уже думает, либо вот-вот начнёт. Считаются и задачи, и подзадачи: подзадача
    наследует `project_id` родителя, а оболочка у проекта одна на всех.

    Проектов без работы в словаре нет. Ключ 0 — строки вне проектов, тот же
    «Без проекта», что и в блоках команды.

    Считать имеет смысл только после `task_claim_locks_reclaim()`: до него в выборку
    попадут строки умерших воркеров, и проект молчал бы до истечения блокировки.
    """
    placeholders = ', '.join(['%s'] * len(TASK_CLAIM_INFLIGHT_STATES))
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT COALESCE(project_id, 0) AS pid, COUNT(*) AS cnt FROM project_task "
            f" WHERE pipeline_state IN ({placeholders}) "
            "   AND pipeline_locked_at IS NOT NULL AND pipeline_locked_by <> '' "
            " GROUP BY COALESCE(project_id, 0)",
            list(TASK_CLAIM_INFLIGHT_STATES))
        rows = await db.fetchall()

    return {int(row['pid']): int(row['cnt']) for row in rows or []}


async def _task_claim(where: str, params: list, state_to: str, worker: str,
                      order: str = 'id') -> dict | None:
    """
    Общий захват задачи: выбрать первую подходящую под `where` и перевести её
    в `state_to`. Условие повторяется в UPDATE, поэтому строку не увести дважды.

    `pipeline_started_at` ставится здесь и дальше не меняется: это начало работы, а
    не её признак. `pipeline_locked_at` на ту же роль не годится — живой job
    подновляет его на ходу (`task_claim_lock_touch`), и возраст блокировки говорит
    про job, а не про прогон. Остаток до таймаута агента на карточках команды
    считается от начала.

    Остановленные человеком строки отсекаются здесь, а не в каждом отборе по
    отдельности: захват один на все шаги конвейера, и это единственное место, где
    пометку нельзя забыть проверить. Человеческий `status` для запрета не годится —
    отбор его не смотрит, и «Ожидает», выставленное руками, тик перебил бы сразу же.
    """
    where = f'({where}) AND {task_metadata_stop_free_sql()}'
    async with mysql_get_db_async() as db:
        await db.execute(f"SELECT id FROM project_task WHERE {where} ORDER BY {order} LIMIT 1", params)
        row = await db.fetchone()
        if not row:
            return None

        kanban_sql, kanban_params = task_state_kanban_sql(state_to)
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, {kanban_sql + ', ' if kanban_sql else ''}"
            f"       pipeline_locked_at = NOW(), pipeline_started_at = NOW(), pipeline_locked_by = %s "
            f" WHERE id = %s AND {where}",
            [state_to] + kanban_params + [worker, row['id']] + params,
        )
        claimed = db.rowcount
        await db.connection.commit()
        if not claimed:
            return None  # успели раньше нас

        await db.execute("SELECT * FROM project_task WHERE id = %s", (row['id'],))
        task = await db.fetchone()

    return dict(task) if task else None


async def _lock_reclaim(db, state_from: str, state_to: str, live_ids: set | None,
                        lock_timeout: int, extra: str = '') -> int:
    """
    Один UPDATE реклейма: строки в `state_from` с брошенной блокировкой -> `state_to`.

    `extra` — дополнительное условие отбора (подзадачи, незавершённый `processing`).
    Коммит не делает: все реклеймы одного тика закрываются одной транзакцией.

    Сначала выбираем id, потом обновляем по ним: реклейм — событие редкое и
    неприятное, и в журнале должно быть видно, у кого именно отобрали работу, а
    не только сколько строк. В обычном тике выборка пуста, и UPDATE не идёт вовсе.
    Условие в UPDATE остаётся полным: между двумя запросами строку мог увести
    кто-то ещё, и `id IN` здесь — уточнение, а не замена проверки.
    """
    stale_sql, stale_params = _lock_stale_sql(live_ids, lock_timeout)
    where = (f"pipeline_state = %s{extra} AND pipeline_locked_at IS NOT NULL AND {stale_sql}")
    params = [state_from] + stale_params

    await db.execute(f"SELECT id, pipeline_locked_by FROM project_task WHERE {where}", params)
    rows = await db.fetchall() or []
    if not rows:
        return 0

    kanban_sql, kanban_params = task_state_kanban_sql(state_to)
    placeholders = ', '.join(['%s'] * len(rows))
    await db.execute(
        f"UPDATE project_task SET pipeline_state = %s, {kanban_sql + ', ' if kanban_sql else ''}"
        "       pipeline_locked_at = NULL, pipeline_locked_by = '' "
        f" WHERE {where} AND id IN ({placeholders})",
        [state_to] + kanban_params + params + [int(row['id']) for row in rows],
    )
    if db.rowcount:
        freed = ', '.join(f"#{row['id']}({row['pipeline_locked_by'] or '?'})" for row in rows)
        logger_info(f'[task] реклейм {state_from} -> {state_to}: {freed}')
    return db.rowcount


def _lock_stale_sql(live_ids: set | None, lock_timeout: int) -> tuple[str, list]:
    """
    Условие «держать блокировку больше некому».

    `live_ids` — строки, за которыми в очереди ещё стоит job; их не трогаем, пока не
    выйдет полный `lock_timeout`. Остальные брошены, и хватает короткого запаса
    на постановку в очередь. `live_ids is None` — очередь не ответила, остаётся один
    таймаут: считать, что job'ов нет вообще, значило бы отобрать строку у живого.
    """
    stale = "pipeline_locked_at < NOW() - INTERVAL %s SECOND"
    if live_ids is None:
        return stale, [lock_timeout]

    orphan = "pipeline_locked_at < NOW() - INTERVAL %s SECOND"
    params = [lock_timeout, LOCK_ORPHAN_GRACE_SEC]
    if live_ids:
        placeholders = ', '.join(['%s'] * len(live_ids))
        orphan += f" AND id NOT IN ({placeholders})"
        params += sorted(live_ids)
    return f"({stale} OR ({orphan}))", params
