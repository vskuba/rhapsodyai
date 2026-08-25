"""
Общие хвосты конвейера: то, что нужно и менеджеру, и исполнителям подзадач.

Исполнители живут в `task_pipeline_manager` (планирование и пересмотр) и
`task_pipeline_executors` (разработчик, QA, багфиксер, финализация); здесь —
общий для них хвост. Журнал прогона (`_pipeline_log_run`) пишется после каждого
прогона — удавшегося, не сошедшегося и оборванного. Повторы сорвавшихся прогонов
(`_pipeline_retry_task`, `_pipeline_retry_subtask`) перезапускают оболочку и
возвращают строку в очередь, не жжя попытку: работы не было, а лимит повторов
ловит случай, когда дело не в случайности.

Адрес оболочки и рабочий каталог подзадачи (`_pipeline_subtask_dir`) собираются
здесь, а не в агенте: роль постоянная, а каталог и ветка — решения конвейера.
"""
import os
from contextlib import suppress

from logging_.logging_ import logger_info
from src.project.task.task_log import task_log_write_run
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_BRANCH,
    TASK_METADATA_KEY_MR,
    task_metadata_update,
)
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_retry import task_retry_take
from src.project.task.task_role import TASK_ROLE_DEFAULT, TASK_ROLE_TITLE
from src.project.task.task_state import (
    task_state_attempt_log,
    task_state_dev_to_testing,
    task_state_subtask_fail,
    task_state_subtask_set,
    task_state_task_fail,
    task_state_task_requeue,
)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    task_setting_timeout_get,
)
from src.project.task.task_worktree import task_worktree_ensure
from src.project.team.team_session import team_session_restart_role


async def _pipeline_log_run(task_id: int, work_dir: str, result: dict, role: str,
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


async def _pipeline_subtask_dir(work_dir: str, subtask_id: int) -> str:
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


async def _pipeline_subtask_branch_save(subtask_id: int, result: dict) -> None:
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


async def _pipeline_subtask_report(subtask: dict, text: str, ok: bool | None = True,
                                   blocked: bool = False) -> None:
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


async def _pipeline_task_to_testing(task: dict) -> bool:
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


async def _pipeline_retry_task(task: dict, label: str, state_retry: str, role: str,
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
        f'{_pipeline_role_title(role)} не вернул результат ({error}). Перезапуск оболочки и повтор '
        f'{retry["count"]} из {retry["max"]}',
        ok=None)
    await team_session_restart_role(role, work_dir)
    await task_state_task_requeue(task['id'], state_retry, error)
    return f"task#{task['id']} {label} -> retry {retry['count']}/{retry['max']}"


async def _pipeline_retry_subtask(subtask: dict, step: str, state_retry: str, role: str,
                                  work_dir: str, attempt_no: int, started: float,
                                  error: str) -> str:
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
    await _pipeline_log_run(subtask['id'], work_dir, result, role, attempt_no, error)

    retry = await task_retry_take(subtask['id'], role, error)
    if not retry['allowed']:
        max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)
        state = await task_state_subtask_fail(subtask['id'], attempt_no, error, max_attempts)
        await _pipeline_subtask_report(
            subtask,
            f'{_pipeline_role_title(role)} не вернул результат {retry["count"]} раза подряд, '
            f'повторы исчерпаны: {error}',
            ok=False, blocked=state == 'blocked')
        return f"subtask#{subtask['id']} {step} -> {state}"

    await _pipeline_subtask_report(
        subtask,
        f'{_pipeline_role_title(role)} не вернул результат ({error}). Перезапуск оболочки и повтор '
        f'{retry["count"]} из {retry["max"]}',
        ok=None)
    await team_session_restart_role(role, work_dir)
    await task_state_subtask_set(subtask['id'], state_retry)
    return f"subtask#{subtask['id']} {step} -> retry {retry['count']}/{retry['max']}"


# ── детали реализации ──────────────────────────────────────────────────────────

def _pipeline_role_title(role: str) -> str:
    """Подлежащее для строки отчёта: «Менеджер составил план», «QA составил план»."""
    return TASK_ROLE_TITLE.get(role, TASK_ROLE_TITLE[TASK_ROLE_DEFAULT])


def _pipeline_plural_sub(n: int) -> str:
    """Подзадача / подзадачи / подзадач — склонение по количеству."""
    return _pipeline_plural(n, 'подзадача', 'подзадачи', 'подзадач')


def _pipeline_plural_goal(n: int) -> str:
    """Цель / цели / целей — склонение по количеству."""
    return _pipeline_plural(n, 'цель', 'цели', 'целей')


def _pipeline_plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
