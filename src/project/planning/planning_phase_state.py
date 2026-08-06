"""
Запись состояний фаз планирования в БД: running / complete / waiting / failed,
подсчёт токенов, закрытие родительской фазы, сброс зависших прогонов.
"""
from datetime import datetime

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_set
from src.project.planning.planning_phase_query import planning_phase_query_title

# После этого простоя фаза в статусе running считается брошенной (рестарт uvicorn).
STUCK_RUNNING_SEC = 3600


async def planning_phase_state_running(project_id: int, phase: str, parent_phase: str | None = None) -> None:
    title = await planning_phase_query_title(phase)
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, parent_phase, title, status, started_at)
            VALUES (%s, %s, %s, %s, 'running', NOW())
            ON DUPLICATE KEY UPDATE parent_phase = %s, title = %s, status = 'running', started_at = NOW(), error = ''
            """,
            (project_id, phase, parent_phase, title, parent_phase, title)
        )
        await db.execute(
            "UPDATE project SET status = 'processing', phase_current = %s WHERE id = %s",
            (phase, project_id)
        )
        await db.connection.commit()


async def planning_phase_state_complete(
    project_id: int,
    phase: str,
    restore_project_status: str | None = None,
    session_uuid: str | None = None,
) -> None:
    await _phase_finish(project_id, phase, 'complete', restore_project_status, session_uuid)


async def planning_phase_state_waiting(
    project_id: int,
    phase: str,
    restore_project_status: str | None = None,
    session_uuid: str | None = None,
) -> None:
    """Фаза выполнила свой workflow, но ожидает завершения дочерних фаз."""
    await _phase_finish(project_id, phase, 'waiting', restore_project_status, session_uuid)


async def planning_phase_state_failed(project_id: int, phase: str, error: str) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_planning_phase SET status = 'failed', error = %s WHERE project_id = %s AND phase = %s",
            (error[:500], project_id, phase)
        )
        await db.execute("UPDATE project SET status = 'error' WHERE id = %s", (project_id,))
        await db.connection.commit()


async def planning_phase_state_parent_complete(project_id: int, parent_phase: str) -> None:
    """Проверяет все ли дочерние фазы завершены и если да — ставит родителю 'complete'."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(status = 'complete') AS done,
                   SUM(status = 'failed') AS failed
            FROM project_planning_phase
            WHERE project_id = %s AND parent_phase = %s
            """,
            (project_id, parent_phase)
        )
        row = await db.fetchone()

    if not row or not row['total']:
        return

    total = int(row['total'])
    done = int(row['done'] or 0)
    failed = int(row['failed'] or 0)

    if done == total or (total > 0 and done + failed == total):
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                UPDATE project_planning_phase SET status = 'complete', completed_at = NOW()
                WHERE project_id = %s AND phase = %s AND status = 'waiting'
                """,
                (project_id, parent_phase)
            )
            await db.connection.commit()
        if failed:
            logger_info(f'planning [{parent_phase}]: дочерние фазы завершены (ошибок: {failed}/{total}) → complete')
        else:
            logger_info(f'planning [{parent_phase}]: все дочерние фазы завершены → complete')


async def planning_phase_state_cronicle_touch(phase: str) -> None:
    """Сохраняет время последнего запуска Cronicle для данной фазы в setting."""
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    await setting_set(f'planning_cronicle_{phase}', now, dynamic=1)


async def planning_phase_state_stuck_reset(phase: str) -> None:
    """Помечает failed фазы, застрявшие в running дольше STUCK_RUNNING_SEC (рестарт uvicorn)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            UPDATE project_planning_phase
               SET status = 'failed',
                   error  = 'Workflow прерван: uvicorn перезапустился во время выполнения'
             WHERE phase = %s
               AND status = 'running'
               AND started_at < NOW() - INTERVAL %s SECOND
            """,
            (phase, STUCK_RUNNING_SEC)
        )
        if db.rowcount:
            logger_info(f'planning [{phase}]: сброшено {db.rowcount} застрявших running-фаз')
        await db.connection.commit()


async def _phase_finish(
    project_id: int,
    phase: str,
    status: str,
    restore_project_status: str | None,
    session_uuid: str | None,
) -> None:
    """Общая часть complete и waiting: подсчёт токенов + upsert строки фазы."""
    title = await planning_phase_query_title(phase)
    async with mysql_get_db_async() as db:
        tokens_input, tokens_output = await _tokens_sum(db, session_uuid)
        tokens_used = tokens_input + tokens_output

        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, title, status, completed_at,
                                                tokens_used, tokens_input, tokens_output)
            VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
            ON DUPLICATE KEY UPDATE title = %s, status = %s, completed_at = NOW(),
                tokens_used = %s, tokens_input = %s, tokens_output = %s
            """,
            (project_id, phase, title, status, tokens_used, tokens_input, tokens_output,
             title, status, tokens_used, tokens_input, tokens_output)
        )
        if restore_project_status:
            await db.execute(
                "UPDATE project SET status = %s WHERE id = %s",
                (restore_project_status, project_id)
            )
        await db.connection.commit()


async def _tokens_sum(db, session_uuid: str | None) -> tuple[int, int]:
    """Суммарные токены сессии по trace-шагам. (0, 0), если сессия не задана."""
    if not session_uuid:
        return 0, 0
    await db.execute(
        """
        SELECT COALESCE(SUM(COALESCE(s.tokens_input, 0)), 0)  AS tin,
               COALESCE(SUM(COALESCE(s.tokens_output, 0)), 0) AS tout
        FROM agent_workflow_trace r
        JOIN agent_workflow_trace_step s ON s.run_id = r.id
        WHERE r.session_uuid = %s
        """,
        (session_uuid,)
    )
    row = await db.fetchone()
    if not row:
        return 0, 0
    return int(row['tin']), int(row['tout'])
