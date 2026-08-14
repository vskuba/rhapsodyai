"""
Очередь работ по ролям для карточек `/admin/team`: сколько задач ждёт роль и что
она делает прямо сейчас.

Отбор повторяет SQL захвата из `task_claim`, а не человеческий `status` задачи:
«ждёт менеджера» — это ровно то, что подберёт следующий тик конвейера, и никакая
другая колонка этого не показывает. Порядок в выдаче тоже совпадает с порядком
захвата, поэтому первый элемент списка ожидания — следующий кандидат в работу.

«В работе» и «в очереди» различаются блокировкой: захват ставит `pipeline_locked_by`,
а состояние при этом может не меняться — так устроен захват `reviewing`.

Подзадача — строка того же `project_task` с непустым `parent_id`, поэтому запросы
Developer/QA — это самосоединение: ребёнок даёт работу, родитель — название задачи,
в которой она стоит.

Разрез — по проекту: карточки на странице сгруппированы блоками проектов. Сам
конвейер проектом не ограничен, поэтому цифра на карточке отвечает на вопрос
«сколько задач этого проекта ждут роль», а не «сколько всего работы у роли».
"""
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    TASK_SETTING_TIMEOUT_DEVELOPER_RUN,
    TASK_SETTING_TIMEOUT_MANAGER_RUN,
    TASK_SETTING_TIMEOUT_QA_RUN,
    task_setting_timeout_get)
from src.project.task.task_role import TASK_ROLE_TYPES, task_role_type_sql
from src.project.team.team_progress import team_progress_running

# Сколько задач очереди показываем на карточке — списком, а не только числом.
TEAM_QUEUE_PREVIEW_LIMIT = 3

# Задачи без проекта попадают в блок «Без проекта», у которого project_id = 0.
TEAM_QUEUE_PROJECT_NONE = 0


async def team_queue_by_project() -> dict[int, dict[str, dict]]:
    """Очереди ролей в разрезе проектов.

    Returns:
        {project_id: {role: {'waiting_count': int, 'waiting': [item], 'current': item|None}}}
        где item — {'task_id', 'subtask_id', 'title', 'task_title', 'state', 'left_seconds'}.
    """
    queues: dict[int, dict[str, dict]] = {}

    # Планирование раскладывается по ролям типом задачи (`task_role`), круг
    # Developer/QA — нет: подзадачи утверждённого плана всегда делает разработчик,
    # а проверяет QA. Поэтому у developer и qa по два источника строк, и
    # `_slot_get` копит их в одну ячейку.
    #
    # Таймаут берётся по источнику строк, а не по имени роли: планирование любой
    # роли — это прогон менеджерского агента (`task_agent_manager`), и ждут его
    # столько, сколько указано в «Ответ менеджера».
    plan_timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_MANAGER_RUN)
    # Один запрос на всю выдачу: работающих прогонов единицы, а строк очереди сотни.
    progress = await team_progress_running()
    for role, rows, timeout in (
        [(role, await _planner_rows(role), plan_timeout) for role in TASK_ROLE_TYPES] + [
            ('developer', await _developer_rows(),
             await task_setting_timeout_get(TASK_SETTING_TIMEOUT_DEVELOPER_RUN)),
            ('qa', await _qa_rows(),
             await task_setting_timeout_get(TASK_SETTING_TIMEOUT_QA_RUN)),
        ]
    ):
        for row in rows:
            slot = _slot_get(queues, row.get('project_id'), role)
            item = _item_build(row, timeout, progress)
            if int(row.get('busy') or 0):
                # Воркеров может быть несколько, но карточка роли одна: показываем
                # первую по порядку захвата — остальные видны в списке задач.
                if slot['current'] is None:
                    slot['current'] = item
                continue
            slot['waiting_count'] += 1
            if len(slot['waiting']) < TEAM_QUEUE_PREVIEW_LIMIT:
                slot['waiting'].append(item)

    return queues


async def _planner_rows(role: str) -> list[dict]:
    """Задачи, которые ждут планирования этой ролью или уже у неё в работе.

    Три случая: захваченное планирование/пересмотр (в работе), отправленный
    человеком пересмотр плана (ждёт) и задача без плана либо без целей (ждёт).
    Последнее условие — копия `task_claim_task_unplanned`: родительские задачи
    исключены, битый JSON приравнен к пустому.

    Роль отбирается типом задачи (`task_role`), тем же условием, что и в захвате:
    баги и тестирование планирует QA, разработку — разработчик, остальное менеджер.
    Живой оболочки здесь, в отличие от захвата, не требуется — карточка для того и
    показывает очередь, чтобы было видно, что ждёт погашенную роль.
    """
    subparents = ("SELECT DISTINCT parent_id FROM project_task "
                  " WHERE parent_id IS NOT NULL")
    role_sql, role_params = task_role_type_sql([role], column='t.task_type_id')
    sql = (
        "SELECT t.id AS task_id, NULL AS subtask_id, t.project_id, "
        "       t.title, t.title AS task_title, t.pipeline_state AS state, "
        "       (t.pipeline_locked_by <> '') AS busy, "
        "       TIMESTAMPDIFF(SECOND, t.pipeline_started_at, NOW()) AS run_seconds, "
        "       CASE WHEN t.pipeline_state = 'reviewing' THEN 0 ELSE 1 END AS claim_order "
        "  FROM project_task t "
        f" WHERE {role_sql} AND ("
        "        (t.pipeline_state IN ('planning', 'reviewing') AND t.pipeline_locked_by <> '') "
        "    OR (t.pipeline_state = 'reviewing' "
        "        AND (t.pipeline_locked_at IS NULL OR t.pipeline_locked_by = '')) "
        "    OR ((COALESCE(JSON_LENGTH(JSON_EXTRACT("
        "            IF(JSON_VALID(t.pipeline_plan), t.pipeline_plan, '{}'), '$.subtasks')), 0) = 0 "
        "         OR JSON_LENGTH(COALESCE(IF(JSON_VALID(t.goals), t.goals, '[]'), '$')) = 0) "
        "        AND (t.pipeline_state IS NULL OR t.pipeline_state = 'new') "
        f"        AND t.id NOT IN ({subparents}))) "
        " ORDER BY claim_order, t.id"
    )

    return await _rows_fetch(sql, tuple(role_params))


