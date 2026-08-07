"""
Запись результатов конвейера в БД: состояния задачи и подзадач, история попыток.

Чтение и захват работы — в `task_claim.py`; здесь только фиксация того,
что уже произошло.
"""
import time

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async


async def task_state_task_get(task_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()
    return dict(row) if row else {}


async def task_state_plan_save(task_id: int, plan_json: str, goals_json: str | None = None) -> None:
    """
    planning | review -> pending_approval. Подзадачи не создаём: сначала утверждение
    человеком.

    `review` — пересмотр плана по кнопке «Обновить план»; на выходе у него ровно то же
    самое, что у первого планирования, поэтому и запись одна. Без него в условии
    результат пересмотра молча не сохранялся бы.

    Цели, наоборот, пишем тем же UPDATE — это чек-лист, а не работа для агентов,
    и утверждать его отдельно нечего. Одним запросом, чтобы не осталось задачи с
    планом, но без целей, если второй запрос не дойдёт.
    """
    sets   = ["pipeline_state = 'pending_approval'", "pipeline_plan = %s", "pipeline_error = ''",
              "pipeline_locked_at = NULL", "pipeline_locked_by = ''"]
    params: list = [plan_json]
    if goals_json is not None:
        sets.append("goals = %s")
        params.append(goals_json)
    params.append(task_id)

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET {', '.join(sets)} "
            "WHERE id = %s AND pipeline_state IN ('planning', 'review')",
            params,
        )
        await db.connection.commit()


async def task_state_subtasks_create(task_id: int, subtasks: list) -> int:
    """Материализовать утверждённый план и снять блокировку с задачи."""
    async with mysql_get_db_async() as db:
        for position, item in enumerate(subtasks):
            await db.execute(
                "INSERT INTO project_task_subtask (task_id, position, title, description) VALUES (%s, %s, %s, %s)",
                (task_id, position, str(item.get('title') or ''), str(item.get('description') or '')),
            )
        await db.execute(
            "UPDATE project_task SET pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            (task_id,),
        )
        await db.connection.commit()
    return len(subtasks)


async def task_state_task_fail(task_id: int, error: str) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task SET pipeline_state = 'failed', pipeline_error = %s, "
            "pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            (error, task_id),
        )
        await db.connection.commit()
    logger_info(f'[task] task#{task_id} -> failed: {error}')


async def task_state_task_finalize() -> tuple[int, str] | None:
    """
    split -> done | failed, когда все подзадачи терминальны.
    Returns: (task_id, final_state) либо None, если финализировать нечего.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT t.id, "
            "       SUM(s.state NOT IN ('done','blocked')) AS pending_cnt, "
            "       SUM(s.state = 'blocked') AS blocked_cnt "
            "  FROM project_task t JOIN project_task_subtask s ON s.task_id = t.id "
            " WHERE t.pipeline_state = 'split' "
            " GROUP BY t.id HAVING pending_cnt = 0 LIMIT 1"
        )
        row = await db.fetchone()
        if not row:
            return None

        final = 'failed' if int(row['blocked_cnt'] or 0) else 'done'
        await db.execute(
            "UPDATE project_task SET pipeline_state = %s WHERE id = %s AND pipeline_state = 'split'",
            (final, row['id']),
        )
        claimed = db.rowcount
        await db.connection.commit()

    if not claimed:
        return None
    logger_info(f'[task] task#{row["id"]} -> {final}')
    return int(row['id']), final


async def task_state_subtask_set(subtask_id: int, state: str, last_error: str | None = None,
                                 attempt_count: int | None = None) -> None:
    sets = ["state = %s", "locked_at = NULL", "locked_by = ''"]
    params: list = [state]
    if last_error is not None:
        sets.append("last_error = %s")
        params.append(last_error)
    if attempt_count is not None:
        sets.append("attempt_count = %s")
        params.append(attempt_count)
    params.append(subtask_id)

    async with mysql_get_db_async() as db:
        await db.execute(f"UPDATE project_task_subtask SET {', '.join(sets)} WHERE id = %s", params)
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
            "INSERT INTO project_task_attempt (subtask_id, attempt_no, role, status, output, error, duration_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (subtask_id, attempt_no, role,
             'ok' if result.get('ok') else 'error',
             str(result.get('output') or ''), str(result.get('error') or ''),
             int((time.monotonic() - started) * 1000)),
        )
        await db.connection.commit()
