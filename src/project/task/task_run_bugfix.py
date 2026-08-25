"""
run_bugfix: bugfix — исправление бага.

bugfixing -> done | failed.

Один прогон, один ответ: кругов «не сошлось» у бага нет. `ok: false` — это
состоявшаяся работа с отрицательным вердиктом («не воспроизводится», «причина вне
проекта»), и второй заход по той же фактуре дал бы тот же ответ. Такой баг уходит
человеку в `blocked` — через `failed`, который карта статусов и переводит в
«Заблокировано».

Сорвавшийся прогон — другое дело: оболочка не ответила, Claude Code мёртв, вернулся
не-JSON. Работы не было, и хоронить баг не за что — уходит на повтор тем же
_retry_task, что и менеджер, с возвратом в `new`.

Каталогов здесь два, и путать их нельзя. `work_dir` — адрес оболочки, там запущен
живой Claude Code. `task_dir` — где лежит код, который правят: своя выкладка
репозитория с веткой бага. Ключом выкладки идёт id самой задачи: у бага нет
подзадач, и ветка у него своя, как у любого листа конвейера.

Соседние модули: `task_pipeline` — триггер и карта, `task_run_developer` —
разработка, `task_run_qa` — проверка, `task_run_finalize` — финализация,
`task_run_manager` — шаги менеджера.
"""
import time

from logging_.logging_ import logger_info
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE, task_agent_bugfixer_run
from src.project.task.task_retry import task_retry_clear
from src.project.task.task_role import task_role_project_work_dir
from src.project.task.task_state import (
    task_state_attempt_log,
    task_state_task_done,
    task_state_task_fail,
    task_state_task_get,
)
from src.project.task.task_pipeline_retry import (
    _retry_task,
    _subtask_dir,
)


async def _run_bugfix(action: dict) -> str | None:
    """
    bugfixing -> done | failed.
    """
    task = await task_state_task_get(int(action.get('task_id') or 0))
    if not task:
        return None

    started = time.monotonic()
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
