"""
Исполнители шагов конвейера: что делает воркер с захваченной строкой.

Тик (`task_pipeline_tick`) только выбирает работу и ставит её в очередь; этот
модуль — вторая половина. `task_pipeline_action_run` разбирает сообщение очереди
по `_RUNNERS` и зовёт нужный исполнитель. Здесь живут исполнители рабочих шагов —
`_run_plan_split`, `_run_developer`, `_run_qa`, `_run_bugfix`, `_run_finalize`;
шаги менеджера вынесены в `task_pipeline_manager`, повторы сорвавшихся прогонов —
в `task_pipeline_retry` (там же общие хвосты: `_subtask_dir`, `_log_run` и др.).

Адрес оболочки и рабочий каталог подзадачи собираются в конвейере, а не в
агенте: роль постоянная, а каталог и ветка — решения конвейера. Журнал прогона
пишется после каждого прогона — удавшегося, не сошедшегося и оборванного.

Соседние модули: `task_pipeline` — триггер и карта, `task_pipeline_claim` — отбор,
`task_pipeline_manager` — шаги менеджера и скан багов, `task_pipeline_retry` —
повторы и общие хвосты, `task_state` — запись результатов, `task_agent_*` — роли
исполнителей.
"""
import time

from logging_.logging_ import logger_info
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE, task_agent_bugfixer_run
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE, task_agent_developer_run
from src.project.task.task_agent_qa import TASK_QA_ROLE, task_agent_qa_run
from src.project.task.task_plan import task_plan_parse
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_retry import task_retry_clear
from src.project.task.task_role import task_role_project_work_dir
from src.project.task.task_state import (
    task_state_attempt_log,
    task_state_goals_inherit,
    task_state_subtask_fail,
    task_state_subtask_get,
    task_state_subtask_set,
    task_state_subtasks_create,
    task_state_task_done,
    task_state_task_fail,
    task_state_task_finalize,
    task_state_task_get,
)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    task_setting_timeout_get)
from src.project.task.task_pipeline_manager import (
    _run_bug_scan,
    _run_manager_plan,
    _run_manager_review,
)
from src.project.task.task_pipeline_retry import (
    _log_run,
    _retry_subtask,
    _retry_task,
    _subtask_branch_save,
    _subtask_dir,
    _subtask_report,
    _task_plural_sub,
    _task_to_testing,
)


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


# Карта строится после определения шагов: имена должны быть уже объявлены.
# Шаги менеджера и скан багов импортируются сверху из `task_pipeline_manager`.
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
