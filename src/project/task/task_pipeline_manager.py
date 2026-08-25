"""
Шаги конвейера, где работает Manager: скан багов, составление плана, пересмотр.

Оба планировочных шага (`_run_manager_plan`, `_run_manager_review`) различаются
только тем, откуда задача взята, и сходятся в общем хвосте
`_manager_plan_write`: сходить к менеджеру и записать результат. `_run_bug_scan` —
подметальщик: сам ищет ошибку в workflow trace и превращает её в баг-задачу,
без захвата строки.

Соседние модули: `task_pipeline_run` — исполнители Developer/QA/Багфиксера и
карта `_RUNNERS`, `task_pipeline_retry` — повторы сорвавшихся прогонов,
`task_bug_*` — скан и создание багов, `task_agent_manager` — роль менеджера.
"""
from logging_.logging_ import logger_info
from src.project.task.task_agent_manager import task_agent_manager_plan
from src.project.task.task_plan import (
    task_plan_goals_merge,
    task_plan_goals_normalize,
    task_plan_serialize,
)
from src.project.task.task_report import task_report_write
from src.project.task.task_retry import task_retry_clear
from src.project.task.task_role import TASK_ROLE_DEFAULT, task_role_project_work_dir
from src.project.task.task_revision import task_revision_add
from src.project.task.task_state import (
    task_state_plan_save,
    task_state_plan_to_development,
    task_state_task_get,
)
from src.project.task.task_pipeline_retry import (
    _retry_task,
    _role_title,
    _subtask_dir,
    _task_plural_goal,
    _task_plural_sub,
)

# ── Автосоздание баг-задач из workflow trace ───────────────────────────────────
from src.project.task.task_bug_scan import task_bug_scan_trace
from src.project.task.task_bug_create import (
    task_bug_create as _task_bug_create_impl,
)
from src.project.task.task_bug_dedup import task_bug_dedup_check


async def _run_bug_scan(action: dict) -> str | None:
    """
    run/step-level ошибка → баг-задача через Task Orchestrator.

    Flow:
        1. task_bug_scan_trace() — ищет первую unprocessed run или step ошибку
        2. task_bug_dedup_check(hash) — проверяет, не создана ли уже задача
        3. task_bug_create() — INSERT project_task с task_type_id=2 ('bug')

    Возвращает: 'task#{id} bug from trace #{run_id}' или None (не нашёл / пропустим).
    """
    error_data = await task_bug_scan_trace()
    if not error_data:
        return None

    error_hash = error_data.get('_error_hash')
    if not error_hash:
        return None

    if await task_bug_dedup_check('workflow_trace', error_hash):
        return None

    task_id = await _task_bug_create_impl(error_data)
    if task_id is None:
        return None

    trace_id = error_data.get('id', 0)
    return f'task#{task_id} bug from trace #{trace_id}'


async def _run_manager_review(action: dict) -> str | None:
    """
    reviewing -> plan_approval: человек нажал «Обновить план», Manager пересматривает
    существующий план и сверяет его с целями.

    Отдельное действие, а не ветка `manager_plan`: тот отбирает задачи по отсутствию
    плана, а здесь план как раз есть и именно он идёт на вход менеджеру.
    """
    return await _manager_plan_write(action, label='review', state_retry='reviewing')


async def _run_manager_plan(action: dict) -> str | None:
    """
    Задача без плана -> planning -> plan_approval: Manager читает описание и
    пишет план. Отбор идёт по отсутствию плана, а не по человеческому `status`.
    """
    return await _manager_plan_write(action, label='manager', state_retry='new')


async def _manager_plan_write(action: dict, label: str, state_retry: str) -> str | None:
    """
    Общий хвост планирования и пересмотра: сходить к менеджеру и записать результат.

    Задача уже захвачена тиком — различаются действия только тем, откуда её
    взяли и передаётся ли менеджеру старый план.

    `state_retry` — куда вернуть задачу, если прогон сорвался: планирование ждёт
    задачу в `new`, пересмотр — в `reviewing` (см. `_retry_task`).

    Сорвавшимся считаем оба исхода без плана: и упавший прогон (таймаут оболочки,
    ошибка движка), и пустой ответ. Менеджер, вернувший ноль подзадач, работы не
    сделал ровно так же, как и не ответивший вовсе, — разница только в том, дошёл ли
    до нас его текст.
    """
    task = await task_state_task_get(int(action.get('task_id') or 0))
    if not task:
        return None

    revise = bool(action.get('revise'))
    # Роль кладёт тик при захвате: сообщение могло пролежать в очереди, а тип задачи
    # человек за это время мог и поменять — планировать должна та роль, которая
    # задачу взяла. Пустое значение — сообщение из очереди, поставленной старым кодом.
    role = str(action.get('role') or '') or TASK_ROLE_DEFAULT
    # Каталог проекта берём из задачи, а не из сообщения очереди: проект у задачи
    # менялся бы вместе с ней, а сообщение помнит только момент захвата. Пустой
    # каталог (задача без проекта) — адресация остаётся по одной роли.
    work_dir = await task_role_project_work_dir(task.get('project_id'))
    # Каталог заводим и менеджеру, хотя кода он не пишет: в нём живут журнал и
    # состояние строки (`task_log`), а без каталога у задачи под менеджером не было
    # бы для них места и пришлось бы держать второе правило хранения. Номера строки
    # для каталога достаточно, а `task_worktree_ensure` идемпотентен — на пересмотре
    # плана каталог просто найдётся готовым.
    task_dir = await _subtask_dir(work_dir, int(task['id']))
    try:
        result = await task_agent_manager_plan(task, revise=revise, role=role,
                                               work_dir=work_dir, task_dir=task_dir)
    except Exception as e:
        return await _retry_task(task, label, state_retry, role, work_dir, f'Manager: {e}')

    subtasks = result.get('subtasks') or []
    if not subtasks:
        return await _retry_task(task, label, state_retry, role, work_dir,
                                 'Manager не вернул ни одной подзадачи')

    # Прогон состоялся — серия срывов прервана, следующему сбою снова полагаются
    # все повторы.
    await task_retry_clear(task['id'])

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

    # Пометка «в разработку» — заранее данное человеком согласие: план готов, ждать
    # ещё и нажатия «Утвердить» не за чем. Задача сама меняет тип на `dev` и уходит
    # в `approved`, дальше её подберёт разбор плана на подзадачи.
    to_dev = await task_state_plan_to_development(task['id'])
    state = 'approved' if to_dev else 'plan_approval'
    tail  = ('. Задача помечена «в разработку» — план утверждён без человека, '
             'тип сменён на «Разработка»') if to_dev else '. Ждёт утверждения человеком'

    action_word = 'пересмотрел план' if revise else 'составил план'
    await task_report_write(
        task['id'],
        f'{_role_title(role)} {action_word}: {len(subtasks)} {_task_plural_sub(len(subtasks))}, '
        f'{len(goals)} {_task_plural_goal(len(goals))}{tail}',
    )
    logger_info(
        f'[task] task#{task["id"]} -> {state} '
        f'({len(subtasks)} подзадач, {len(goals)} целей)'
    )
    return f"task#{task['id']} {label} -> {state}"
