"""
Исполнение действий конвейера: что делает воркер с захваченной строкой.

Тик (`task_pipeline_tick`) только выбирает работу и ставит её в очередь; этот
модуль — вторая половина. `task_pipeline_action_run` разбирает сообщение очереди
по `_RUNNERS` и зовёт нужный исполнитель. Каждый `_run_*` — один шаг машины
состояний: Manager (план/пересмотр), разбор плана, Developer, QA, Багфиксер,
финализация. Хвосты, общие у нескольких шагов, вынесены в `_manager_plan_write`,
`_retry_task`, `_retry_subtask`.

Адрес оболочки и рабочий каталог подзадачи (`_subtask_dir`) собираются здесь, а
не в агенте: роль постоянная, а каталог и ветка — решения конвейера. Журнал прогона
(`_log_run`) пишется после каждого прогона — удавшегося, не сошедшегося и оборванного.

Соседние модули: `task_pipeline` — триггер и карта, `task_pipeline_claim` — отбор,
`task_state` — запись результатов, `task_agent_*` — роли исполнителей.
"""
import os
import time
from contextlib import suppress

from logging_.logging_ import logger_info
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE, task_agent_bugfixer_run
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE, task_agent_developer_run
from src.project.task.task_agent_manager import task_agent_manager_plan
from src.project.task.task_agent_qa import TASK_QA_ROLE, task_agent_qa_run
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_BRANCH,
    TASK_METADATA_KEY_MR,
    task_metadata_update,
)
from src.project.task.task_plan import (
    task_plan_goals_merge,
    task_plan_goals_normalize,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_retry import task_retry_clear, task_retry_take
from src.project.task.task_role import (TASK_ROLE_DEFAULT, TASK_ROLE_TITLE, task_role_project_work_dir)
from src.project.task.task_revision import task_revision_add
from src.project.task.task_state import (
    task_state_attempt_log,
    task_state_dev_to_testing,
    task_state_goals_inherit,
    task_state_plan_save,
    task_state_plan_to_development,
    task_state_subtask_fail,
    task_state_subtask_get,
    task_state_subtask_set,
    task_state_subtasks_create,
    task_state_task_done,
    task_state_task_fail,
    task_state_task_finalize,
    task_state_task_get,
    task_state_task_requeue,
)
from src.project.task.task_log import task_log_write_run
from src.project.task.task_worktree import task_worktree_ensure
from src.project.team.team_session import team_session_restart_role
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    task_setting_timeout_get)

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
    logger_info(f'[task] task#{task["id"]} -> processing ({created} подзадач)')
    return f"task#{task['id']} processing -> {created} подзадач"


