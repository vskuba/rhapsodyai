"""Доля выполненного у работающей роли: сколько шагов прогона уже пройдено.

Работу роли ведёт workflow, и единственный след того, где она сейчас, — трейс
(`agent_workflow_trace` и его шаги). Прогон привязывается к строке очереди не по
времени захвата, а по номеру задачи в стартовых переменных: у одной роли столько
одновременных прогонов, сколько проектов, и «ближайший по времени» ошибался бы
ровно тогда, когда работы много.

**Знаменатель — не число шагов в workflow.** В WF55 их 53, но полтора десятка —
ветки ошибок и тупики («Менеджер недоступен», «Цели недоступны»), в удачном
прогоне не исполняемые ни разу; зато шаги-циклы (судья, счётчик итераций)
исполняются по нескольку раз. Считать от определения значило бы показывать 26 %
в момент, когда менеджер уже вернул план. Поэтому за 100 % берётся медиана числа
исполненных шагов по прошлым **удачным** прогонам того же workflow — оценка по
факту, а не по схеме. Истории нет — только тогда берём число шагов определения.

Отсюда и потолок: оценка по медиане легко перешагивает свой знаменатель (цикл
судьи развернулся лишний раз), а работающий прогон не бывает завершён — процент
упирается в `TEAM_PROGRESS_MAX_PERCENT` и ждёт настоящего конца.
"""
from mysql_.mysql_ import mysql_get_db_async

# Сколько прошлых удачных прогонов берём за образец длины.
TEAM_PROGRESS_SAMPLE_LIMIT = 10

# Работающий прогон не показывает 100 %: конец отмечает завершение, а не оценка.
TEAM_PROGRESS_MAX_PERCENT = 99


async def team_progress_running() -> dict[tuple[str, int], dict]:
    """Прогресс всех работающих прогонов.

    Returns:
        {('task'|'subtask', id): {'percent': int, 'step_index': int,
                                  'step_total': int, 'step_title': str}}
        Ключ — то, чем прогон занят: планирование адресуется задачей, круг
        Developer/QA — подзадачей. Прогонов без номера в переменных (запуск
        не из конвейера) в ответе нет.
    """
    runs = await _runs_running()
    if not runs:
        return {}

    last_steps = await _steps_last([run['id'] for run in runs])
    totals     = await _totals_by_workflow({int(run['workflow_id'] or 0) for run in runs})

    progress: dict[tuple[str, int], dict] = {}
    for run in runs:
        step = last_steps.get(int(run['id']))
        if not step:
            # Прогон начался, первый шаг ещё не закрыт — считать нечего.
            continue
        key = _key_build(run)
        if key is None:
            continue
        total = max(1, int(totals.get(int(run['workflow_id'] or 0)) or 1))
        # `exec_index` считает с единицы, так что это уже «сколько шагов пройдено».
        index = int(step.get('exec_index') or 0)
        progress[key] = {
            'percent':    min(TEAM_PROGRESS_MAX_PERCENT, round(100 * index / total)),
            'step_index': index,
            'step_total': total,
            'step_title': str(step.get('step_title') or ''),
        }

    return progress


async def _runs_running() -> list[dict]:
    """Работающие прогоны с номерами задачи и подзадачи из стартовых переменных."""
    sql = (
        "SELECT id, workflow_id, "
        "       JSON_UNQUOTE(JSON_EXTRACT(variables_start, '$.task_id')) AS task_id, "
        "       JSON_UNQUOTE(JSON_EXTRACT(variables_start, '$.subtask_id')) AS subtask_id "
        "  FROM agent_workflow_trace "
        " WHERE status = 'running' AND JSON_VALID(variables_start) "
        " ORDER BY id"
    )

    return await _rows_fetch(sql, ())


async def _steps_last(run_ids: list[int]) -> dict[int, dict]:
    """Последний записанный шаг каждого прогона.

    Порядок — по `id` записи, а не по `exec_index`: индекс на циклах повторяется,
    и «последний по индексу» вернул бы шаг из предыдущего витка.
    """
    marks = ', '.join(['%s'] * len(run_ids))
    sql = (
        "SELECT s.run_id, s.exec_index, s.step_title "
        "  FROM agent_workflow_trace_step s "
        "  JOIN (SELECT run_id, MAX(id) AS id FROM agent_workflow_trace_step "
        f"         WHERE run_id IN ({marks}) GROUP BY run_id) last ON last.id = s.id"
    )
    rows = await _rows_fetch(sql, tuple(run_ids))

    return {int(row['run_id']): row for row in rows}


async def _totals_by_workflow(workflow_ids: set[int]) -> dict[int, int]:
    """Сколько шагов считать за 100 % — по медиане прошлых удачных прогонов."""
    ids = [wid for wid in workflow_ids if wid]
    if not ids:
        return {}

    marks = ', '.join(['%s'] * len(ids))
    sql = (
        "SELECT r.workflow_id, r.id, COUNT(s.id) AS execs "
        "  FROM agent_workflow_trace r "
        "  JOIN agent_workflow_trace_step s ON s.run_id = r.id "
        f" WHERE r.workflow_id IN ({marks}) AND r.status = 'success' "
        " GROUP BY r.workflow_id, r.id "
        " ORDER BY r.workflow_id, r.id DESC"
    )
    samples: dict[int, list[int]] = {}
    for row in await _rows_fetch(sql, tuple(ids)):
        bucket = samples.setdefault(int(row['workflow_id']), [])
        if len(bucket) < TEAM_PROGRESS_SAMPLE_LIMIT:
            bucket.append(int(row['execs'] or 0))

    totals = {wid: _median(values) for wid, values in samples.items() if _median(values)}
    missing = [wid for wid in ids if wid not in totals]

    return {**(await _totals_defined(missing)), **totals}


async def _totals_defined(workflow_ids: list[int]) -> dict[int, int]:
    """Запасной знаменатель — число шагов в определении workflow."""
    if not workflow_ids:
        return {}

    marks = ', '.join(['%s'] * len(workflow_ids))
    sql = (f"SELECT workflow_id, COUNT(*) AS steps FROM agent_workflow_step "
           f" WHERE workflow_id IN ({marks}) GROUP BY workflow_id")

    return {int(row['workflow_id']): int(row['steps'] or 0)
            for row in await _rows_fetch(sql, tuple(workflow_ids))}


async def _rows_fetch(sql: str, params: tuple) -> list[dict]:
    async with mysql_get_db_async() as db:
        await db.execute(sql, params)
        rows = await db.fetchall()

    return [dict(row) for row in (rows or [])]


def _key_build(run: dict) -> tuple[str, int] | None:
    """Чем занят прогон: подзадача важнее задачи.

    У Developer/QA в переменных лежат обе — задача нужна промпту для контекста,
    работой же считается подзадача, и очередь показывает именно её.
    """
    for kind in ('subtask', 'task'):
        value = str(run.get(f'{kind}_id') or '').strip()
        if value.isdigit() and int(value):
            return kind, int(value)

    return None


def _median(values: list[int]) -> int:
    """Медиана, а не среднее: один сорвавшийся долгий прогон не сдвигает оценку."""
    ordered = sorted(v for v in values if v > 0)
    if not ordered:
        return 0
    middle = len(ordered) // 2

    return (ordered[middle] if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) // 2)
