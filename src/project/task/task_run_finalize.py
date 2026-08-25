"""
run_finalize: finalize — финализация всех подзадач.

processing -> done | failed, когда все подзадачи в терминальном состоянии.

Соседние модули: `task_pipeline` — триггер и карта, `task_run_developer` —
разработка, `task_run_qa` — проверка, `task_run_bugfix` — исправление багов,
`task_run_manager` — шаги менеджера.
"""
from logging_.logging_ import logger_info
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_state import (
    task_state_goals_inherit,
    task_state_task_finalize,
)


async def _run_finalize(action: dict) -> str | None:
    """processing -> done | failed, когда все подзадачи в терминальном состоянии."""
    finalized = await task_state_task_finalize()
    if not finalized:
        return None
    task_id, final = finalized
    summary = await task_report_subtasks_summary(task_id)
    if final == 'done':
        # Цели родителя проверяет не он сам, а его подзадачи: сюда переносим только
        # те отметки, которые QA уже подтвердил ниже по дереву.
        await task_state_goals_inherit(task_id)
        await task_report_write(task_id, f'Задача выполнена успешно: все подзадачи готовы ({summary})')
    else:
        # Не через `task_state_task_fail`: та ставит состояние сама, а его уже
        # выставила финализация — второй UPDATE только затёр бы блокировки.
        await task_report_write(
            task_id, f'Задача завершена со сбоем: часть подзадач заблокирована ({summary})', ok=False)
    return f"task#{task_id} -> {final}"
