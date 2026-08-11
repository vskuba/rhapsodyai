"""
Сканирование workflow trace на наличие новых ошибок для автосоздания баг-задач.

Публичные функции:
    task_bug_scan_trace — ищет unprocessed run-level и step-level ошибки
"""

from src.project.task.task_bug_create import _task_bug_error_hash


async def task_bug_scan_trace() -> dict | None:
    """
    Ищет первую непроцессированную run-level ошибку из workflow trace.

    Приоритет: run-level > step-level (полный крах важнее ошибки шага).

    Возвращает словарь с полями ошибки или None (не нашёл).

    Поля результата:
        result_type: 'run' | 'step'
        run_id, step_id (только step-level)
        workflow_id, agent_id, workflow_title, agent_name
        error: текст ошибки (унифицировано для run и step)
        duration_ms
        started_at, finished_at (только run-level)
        _error_hash: SHA-256 хеш для дедупликации
    """
    # 1. Run-level ошибка (приоритет: полный крах workflow)
    result = await _scan_run_level()
    if result:
        result['result_type'] = 'run'
        result['_error_hash'] = _task_bug_error_hash(result.get('error', ''))
        return result

    # 2. Step-level ошибка с фильтрацией шума
    result = await _scan_step_level()
    if result:
        result['result_type'] = 'step'
        # Унифицируем поле: step_error -> error
        if 'error' not in result and 'step_error' in result:
            result['error'] = result['step_error']
        result['_error_hash'] = _task_bug_error_hash(result.get('error', ''))
        return result

    return None


async def _scan_run_level() -> dict | None:
    """
    Найти первую run-level ошибку, которая уже завершена (finished_at IS NOT NULL).

    Возвращает словарь с полями ошибки или None.
    """
    from mysql_.mysql_ import mysql_get_db_async

    sql = """
        SELECT r.id AS run_id, r.workflow_id, r.error, r.started_at,
               r.duration_ms, r.agent_id, r.finished_at,
               a.name AS agent_name, w.title AS workflow_title
          FROM agent_workflow_trace r
          JOIN agent_workflow a ON a.id = r.agent_id
          JOIN agent_workflow w ON w.id = r.workflow_id
         WHERE r.status = 'error'
           AND r.error IS NOT NULL
           AND r.error != ''
           AND r.finished_at IS NOT NULL
         ORDER BY r.finished_at DESC
         LIMIT 1
    """

    async with mysql_get_db_async() as db:
        await db.execute(sql)
        row = await db.fetchone()
        if not row:
            return None
        return dict(row)


async def _scan_step_level() -> dict | None:
    """
    Найти первую step-level ошибку с фильтрацией шума.

    Пропускаем:
    - LLM-шаги с timeout/rate limit
    - Ошибки с пустым текстом
    """
    from mysql_.mysql_ import mysql_get_db_async

    sql = """
        SELECT r.id AS run_id, r.workflow_id, r.agent_id,
               s.id AS step_id, s.step_title, s.step_type,
               s.error AS step_error, s.variables_changed,
               r.started_at, r.duration_ms,
               a.name AS agent_name, w.title AS workflow_title
          FROM agent_workflow_trace r
          JOIN agent_workflow a ON a.id = r.agent_id
          JOIN agent_workflow w ON w.id = r.workflow_id
          JOIN agent_workflow_trace_step s ON s.run_id = r.id
                                           AND s.status IN ('error', 'retry')
                                           AND s.error IS NOT NULL
         WHERE r.status = 'error'
           AND r.error IS NOT NULL
           AND r.finished_at IS NOT NULL
           AND s.error != ''
           AND s.error IS NOT NULL
           AND s.step_type != 'llm'
         ORDER BY r.finished_at DESC, s.created_at ASC
         LIMIT 1
    """

    async with mysql_get_db_async() as db:
        await db.execute(sql)
        row = await db.fetchone()
        if not row:
            return None
        return dict(row)