async def _run_developer(action: dict) -> str | None:
    """
    planned | failed_qa -> developing -> qa_pending.

    Адрес оболочки собирается здесь, а не в агенте: роль постоянная (подзадачи
    утверждённого плана всегда делает Developer), а каталог берётся у проекта
    родительской задачи — разработчики разных проектов называются одинаково, и без
    каталога прогон ушёл бы в чужую оболочку.

    Каталогов здесь два, и путать их нельзя. `work_dir` — адрес оболочки, там
    запущен живой Claude Code, и меняться он не может. `subtask_dir` — где лежит
    код, который правят: своя выкладка репозитория со своей веткой
    (`.claude/worktrees/feature_task_<id>`). Оболочка остаётся на месте, а работает
    в каталоге подзадачи — так правки не задевают ни master, ни каталог человека.

    Сорвавшийся прогон (исключение из агента: таймаут, мёртвая оболочка) круг не
    закрывает и попытку не жжёт — подзадача уходит на повтор, см. `_retry_subtask`.
    Попытку жжёт только состоявшаяся работа, которая не сошлась.
    """
    subtask = await task_state_subtask_get(int(action.get('subtask_id') or 0))
    if not subtask:
        return None

    task = await task_state_task_get(subtask['parent_id'])
    attempt_no = int(subtask['pipeline_attempt_count']) + 1
    started = time.monotonic()
    work_dir = await task_role_project_work_dir((task or {}).get('project_id'))
    subtask_dir = await _subtask_dir(work_dir, subtask['id'])

    try:
        result = await task_agent_developer_run(
            task, subtask, str(subtask.get('pipeline_error') or ''),
            role=TASK_DEVELOPER_ROLE, work_dir=work_dir, subtask_dir=subtask_dir)
    except Exception as e:
        return await _retry_subtask(subtask, 'developer', 'planned', TASK_DEVELOPER_ROLE,
                                    work_dir, attempt_no, started, f'Developer: {e}')

    # Среда не пригодна для работы (сервер подзадачи не поднялся, ветка выкачена от
    # сломанного master) — работы не было, и жечь попытку не за что: возвращаем строку
    # в очередь тем же путём, что и сорвавшийся прогон. Лимит повторов не даст крутить
    # это вечно: три отказа подряд человек увидит как `blocked`.
    if not result.get('env_ok', True):
        return await _retry_subtask(subtask, 'developer', 'planned', TASK_DEVELOPER_ROLE,
                                    work_dir, attempt_no, started,
                                    f"Developer: среда не готова — {result.get('error') or 'сервер подзадачи не отвечает'}")

    await task_retry_clear(subtask['id'])
    await task_state_attempt_log(subtask['id'], attempt_no, 'developer', result, started)
    await _subtask_branch_save(subtask['id'], result)
    await _log_run(subtask['id'], work_dir, result, 'developer', attempt_no)

    if result.get('ok'):
        await task_state_subtask_set(subtask['id'], 'qa_pending', last_error='')
        await _subtask_report(subtask, f'разработка завершена (попытка {attempt_no}), ушла на проверку QA')
        await _task_to_testing(task)
        return f"subtask#{subtask['id']} developer -> qa_pending"

    # Развалился сам разработчик — попытка засчитана, круг закрываем как провал.
    error = str(result.get('error') or 'ошибка разработчика')
    max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)
    state = await task_state_subtask_fail(subtask['id'], attempt_no, error, max_attempts)
    await _subtask_report(subtask, f'разработчик сорвался (попытка {attempt_no} из {max_attempts}): {error}',
                          ok=False, blocked=state == 'blocked')
    return f"subtask#{subtask['id']} developer -> {state}"


