"""
Чтение из БД для конвейера планирования: выборка проектов, готовых к фазе,
и заголовки фаз. Только чтение — записью статусов занимается `planning_phase_state`.
"""
from mysql_.mysql_ import mysql_get_db_async

_titles_cache: dict[str, str] | None = None


async def planning_phase_query_pending_projects(
    phase: str,
    requires_phases: list[str],
    project_statuses: list[str] | None = None,
    project_id_filter: int | None = None,
) -> list:
    """
    Возвращает проекты, где:
    - все requires_phases завершены (status=complete или waiting)
    - phase ещё не выполняется и не завершена (либо была failed — тогда берём повторно)

    project_id_filter: если задан — вернуть только этот проект (для runner'а).
    """
    statuses = project_statuses or ['pending', 'processing']
    status_placeholders = ', '.join(['%s'] * len(statuses))
    id_filter_sql = 'AND p.id = %s' if project_id_filter else ''
    id_filter_params = (project_id_filter,) if project_id_filter else ()

    async with mysql_get_db_async() as db:
        if not requires_phases:
            await db.execute(
                f"""
                SELECT p.id FROM project p
                WHERE p.status IN ({status_placeholders})
                  {id_filter_sql}
                  AND NOT EXISTS (
                    SELECT 1 FROM project_planning_phase ph
                    WHERE ph.project_id = p.id AND ph.phase = %s AND ph.status IN ('running','complete')
                  )
                ORDER BY p.id ASC
                LIMIT 10
                """,
                (*statuses, *id_filter_params, phase)
            )
        else:
            placeholders = ', '.join(['%s'] * len(requires_phases))
            req_count = len(requires_phases)
            await db.execute(
                f"""
                SELECT p.id FROM project p
                WHERE p.status IN ({status_placeholders})
                  {id_filter_sql}
                  AND (
                    SELECT COUNT(*) FROM project_planning_phase ph
                    WHERE ph.project_id = p.id
                      AND ph.phase IN ({placeholders})
                      AND ph.status IN ('complete', 'waiting')
                  ) = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM project_planning_phase ph2
                    WHERE ph2.project_id = p.id AND ph2.phase = %s AND ph2.status IN ('running','complete')
                  )
                ORDER BY p.id ASC
                LIMIT 10
                """,
                (*statuses, *id_filter_params, *requires_phases, req_count, phase)
            )
        rows = await db.fetchall()
        return list(rows or [])


async def planning_phase_query_status(project_id: int, phase: str) -> str | None:
    """Текущий статус фазы проекта, либо None если фаза ещё не создавалась."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT status FROM project_planning_phase WHERE project_id = %s AND phase = %s",
            (project_id, phase)
        )
        row = await db.fetchone()
    return (row or {}).get('status')


async def planning_phase_query_title(phase: str) -> str:
    """Человекочитаемое название фазы из `project_planning_phase_source` (кешируется)."""
    titles = await _titles_load()
    return titles.get(phase, phase)


async def _titles_load() -> dict[str, str]:
    global _titles_cache
    if _titles_cache is None:
        async with mysql_get_db_async() as db:
            await db.execute('SELECT phase_key, title FROM project_planning_phase_source')
            rows = await db.fetchall()
        _titles_cache = {r['phase_key']: r['title'] for r in (rows or [])}
    return _titles_cache
