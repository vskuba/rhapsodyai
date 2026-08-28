"""
Создание баг-задачи из workflow trace ошибки.

Публичные функции:
    task_bug_create — создаёт task_type_id='bug' задачу с trace_meta
"""
import hashlib
import json

from src.project.task.task_bug_format import (
    task_bug_format_run_description,
    task_bug_format_run_title,
    task_bug_format_step_description,
    task_bug_format_step_title,
)
from src.project.task.task_bug_project_map import task_bug_project_map_for_workflow


async def task_bug_create(error_data: dict) -> int | None:
    """
    Создаёт баг-задачу из ошибки workflow trace.

    Args:
        error_data: словарь, возвращаемый task_bug_scan_trace():
            result_type, run_id, workflow_id, error, workflow_title,
            agent_name, duration_ms, started_at + опционально step_id,
            step_title, step_type, variables_changed.

    Returns:
        ID созданной задачи или None (при ошибке).
    """
    result_type = error_data.get('result_type', 'run')
    workflow_title = error_data.get('workflow_title') or ''
    error = error_data.get('error', '')
    workflow_id = int(error_data.get('workflow_id', 0))

    # 1. Формируем title / description
    if result_type == 'run':
        title = task_bug_format_run_title(
            workflow_title=workflow_title,
            error=error,
            duration_ms=error_data.get('duration_ms'),
        )
        description = task_bug_format_run_description(
            workflow_title=workflow_title,
            agent_name=error_data.get('agent_name'),
            error=error,
            duration_ms=error_data.get('duration_ms'),
            started_at=str(error_data.get('started_at') or ''),
            finished_at=str(error_data.get('finished_at') or ''),
        )
        trace_meta = json.dumps(_build_run_meta(error_data), ensure_ascii=False)
    else:
        title = task_bug_format_step_title(
            workflow_title=workflow_title,
            step_title=error_data.get('step_title') or '',
            step_type=error_data.get('step_type') or '',
            error=error,
        )
        description = task_bug_format_step_description(
            workflow_title=workflow_title,
            step_title=error_data.get('step_title') or '',
            step_type=error_data.get('step_type') or '',
            step_id=int(error_data.get('step_id', 0)),
            error=error,
            variables_changed=error_data.get('variables_changed'),
        )
        trace_meta = json.dumps(_build_step_meta(error_data), ensure_ascii=False)

    # 2. Определяем project_id. Ноль из конфигурации значит «без проекта» — в колонку
    # он идёт как NULL, иначе строка ссылалась бы на несуществующий проект №0.
    project_id = task_bug_project_map_for_workflow(workflow_id) or None

    # 3. Вставляем задачу
    return await _task_bug_insert(
        project_id=project_id,
        title=title,
        description=description,
        trace_meta=trace_meta,
    )


def _build_run_meta(error_data: dict) -> dict:
    """Формирует trace_meta dict для run-level ошибки."""
    error = error_data.get('error', '')
    return {
        'domain': 'workflow_trace',
        'trace_run_id': int(error_data.get('run_id', 0)),
        'trace_step_id': None,
        'workflow_id': int(error_data.get('workflow_id', 0)),
        'workflow_title': error_data.get('workflow_title') or '',
        'agent_name': error_data.get('agent_name') or '',
        'error_hash': _task_bug_error_hash(error),
        'error_summary': error.strip().split('\n')[0][:200] if error else '',
    }


def _build_step_meta(error_data: dict) -> dict:
    """Формирует trace_meta dict для step-level ошибки."""
    error = error_data.get('error', '')
    return {
        'domain': 'workflow_trace',
        'trace_run_id': int(error_data.get('run_id', 0)),
        'trace_step_id': int(error_data.get('step_id', 0)),
        'workflow_id': int(error_data.get('workflow_id', 0)),
        'workflow_title': error_data.get('workflow_title') or '',
        'agent_name': error_data.get('agent_name') or '',
        'step_title': error_data.get('step_title') or '',
        'step_type': error_data.get('step_type') or '',
        'error_hash': _task_bug_error_hash(error),
        'error_summary': error.strip().split('\n')[0][:200] if error else '',
    }


def _task_bug_error_hash(error: str) -> str:
    """
    Детерминированный SHA-256 хеш ошибки для дедупа.

    strip + lower убирают случайные различия в регистре и пробелах.
    Если ошибка меняется — hash изменится, и задача создастся заново —
    это правильное поведение: изменившаяся ошибка = возможный новый паттерн.
    """
    canonical = f"workflow_trace:{error.strip().lower()}"
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


async def _task_bug_insert(project_id: int | None, title: str, description: str,
                           trace_meta: str) -> int | None:
    """
    Вставляет новую баг-задачу в project_task.

    Args:
        project_id: ID проекта или None — задача заводится без проекта.
        title: Заголовок задачи.
        description: Описание задачи.
        trace_meta: JSON-строка trace_meta.

    Returns:
        ID созданной задачи или None.
    """
    from logging_.logging_ import logger_info
    from mysql_.mysql_ import mysql_get_db_async

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                INSERT INTO project_task
                    (project_id, parent_id, title, description, goals, status,
                     report, position, task_type_id, trace_meta,
                     pipeline_plan, pipeline_error, pipeline_locked_by)
                VALUES (%s, NULL, %s, %s, '', 'pending',
                        '', 0, 2, %s, '', '', '')
                """,
                (project_id, title, description, trace_meta),
            )
            task_id = db.lastrowid
            logger_info(f'[bug_task] created task#{task_id} from trace error (project {project_id})')
            return task_id
    except Exception as e:
        logger_info(f'[bug_task] INSERT failed: {e}')
        return None