async def _run_qa(action: dict) -> str | None:
    """
    testing -> done | failed_qa | blocked.

    Адрес оболочки собирается здесь по тем же правилам, что и у разработчика:
    роль постоянная (`qa`), каталог — у проекта родительской задачи. Код проверяем
    в каталоге подзадачи — том же, где его писал разработчик: проверять ветку по
    общему чекауту значило бы смотреть чужой код. Ошибка QA
    уходит подзадаче в `pipeline_error`, и следующий круг разработчик получает её
    на вход замечанием — поэтому важно, чтобы в ней были конкретные пункты, а не
    «проверки не прошли».

    Сорвавшийся прогон QA, как и у разработчика, круг не закрывает: вернуть подзадачу
    разработчику из-за того, что зависла проверяющая оболочка, значило бы попросить
    переделать работу, которую никто не смотрел.
    """
    subtask = await task_state_subtask_get(int(action.get('subtask_id') or 0))
    if not subtask:
        return None

    task = await task_state_task_get(subtask['parent_id'])
    attempt_no = int(subtask['pipeline_attempt_count']) + 1
    started = time.monotonic()
    work_dir = await task_role_project_work_dir((task or {}).get('project_id'))
    subtask_dir = await _subtask_dir(work_dir, subtask['id'])

    try:
        result = await task_agent_qa_run(
            task, subtask, str(subtask.get('pipeline_error') or ''),
            role=TASK_QA_ROLE, work_dir=work_dir, subtask_dir=subtask_dir)
    except Exception as e:
        return await _retry_subtask(subtask, 'qa', 'qa_pending', TASK_QA_ROLE,
                                    work_dir, attempt_no, started, f'QA: {e}')

    # Проверять не на чем — вернуть подзадачу разработчику нельзя: его работу никто
    # не смотрел. Как и у разработчика, это повтор без потраченной попытки.
    if not result.get('env_ok', True):
        return await _retry_subtask(subtask, 'qa', 'qa_pending', TASK_QA_ROLE,
                                    work_dir, attempt_no, started,
                                    f"QA: среда не готова — {result.get('error') or 'сервер подзадачи не отвечает'}")

    await task_retry_clear(subtask['id'])
    await task_state_attempt_log(subtask['id'], attempt_no, 'qa', result, started)
    await _log_run(subtask['id'], work_dir, result, 'qa', attempt_no)

    if result.get('ok'):
        await task_state_subtask_set(subtask['id'], 'done', last_error='', attempt_count=attempt_no)
        # Цели подзадачи здесь не трогаем: галочки уже проставил сам QA в ходе
        # прогона — по одной, каждую своим ответом (`src/tool/project/task_goal.py`).
        # Закрыть их отсюда значило бы отметить проверенным и то, что он не подтвердил.
        await _subtask_report(subtask, 'проверку QA прошла, подзадача готова')
        return f"subtask#{subtask['id']} qa -> done"

    error = str(result.get('error') or 'проверки не прошли')
    max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)
    state = await task_state_subtask_fail(subtask['id'], attempt_no, error, max_attempts)
    await _subtask_report(subtask, f'QA вернул на доработку (попытка {attempt_no} из {max_attempts}): {error}',
                          ok=False, blocked=state == 'blocked')
    return f"subtask#{subtask['id']} qa -> {state}"


async def _run_bugfix(action: dict) -> str | None:
    """
    bugfixing -> done | failed.

    Один прогон, один ответ: кругов «не сошлось» у бага нет. `ok: false` — это
    состоявшаяся работа с отрицательным вердиктом («не воспроизводится», «причина вне
    проекта»), и второй заход по той же фактуре дал бы тот же ответ. Такой баг уходит
    человеку в `blocked` — через `failed`, который карта статусов и переводит в
    «Заблокировано».

    Сорвавшийся прогон — другое дело: оболочка не ответила, Claude Code мёртв, вернулся
    не-JSON. Работы не было, и хоронить баг не за что — уходит на повтор тем же
    `_retry_task`, что и менеджер, с возвратом в `new`.

    Каталогов здесь два, и путать их нельзя. `work_dir` — адрес оболочки, там запущен
    живой Claude Code. `task_dir` — где лежит код, который правят: своя выкладка
    репозитория с веткой бага. Ключом выкладки идёт id самой задачи: у бага нет
    подзадач, и ветка у него своя, как у любого листа конвейера.
    """
    task = await task_state_task_get(int(action.get('task_id') or 0))
    if not task:
        return None

    started  = time.monotonic()
    work_dir = await task_role_project_work_dir(task.get('project_id'))
    task_dir = await _subtask_dir(work_dir, task['id'])

    try:
        result = await task_agent_bugfixer_run(
            task, role=TASK_BUGFIXER_ROLE, work_dir=work_dir, task_dir=task_dir)
    except Exception as e:
        return await _retry_task(task, 'bugfix', 'new', TASK_BUGFIXER_ROLE,
                                 work_dir, f'Багфиксер: {e}')

    # Среда не пригодна для работы (каталог бага не поднялся, ветка выкачена от
    # сломанного master) — работы не было, и вести баг в `blocked` не за что: его никто
    # не смотрел. Возвращаем строку в очередь тем же путём, что и сорвавшийся прогон;
    # лимит повторов не даст крутить это вечно.
    if not result.get('env_ok', True):
        return await _retry_task(
            task, 'bugfix', 'new', TASK_BUGFIXER_ROLE, work_dir,
            f"Багфиксер: среда не готова — {result.get('error') or 'каталог бага не поднялся'}")

    await task_retry_clear(task['id'])
    # Попытка всегда первая: круг у бага один, и `pipeline_attempt_count` он не растит.
    # Строка журнала нужна ради времени прогона и текста отчёта — по ней видно, сколько
    # багфиксер думал и что сделал.
    await task_state_attempt_log(task['id'], 1, TASK_BUGFIXER_ROLE, result, started)

    if result.get('ok'):
        report = str(result.get('output') or '').strip() or 'отчёт не заполнен'
        await task_state_task_done(task['id'], f'Баг починен (Багфиксер): {report}')
        return f"task#{task['id']} bugfix -> done"

    error = str(result.get('error') or 'багфиксер не назвал причину')
    await task_state_task_fail(task['id'], f'Баг не починен: {error}')
    return f"task#{task['id']} bugfix -> failed"


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


