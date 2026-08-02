import json
import traceback

from config.config import config_get
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Максимальная длина одного сохраняемого значения — защита журнала от распухания
TRACE_VALUE_MAX_LEN = 20_000


def trace_enabled() -> bool:
    return str(config_get('WORKFLOW_TRACE_ENABLED', '1')).lower() not in ('0', 'false', 'off')


async def trace_run_start(run_uuid: str, workflow_id, agent_id, user_id,
                          session_uuid: str, request_uuid: str,
                          prompt_user, variables: dict,
                          parent_run_id: int | None = None,
                          parent_step_id: int | None = None,
                          depth: int = 0) -> int | None:
    """Создает запись запуска workflow. Возвращает run_id либо None (трейс выключен/сбой) —
    сбой записи журнала никогда не должен ронять выполнение workflow."""
    if not trace_enabled():
        return None
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                INSERT INTO agent_workflow_trace
                    (run_uuid, parent_run_id, parent_step_id, depth, workflow_id, agent_id,
                     user_id, session_uuid, request_uuid, prompt_user, variables_start)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_uuid, parent_run_id, parent_step_id, depth, workflow_id, agent_id,
                 user_id, session_uuid, request_uuid, _truncate(prompt_user), _json_dump(variables))
            )
            return db.lastrowid
    except Exception as e:
        logger_info(f"⚠️ trace_run_start не записан: {e}\n{traceback.format_exc()}")
        return None


async def trace_run_finish(run_id: int | None, status: str,
                           result=None, error: str | None = None,
                           duration_ms: int | None = None) -> None:
    """Закрывает запись запуска: статус, результат/ошибка, длительность."""
    if run_id is None:
        return
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                UPDATE agent_workflow_trace
                SET status = %s, result = %s, error = %s,
                    finished_at = NOW(3), duration_ms = %s
                WHERE id = %s
                """,
                (status, _truncate(result), _truncate(error), duration_ms, run_id)
            )
    except Exception as e:
        logger_info(f"⚠️ trace_run_finish не записан: {e}")


async def trace_step(run_id: int | None, exec_index: int, step: dict,
                     metadata_rendered=None, variables_changed: dict | None = None,
                     output=None, transition: dict | None = None,
                     status: str = 'success', error: str | None = None,
                     duration_ms: int | None = None,
                     llm_id: int | None = None) -> None:
    """Записывает выполненный шаг: вход (metadata после рендера), выход (изменённые
    переменные), сырой output, сработавший переход, статус и длительность.
    llm_id — модель использованная в LLM-шаге (None для tool/text/variable шагов)."""
    if run_id is None:
        return
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                INSERT INTO agent_workflow_trace_step
                    (run_id, exec_index, step_id, step_title, step_type, llm_id,
                     metadata_rendered, variables_changed, output, transition, status, error, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, exec_index, step.get('id'),
                 str(step.get('title', ''))[:100], str(step.get('step_type_name', ''))[:50],
                 llm_id,
                 _json_dump(metadata_rendered), _json_dump(variables_changed),
                 _truncate(output), _json_dump(transition),
                 status, _truncate(error), duration_ms)
            )
    except Exception as e:
        logger_info(f"⚠️ trace_step не записан: {e}")


async def workflow_trace_runs_stale_close() -> None:
    """На старте сервера закрывает зависшие трейсы (status='running') как 'stopped'."""
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE agent_workflow_trace SET status = 'stopped', error = 'Server restart' "
                "WHERE status = 'running'"
            )
            await db.connection.commit()
    except Exception as e:
        logger_info(f"⚠️ workflow_trace_runs_stale_close: {e}")


def variables_diff(before: dict, after: dict) -> dict:
    """Изменённые и новые переменные шага (для поля variables_changed)."""
    return {
        key: value for key, value in after.items()
        if key not in before or before[key] != value
    }


def _truncate(text: str | None) -> str | None:
    if text is None:
        return None
    text = str(text)
    if len(text) > TRACE_VALUE_MAX_LEN:
        return text[:TRACE_VALUE_MAX_LEN] + '...[truncated]'
    return text


def _json_dump(data) -> str | None:
    if data is None:
        return None
    try:
        return _truncate(json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        return _truncate(str(data))