async def _developer_rows() -> list[dict]:
    """Подзадачи в разработке и ожидающие разработчика.

    Исчерпавшие попытки не показываем: захват уводит такие в `blocked`, работой
    они уже не станут.
    """
    sql = (
        "SELECT s.id AS subtask_id, s.parent_id AS task_id, t.project_id, "
        "       s.title, t.title AS task_title, s.pipeline_state AS state, "
        "       (s.pipeline_locked_by <> '') AS busy, "
        "       TIMESTAMPDIFF(SECOND, s.pipeline_started_at, NOW()) AS run_seconds, "
        "       CASE WHEN s.pipeline_state = 'planned' THEN 0 ELSE 1 END AS claim_order "
        "  FROM project_task s "
        "  JOIN project_task t ON t.id = s.parent_id "
        " WHERE (s.pipeline_state = 'developing' AND s.pipeline_locked_by <> '') "
        "    OR (s.pipeline_state IN ('planned', 'failed_qa') "
        "        AND (s.pipeline_locked_at IS NULL OR s.pipeline_locked_by = '') "
        "        AND s.pipeline_attempt_count < %s) "
        " ORDER BY claim_order, s.parent_id, s.position, s.id"
    )

    return await _rows_fetch(sql, (await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX),))


async def _qa_rows() -> list[dict]:
    """Подзадачи у QA: `qa_pending` — очередь, `testing` — проверка уже идёт."""
    sql = (
        "SELECT s.id AS subtask_id, s.parent_id AS task_id, t.project_id, "
        "       s.title, t.title AS task_title, s.pipeline_state AS state, "
        "       (s.pipeline_locked_by <> '') AS busy, "
        "       TIMESTAMPDIFF(SECOND, s.pipeline_started_at, NOW()) AS run_seconds "
        "  FROM project_task s "
        "  JOIN project_task t ON t.id = s.parent_id "
        " WHERE s.pipeline_state IN ('qa_pending', 'testing') "
        " ORDER BY s.parent_id, s.position, s.id"
    )

    return await _rows_fetch(sql, ())


async def _rows_fetch(sql: str, params: tuple) -> list[dict]:
    async with mysql_get_db_async() as db:
        await db.execute(sql, params)
        rows = await db.fetchall()

    return [dict(row) for row in (rows or [])]


def _slot_get(queues: dict, project_id, role: str) -> dict:
    """Ячейка роли в разрезе проекта — создаётся при первой попавшейся строке."""
    key = int(project_id or TEAM_QUEUE_PROJECT_NONE)

    return queues.setdefault(key, {}).setdefault(
        role, {'waiting_count': 0, 'waiting': [], 'current': None})


def _item_build(row: dict, timeout: int, progress: dict) -> dict:
    """Строка очереди для карточки: у менеджера это задача, у Developer/QA — подзадача.

    `left_seconds` — остаток до таймаута агента, и он есть только у работающей
    строки: у ожидающей отсчёт ещё не начинался. None вместо нуля потому, что
    «времени не осталось» и «время не считается» — разные вещи, и карточка их
    показывает по-разному.

    `percent`, `step_index`, `step_total`, `step_title` — из трейса работающего
    прогона (`team_progress_running`). Их нет ни у ожидающей строки, ни у прогона,
    начатого до появления номера задачи в переменных: карточка тогда просто молчит
    про долю, а не показывает ноль.
    """
    run_seconds = row.get('run_seconds')
    left_seconds = None
    if int(row.get('busy') or 0) and run_seconds is not None:
        left_seconds = max(0, int(timeout) - int(run_seconds))

    subtask_id = int(row['subtask_id']) if row.get('subtask_id') else None
    task_id    = int(row.get('task_id') or 0)
    step = progress.get(('subtask', subtask_id) if subtask_id else ('task', task_id), {})

    return {
        'task_id': task_id,
        'subtask_id': subtask_id,
        'title': str(row.get('title') or '').strip() or f"Задача #{row.get('task_id')}",
        'task_title': str(row.get('task_title') or '').strip(),
        'state': str(row.get('state') or ''),
        'left_seconds': left_seconds,
        'percent': step.get('percent'),
        'step_index': step.get('step_index'),
        'step_total': step.get('step_total'),
        'step_title': step.get('step_title', ''),
    }
