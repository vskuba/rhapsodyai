"""
run_plan_split: plan_split — раскладываем утверждённый план в подзадачи.

Соседние модули: `task_pipeline` — триггер и карта, `task_run_developer` —
разработка, `task_run_qa` — проверка, `task_run_bugfix` — исправление багов,
`task_run_finalize` — финализация, `task_run_manager` — шаги менеджера,
`task_retry` — повторы сорвавшихся прогонов + общие хвосты: `_subtask_dir`,
`_log_run`, `_subtask_report`, `_task_to_testing`, `_subtask_branch_save`.
"""
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE
from src.project.task.task_plan import task_plan_parse
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_retry import task_retry_clear
from src.project.task.task_state import (
    task_state_task_fail,
    task_state_subtasks_create,
    task_state_task_get,
)
from src.project.task.task_pipeline_retry import _task_plural_sub


async def _run_plan_split(action: dict) -> str | None:
    """approved -> processing: раскладываем утверждённый план в подзадачи — детей задачи."""
    task = await task_state_task_get(int(action.get('task_id') or 0))
    if not task:
        return None

    _, subtasks = task_plan_parse(task.get('pipeline_plan') or '')
    if not subtasks:
        await task_state_task_fail(task['id'], 'В утверждённом плане нет подзадач')
        return f"task#{task['id']} processing -> failed"

    created = await task_state_subtasks_create(task['id'], subtasks)
    await task_report_write(
        task['id'], f'План утверждён и разложен на {created} {_task_plural_sub(created)} — выполнение началось')
    from logging_.logging_ import logger_info
    logger_info(f'[task] task#{task["id"]} -> processing ({created} подзадач)')
    return f"task#{task['id']} processing -> {created} подзадач"
