"""
Машина состояний конвейера задач.

Не крутит бесконечный цикл: `task_pipeline_run()` — это один тик, который находит
первую задачу, требующую внимания, делает по ней ровно одно действие и возвращает
статистику. Запускается по расписанию из Cronicle через `task_orchestrator.py`.

    task.pipeline_state:
        (нет плана) -> planning -> pending_approval -> (человек) -> approved -> split -> done|failed

    Вход в конвейер — отсутствие плана, а не явная отправка: задачу без
    `pipeline_plan` Manager подхватывает при любом человеческом `status`.

    project_task_subtask.state:
        planned -> developing -> qa_pending -> done
                        ^              '-> failed_qa -> повтор, пока attempt_count < MAX_ATTEMPTS
                        '----------------'                    '-> blocked (лимит исчерпан)

Соседние модули: `task_claim` — захват и блокировки, `task_state` — запись
результатов, `task_agent_manager` — Manager на LLM, `task_agent` — заглушки
Developer и QA, `task_plan` — формат плана.
"""
import time

from logging_.logging_ import logger_info
from src.project.task.task_agent import task_agent_developer_run, task_agent_qa_run
from src.project.task.task_agent_manager import task_agent_manager_plan
from src.project.task.task_claim import (
    task_claim_locks_reclaim,
    task_claim_subtask,
    task_claim_subtask_developable,
    task_claim_task,
    task_claim_task_unplanned,
    task_claim_worker_id,
)
from src.project.task.task_plan import task_plan_goals_merge, task_plan_parse, task_plan_serialize
from src.project.task.task_state import (
    task_state_attempt_log,
    task_state_plan_save,
    task_state_subtask_fail,
    task_state_subtask_set,
    task_state_subtasks_create,
    task_state_task_fail,
    task_state_task_finalize,
    task_state_task_get,
)

MAX_ATTEMPTS = 3  # сколько кругов Developer/QA допустимо по одной подзадаче


async def task_pipeline_run(max_actions: int = 1) -> dict:
    """
    Один тик конвейера.

    Returns:
        actions: сколько действий выполнено.
        reclaimed: сколько протухших блокировок сброшено.
        steps: список выполненных шагов для лога.
    """
    worker = task_claim_worker_id()
    stats = {'actions': 0, 'reclaimed': await task_claim_locks_reclaim(), 'steps': []}

    for _ in range(max(1, int(max_actions))):
        step = await _action_next(worker)
        if not step:
            break
        stats['actions'] += 1
        stats['steps'].append(step)

    return stats


# ─── Шаги конвейера ────────────────────────────────────────────────────────────

async def _action_next(worker: str) -> str | None:
    """Выполнить первое подошедшее действие. None — работы нет."""
    for handler in (
        _step_manager_plan,
        _step_plan_split,
        _step_developer_run,
        _step_qa_run,
        _step_task_finalize,
    ):
        step = await handler(worker)
        if step:
            return step
    return None


async def _step_manager_plan(worker: str) -> str | None:
    """
    Задача без плана -> planning -> pending_approval: Manager читает описание и
    пишет план. Отбор идёт по отсутствию плана, а не по человеческому `status`.
    """
    task = await task_claim_task_unplanned(worker)
    if not task:
        return None

    try:
        result = await task_agent_manager_plan(task)
    except Exception as e:
        await task_state_task_fail(task['id'], f'Manager: {e}')
        return f"task#{task['id']} manager -> failed"

    subtasks = result.get('subtasks') or []
    if not subtasks:
        await task_state_task_fail(task['id'], 'Manager не вернул ни одной подзадачи')
        return f"task#{task['id']} manager -> failed (пустой план)"

    # Цели пишем сразу в задачу, не дожидаясь утверждения плана: подзадачи без
    # утверждения ломали бы конвейер, а цели — просто чек-лист в колонке «Цели»,
    # и человеку они нужны как раз в момент разбора плана.
    goals = result.get('goals') or []
    await task_state_plan_save(
        task['id'],
        task_plan_serialize(str(result.get('plan_text') or ''), subtasks, goals),
        goals_json=task_plan_goals_merge(task.get('goals'), goals),
    )
    logger_info(
        f'[task] task#{task["id"]} -> pending_approval '
        f'({len(subtasks)} подзадач, {len(goals)} целей)'
    )
    return f"task#{task['id']} manager -> pending_approval"


async def _step_plan_split(worker: str) -> str | None:
    """approved -> split: раскладываем утверждённый план в строки project_task_subtask."""
    task = await task_claim_task('approved', 'split', worker)
    if not task:
        return None

    _, subtasks = task_plan_parse(task.get('pipeline_plan') or '')
    if not subtasks:
        await task_state_task_fail(task['id'], 'В утверждённом плане нет подзадач')
        return f"task#{task['id']} split -> failed"

    created = await task_state_subtasks_create(task['id'], subtasks)
    logger_info(f'[task] task#{task["id"]} -> split ({created} подзадач)')
    return f"task#{task['id']} split -> {created} подзадач"


async def _step_developer_run(worker: str) -> str | None:
    """planned | failed_qa -> developing -> qa_pending."""
    subtask = await task_claim_subtask_developable(worker, MAX_ATTEMPTS)
    if not subtask:
        return None

    task = await task_state_task_get(subtask['task_id'])
    attempt_no = int(subtask['attempt_count']) + 1
    started = time.monotonic()

    try:
        result = await task_agent_developer_run(task, subtask, str(subtask.get('last_error') or ''))
    except Exception as e:
        result = {'ok': False, 'output': '', 'error': f'Developer: {e}'}

    await task_state_attempt_log(subtask['id'], attempt_no, 'developer', result, started)

    if result.get('ok'):
        await task_state_subtask_set(subtask['id'], 'qa_pending', last_error='')
        return f"subtask#{subtask['id']} developer -> qa_pending"

    # Развалился сам разработчик — попытка засчитана, круг закрываем как провал.
    state = await task_state_subtask_fail(
        subtask['id'], attempt_no, str(result.get('error') or 'ошибка разработчика'), MAX_ATTEMPTS)
    return f"subtask#{subtask['id']} developer -> {state}"


async def _step_qa_run(worker: str) -> str | None:
    """qa_pending -> done | failed_qa | blocked."""
    subtask = await task_claim_subtask('qa_pending', 'qa_pending', worker)
    if not subtask:
        return None

    task = await task_state_task_get(subtask['task_id'])
    attempt_no = int(subtask['attempt_count']) + 1
    started = time.monotonic()

    try:
        result = await task_agent_qa_run(task, subtask)
    except Exception as e:
        result = {'ok': False, 'output': '', 'error': f'QA: {e}'}

    await task_state_attempt_log(subtask['id'], attempt_no, 'qa', result, started)

    if result.get('ok'):
        await task_state_subtask_set(subtask['id'], 'done', last_error='', attempt_count=attempt_no)
        return f"subtask#{subtask['id']} qa -> done"

    state = await task_state_subtask_fail(
        subtask['id'], attempt_no, str(result.get('error') or 'проверки не прошли'), MAX_ATTEMPTS)
    return f"subtask#{subtask['id']} qa -> {state}"


async def _step_task_finalize(worker: str) -> str | None:
    """split -> done | failed, когда все подзадачи в терминальном состоянии."""
    finalized = await task_state_task_finalize()
    if not finalized:
        return None
    task_id, final = finalized
    return f"task#{task_id} -> {final}"