async def _retry_task(task: dict, label: str, state_retry: str, role: str,
                      work_dir: str, error: str) -> str:
    """
    Прогон менеджера сорвался: перезапустить оболочку и вернуть задачу следующему тику.

    Лимит исчерпан — задача уходит в `failed` тем же путём, что и раньше: три
    сорвавшихся прогона подряд означают, что дело не в случайности и нужен человек.

    Повторяем не здесь, а следующим тиком. Второй поход к менеджеру внутри той же job
    не влезает в отведённое воркеру время (`timeout_worker_job` против часа
    на прогон), и rq убил бы его посреди работы.

    Порядок важен: сначала считаем срыв, потом перезапускаем оболочку и только в конце
    отпускаем строку. Умри воркер на перезапуске — строка останется заблокированной в
    переходном состоянии, и её вернёт `task_claim_locks_reclaim()` ровно туда же, куда
    вернули бы мы; отпусти мы её первой, задачу успел бы забрать соседний воркер и
    отправить в оболочку, которую мы в этот момент гасим.
    """
    retry = await task_retry_take(task['id'], role, error)
    if not retry['allowed']:
        # Счётчик дописываем в текст ошибки: она же уходит в отчёт задачи, и без него
        # человек видел бы одинокий сбой там, где агент молчал четыре прогона подряд.
        await task_state_task_fail(
            task['id'], f'{error} (срывов подряд: {retry["count"]}, повторы исчерпаны)')
        return f"task#{task['id']} {label} -> failed"

    await task_report_write(
        task['id'],
        f'{_role_title(role)} не вернул результат ({error}). Перезапуск оболочки и повтор '
        f'{retry["count"]} из {retry["max"]}',
        ok=None)
    await team_session_restart_role(role, work_dir)
    await task_state_task_requeue(task['id'], state_retry, error)
    return f"task#{task['id']} {label} -> retry {retry['count']}/{retry['max']}"


