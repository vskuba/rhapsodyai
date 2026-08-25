"""
run_qa: qa — проверка качества разработки подзадачи.

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

Соседние модули: `task_pipeline` — триггер и карта, `task_run_developer` —
разработка, `task_run_bugfix` — исправление багов, `task_run_finalize` —
финализация, `task_run_manager` — шаги менеджера.
"""
import time

from logging_.logging_ import logger_info
from src.project.task.task_agent_qa import TASK_QA_ROLE, task_agent_qa_run
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
    _subtask_dir,
    _subtask_report,
)


async def _run_qa(action: dict) -> str | None:
    """
    testing -> done | failed_qa | blocked.
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
