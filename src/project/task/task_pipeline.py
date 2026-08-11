"""
Машина состояний конвейера задач.

Не крутит бесконечный цикл: `task_pipeline_run()` — это один тик, который находит
первую задачу, требующую внимания, делает по ней ровно одно действие и возвращает
статистику. Запускается по расписанию из Cronicle через `task_orchestrator.py`.

    task.pipeline_state:
        (нет плана) -> planning -> pending_approval -> (человек) -> approved -> split -> done|failed
                       review --^                      (человек: «Обновить план»)

    Вход в конвейер — отсутствие плана, а не явная отправка: задачу без
    `pipeline_plan` Manager подхватывает при любом человеческом `status`.

    Второй вход — `review`: у задачи план есть, но человек отправил его на пересмотр.
    По отсутствию плана такую задачу не отобрать, поэтому у неё своё состояние и свой
    шаг; результат тот же — `pending_approval`.

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
    task_claim_task_review,
    task_claim_task_unplanned,
    task_claim_worker_id,
)
from src.project.task.task_plan import (
    task_plan_goals_merge,
    task_plan_goals_normalize,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_revision import task_revision_add
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

# ── Автосоздание баг-задач из workflow trace ───────────────────────────────────
from src.project.task.task_bug_scan import task_bug_scan_trace
from src.project.task.task_bug_create import (
    task_bug_create as _task_bug_create_impl,
)
from src.project.task.task_bug_dedup import task_bug_dedup_check

BUG_TASK_SCAN_ENABLED = True  # env: BUG_TASK_SCAN_ENABLED=1

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
        # Автосоздание багов из workflow trace — первым: ошибки нужно обрабатывать
        # сразу после завершения run'а, не дожидаясь обработки pipeline задач.
        _step_bug_from_trace,
        # Пересмотр — первым: на другом конце этого шага человек, который нажал
        # «Обновить план» и ждёт результата, а плановое планирование подождёт тик.
        _step_manager_review,
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


async def _step_bug_from_trace(worker: str) -> str | None:
    """
    run/step-level ошибка → баг-задача через Task Orchestrator.

    Flow:
        1. task_bug_scan_trace() — ищет первую unprocessed run или step ошибку
        2. task_bug_dedup_check(hash) — проверяет, не создана ли уже задача
        3. task_bug_create() — INSERT project_task с task_type_id=2 ('bug')

    Возвращает: 'task#{id} bug from trace #{run_id}' или None (не нашёл / пропустим).
    """
    if not BUG_TASK_SCAN_ENABLED:
        return None

    # 1. Сканируем trace на ошибки
    error_data = await task_bug_scan_trace()
    if not error_data:
        return None

    error_hash = error_data.get('_error_hash')
    if not error_hash:
        return None

    # 2. Дедуп
    is_dup = await task_bug_dedup_check('workflow_trace', error_hash)
    if is_dup:
        return None

    # 3. Создаём задачу
    task_id = await _task_bug_create_impl(error_data)
    if task_id is None:
        return None

    trace_id = error_data.get('id', 0)
    return f'task#{task_id} bug from trace #{trace_id}'


async def _step_manager_review(worker: str) -> str | None:
    """
    review -> pending_approval: человек нажал «Обновить план», Manager пересматривает
    существующий план и сверяет его с целями.

    Отдельный шаг, а не ветка `_step_manager_plan`: тот отбирает задачи по отсутствию
    плана, а здесь план как раз есть и именно он идёт на вход менеджеру.
    """
    task = await task_claim_task_review(worker)
    if not task:
        return None
    return await _manager_plan_write(task, revise=True)


async def _step_manager_plan(worker: str) -> str | None:
    """
    Задача без плана -> planning -> pending_approval: Manager читает описание и
    пишет план. Отбор идёт по отсутствию плана, а не по человеческому `status`.

    Если план уже есть, а целей нет — менеджер запускается с revise=True,
    чтобы пересмотреть существующий план и дописать цели, не удаляя subtasks.
    """
    task = await task_claim_task_unplanned(worker)
    if not task:
        return None
    # Если план уже есть (есть subtasks), но goals пуст — пересматриваем,
    # а не пишем заново: менеджер удалит subtasks при write-from-scratch.
    _, existing_subtasks = task_plan_parse(task.get('pipeline_plan') or '')
    revise = len(existing_subtasks) > 0
    return await _manager_plan_write(task, revise=revise)


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


async def _manager_plan_write(task: dict, revise: bool) -> str:
    """
    Общий хвост планирования и пересмотра: сходить к менеджеру и записать результат.

    Задача уже захвачена вызывающим шагом — различаются они только тем, откуда её
    взяли и передаётся ли менеджеру старый план.
    """
    label = 'review' if revise else 'manager'
    try:
        result = await task_agent_manager_plan(task, revise=revise)
    except Exception as e:
        await task_state_task_fail(task['id'], f'Manager: {e}')
        return f"task#{task['id']} {label} -> failed"

    subtasks = result.get('subtasks') or []
    if not subtasks:
        await task_state_task_fail(task['id'], 'Manager не вернул ни одной подзадачи')
        return f"task#{task['id']} {label} -> failed (пустой план)"

    # Цели пишем сразу в задачу, не дожидаясь утверждения плана: подзадачи без
    # утверждения ломали бы конвейер, а цели — просто чек-лист в колонке «Цели»,
    # и человеку они нужны как раз в момент разбора плана.
    goals     = result.get('goals') or []
    plan_text = str(result.get('plan_text') or '')
    goals_json = task_plan_goals_merge(task.get('goals'), goals)
    await task_state_plan_save(
        task['id'],
        task_plan_serialize(plan_text, subtasks, goals),
        goals_json=goals_json,
    )
    # Ревизию пишем здесь, а не внутри `task_state_plan_save`: там один UPDATE без
    # побочных таблиц, и спрятанная в нём запись истории читалась бы как сюрприз.
    # В ревизию идут те же слитые цели, что легли в задачу, — иначе восстановление
    # вернуло бы только предложенное агентом, потеряв цели человека.
    await task_revision_add(task['id'], plan_text, task_plan_goals_normalize(goals_json),
                            subtasks, author_kind='manager')

    logger_info(
        f'[task] task#{task["id"]} -> pending_approval '
        f'({len(subtasks)} подзадач, {len(goals)} целей)'
    )
    return f"task#{task['id']} {label} -> pending_approval"