async def _retry_subtask(subtask: dict, step: str, state_retry: str, role: str, work_dir: str,
                         attempt_no: int, started: float, error: str) -> str:
    """
    Прогон Developer/QA сорвался: перезапустить оболочку и вернуть подзадачу в очередь.

    Круг не закрываем и `pipeline_attempt_count` не трогаем — работы не было, жечь
    попытку не за что. Ошибку в `pipeline_error` тоже не пишем: разработчик читает её
    как замечание QA, а «оболочка не ответила» замечанием не является и только сбило бы
    его со следующего круга. След срыва остаётся в отчёте задачи, в `metadata.retry`
    и строкой `project_task_attempt` — по ней видно, сколько прогон продержался.

    Лимит исчерпан — закрываем круг как провал, обычным `task_state_subtask_fail`:
    три подряд сорвавшихся прогона по одной подзадаче человек должен увидеть.

    `state_retry` — куда вернуть строку: разработка -> `planned`, проверка ->
    `qa_pending` (те же значения, что у возврата брошенной блокировки).
    """
    result = {'ok': False, 'output': '', 'error': error}
    await task_state_attempt_log(subtask['id'], attempt_no, step, result, started)
    # Ради этого журнал и заводили: ответа нет, но шаги, что успели пройти, в
    # трассе остались — следующий круг начнёт с них, а не с чистого листа.
    await _log_run(subtask['id'], work_dir, result, role, attempt_no, error)

    retry = await task_retry_take(subtask['id'], role, error)
    if not retry['allowed']:
        max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)
        state = await task_state_subtask_fail(subtask['id'], attempt_no, error, max_attempts)
        await _subtask_report(
            subtask,
            f'{_role_title(role)} не вернул результат {retry["count"]} раза подряд, '
            f'повторы исчерпаны: {error}',
            ok=False, blocked=state == 'blocked')
        return f"subtask#{subtask['id']} {step} -> {state}"

    await _subtask_report(
        subtask,
        f'{_role_title(role)} не вернул результат ({error}). Перезапуск оболочки и повтор '
        f'{retry["count"]} из {retry["max"]}',
        ok=None)
    await team_session_restart_role(role, work_dir)
    await task_state_subtask_set(subtask['id'], state_retry)
    return f"subtask#{subtask['id']} {step} -> retry {retry['count']}/{retry['max']}"


async def _subtask_report(subtask: dict, text: str, ok: bool | None = True, blocked: bool = False) -> None:
    """
    Отчёт шага Developer/QA пишем в родительскую задачу: своего поля отчёта у
    подзадачи нет, а человек следит именно за задачей.

    К строке шага добавляем сводку по всем подзадачам — без неё непонятно,
    насколько задача близка к финишу.
    """
    task_id = int(subtask.get('parent_id') or 0)
    summary = await task_report_subtasks_summary(task_id)
    title   = str(subtask.get('title') or '').strip()
    label   = f'Подзадача #{subtask["id"]}' + (f' «{title}»' if title else '')
    tail    = ' — исчерпаны попытки, нужен человек' if blocked else ''
    await task_report_write(task_id, f'{label}: {text}{tail}. Всего: {summary}', ok=ok)


async def _task_to_testing(task: dict) -> bool:
    """
    Пометка «в тестирование»: последний разработчик закончил -> задача уходит на проверку.

    Зовём после каждого удачного круга Developer, а решает `task_state_dev_to_testing`:
    переход состоится только у той задачи, где в `qa_pending` упёрлись уже все ветки
    плана. Разработчик, закрывший свою подзадачу первым из трёх, просто получит False.

    Отдельного шага конвейера тут нет намеренно: это не работа агента, а смена
    вкладки — тип на «Тестирование», состояние `testing`, — и лишний проход тика она
    не стоит. Круг QA по подзадачам идёт дальше как ни в чём не бывало, задачу закроет
    та же финализация.
    """
    task_id = int((task or {}).get('id') or 0)
    if not task_id or not await task_state_dev_to_testing(task_id):
        return False

    await task_report_write(
        task_id,
        'Разработка по всем подзадачам закончена. Задача помечена «в тестирование» — '
        'тип сменён на «Тестирование», идёт проверка')
    return True


async def _subtask_branch_save(subtask_id: int, result: dict) -> None:
    """
    Ветка и merge request из отчёта разработчика — в metadata подзадачи.

    Пишем и на неудачном круге: ветку разработчик заводит до того, как работа сойдётся,
    и на разборе провала ссылка нужнее всего. Пустые значения не пишем — иначе круг,
    сорвавшийся до первого коммита, затёр бы ссылку, добытую кругом раньше.
    """
    patch = {key: value for key, value in (
        (TASK_METADATA_KEY_BRANCH, str(result.get('branch') or '').strip()),
        (TASK_METADATA_KEY_MR,     str(result.get('mr_url') or '').strip()),
    ) if value}
    if patch:
        await task_metadata_update(subtask_id, patch)


