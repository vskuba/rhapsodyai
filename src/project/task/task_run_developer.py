"""
run_developer: developer — разработка подзадач.

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
закрывает и попытку не жжёт — подзадача уходит на повтор, см. `task_retry`.
Попытку жжёт только состоявшаяся работа, которая не сошлась.

Соседние модули: `task_pipeline` — триггер и карта, `task_run_plan_split` —
разбивка плана, `task_run_qa` — проверка, `task_run_bugfix` — исправление багов,
`task_run_finalize` — финализация, `task_run_manager` — шаги менеджера.
"""
import time

from logging_.logging_ import logger_info
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE, task_agent_developer_run
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_retry import task_retry_clear
from src.project.task.task_role import task_role_project_work_dir
from src.project.task.task_state import (
    task_state_attempt_log,
    task_state_subtask_fail,
    task_state_subtask_get,
    task_state_subtask_set,
    task_state_task_get,
)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    task_setting_timeout_get,
)
from src.project.task.task_pipeline_retry import (
    _log_run,
    _retry_subtask,
    _subtask_branch_save,
    _subtask_dir,
    _subtask_report,
    _task_to_testing,
)


async def _run_developer(action: dict) -> str | None:
    """
    planned | failed_qa -> developing -> qa_pending.
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