async def _log_run(task_id: int, work_dir: str, result: dict, role: str,
                   attempt_no: int, error: str = '') -> None:
    """
    Переложить прогон роли в журнал строки — то, что прочтёт следующий круг.

    Зовётся после каждого прогона: и удавшегося, и не сошедшегося, и оборванного.
    Оборванный тут важнее всех — ответа у него нет, а пройденные шаги в трассе
    есть, и без этой записи следующий круг начал бы с чистого листа. Так и вышло
    с подзадачей #1028: шестнадцать минут, чтобы заново узнать про собственный
    коммит.

    Ошибки глушим: журнал вспомогательный, и ронять из-за него состоявшийся круг
    нечестно.
    """
    outcome = str(error or result.get('error') or '').strip()
    if not outcome:
        outcome = 'готово' if result.get('ok') else 'работа не сошлась'

    with suppress(Exception):
        await task_log_write_run(work_dir, task_id, str(result.get('session_uuid') or ''),
                                 role, attempt_no, outcome)


async def _subtask_dir(work_dir: str, subtask_id: int) -> str:
    """
    Рабочий каталог подзадачи — своя выкладка репозитория со своей веткой.

    Заводится здесь, а не агентом: имя ветки и точка отреза (`origin/master`) —
    решения конвейера, и живому Claude Code их пересказывать нельзя, он их
    переиначивает. К моменту первого промпта ветка уже выкачена, разработчику
    остаётся работать.

    Каталог общий у Developer и QA, поэтому вызов идёт из обеих веток и обязан
    быть идемпотентным — `task_worktree_ensure` таков.

    Сорваться создание может по-разному (нет прав, занята ветка, битый git), и
    ронять из-за этого круг не станем: пустая строка означает «работай там же, где
    раньше» — в общем каталоге проекта. Это прежнее поведение конвейера, оно
    рабочее, просто без изоляции.

    Отдельно ловим невидимый каталог. Проектов на машине несколько, каждый со своим
    репозиторием, а в контейнер смонтированы не все: свой каталог установки идёт из
    `PROJECT_HOST_DIR`, чужие добавляют руками в `docker-compose.override.yml`.
    Забытое монтирование выглядит изнутри как «каталога нет» и без отдельного
    сообщения выливается в невнятный сбой git — поэтому говорим прямо, что делать.
    """
    if not work_dir or not subtask_id:
        return ''

    if not os.path.isdir(work_dir):
        logger_info(f'[task] subtask#{subtask_id}: каталог проекта {work_dir} не виден — '
                    f'проверьте PROJECT_HOST_DIR и монтирования в docker-compose.override.yml '
                    f'(путь внутри контейнера обязан совпадать с путём на хосте); '
                    f'работаем в каталоге проекта')
        return ''

    try:
        return await task_worktree_ensure(work_dir, subtask_id)
    except Exception as e:
        logger_info(f'[task] subtask#{subtask_id}: рабочий каталог не создан ({e}), '
                    f'работаем в каталоге проекта')
        return ''


# Карта строится после определения шагов: имена должны быть уже объявлены.
_RUNNERS = {
    'bug_scan':       _run_bug_scan,
    'manager_review': _run_manager_review,
    'manager_plan':   _run_manager_plan,
    'plan_split':     _run_plan_split,
    'developer':      _run_developer,
    'qa':             _run_qa,
    'bugfix':         _run_bugfix,
    'finalize':       _run_finalize,
}


# ── детали реализации ──────────────────────────────────────────────────────────

def _role_title(role: str) -> str:
    """Подлежащее для строки отчёта: «Менеджер составил план», «QA составил план»."""
    return TASK_ROLE_TITLE.get(role, TASK_ROLE_TITLE[TASK_ROLE_DEFAULT])


def _task_plural_sub(n: int) -> str:
    return _task_plural(n, 'подзадача', 'подзадачи', 'подзадач')


def _task_plural_goal(n: int) -> str:
    return _task_plural(n, 'цель', 'цели', 'целей')


def _task_plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
