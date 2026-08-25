"""
Машина состояний конвейера задач.

Разделена на две половины. `task_pipeline_tick()` — триггер: сбрасывает протухшие
блокировки, захватывает строки и ставит по сообщению на действие в Redis-очередь,
после чего сразу возвращается. Запускается по расписанию из Cronicle через
`task_orchestrator.py` и не ходит ни к менеджеру, ни к агентам — тик обязан быть
коротким, иначе Cronicle начнёт накладывать запуски друг на друга.

`task_pipeline_action_run()` — вторая половина: её зовёт `rq worker`
(см. `src/worker/project/task_worker.py`), и уже она делает саму работу. Воркеров может быть много.

    task.pipeline_state:
        (нет плана) -> planning -> plan_approval -> (человек) -> approved -> processing -> done|failed
                       reviewing --^                   (человек: «Обновить план»)

    Вход в конвейер — отсутствие плана, а не явная отправка: задачу без
    `pipeline_plan` Manager подхватывает при любом человеческом `status`.

    Второй вход — `reviewing`: у задачи план есть, но человек отправил его на пересмотр.
    По отсутствию плана такую задачу не отобрать, поэтому у неё своё состояние и свой
    шаг; результат тот же — `plan_approval`.

    Шаг человека пропускается, если задача помечена флажком «в разработку»
    (`metadata.to_development`): согласие дано заранее, и с готовым планом задача сама
    уходит в `approved`, сменив тип с `plan` на `dev` (`task_state_plan_to_development`).

    Из `processing` задача уходит в `testing`, когда разработка кончилась по всем веткам
    плана (все дети в `qa_pending` или `testing`), а пометка «в тестирование» (`metadata.to_testing`) не
    снята — по умолчанию она стоит. Тип меняется с `dev` на `test`, работа продолжается
    та же: круг QA по подзадачам и общая финализация (`task_state_dev_to_testing`).

    Подзадача.pipeline_state:
        planned -> developing -> qa_pending -> testing -> done
                        ^                         '-> failed_qa -> повтор, пока попыток < timeout_attempt_max
                        '---------------------------'                    '-> blocked (лимит исчерпан)

    `qa_pending` — очередь к QA, `testing` — проверка уже идёт. Состояния два, а не одно,
    потому что «работа сделана и ждёт» и «над работой сейчас думают» — разные новости для
    человека: подзадача под живой проверкой иначе выглядит на странице застрявшей.

    Подзадача — строка того же `project_task` с непустым `parent_id`: отдельной таблицы
    у конвейера нет, дерево задач одно. Поэтому ветку задаёт `parent_id`, а не колонка:
    у корневой задачи состояния планирования, у ребёнка — круг Developer → QA.

    Баг.pipeline_state:
        (тип `bug`) -> bugfixing -> done | failed

    У бага нет плана, подзадач и второго круга: багфиксер воспроизводит, чинит и
    проверяет за один прогон. Отрицательный вердикт — это `failed`, то есть
    «Заблокировано» для человека, а не новый круг: та же фактура дала бы тот же ответ.
    Отсюда и отдельное состояние захвата: `developing` бывает только у подзадач плана,
    и карты возврата брошенной блокировки у корневых строк и подзадач разные.

    Переходные состояния (`planning`, `reviewing`, `developing`, `testing`) — это и
    есть «действие в работе»: пока строка в них, тик её не подберёт. Умер воркер —
    блокировку вернёт `task_claim_locks_reclaim()` по таймауту, и работа встанет
    в очередь заново.

    Агент не ответил (таймаут прогона, зависшая оболочка, пустой план у менеджера) —
    это не результат работы, а несостоявшийся прогон: его оболочку перезапускаем и тот
    же вход отдаём заново, до `timeout_retry_max` раз (`task_retry`). Круг Developer → QA
    такой срыв не жжёт — попытку тратит только состоявшаяся работа, которая не сошлась.

Соседние модули: `task_pipeline_claim` — отбор и захват строк, `task_pipeline_run` —
исполнители действий, `task_claim` — блокировки, `src/worker/project/task_worker` —
очередь и job для воркера, `task_state` — запись результатов, `task_agent_*` — роли
исполнителей, `task_plan` — формат плана.
"""
import asyncio
import time
from contextlib import suppress

from logging_.logging_ import logger_info
from src.project.task.task_claim import (
    TASK_CLAIM_LOCK_TOUCH_SEC,
    task_claim_lock_touch,
    task_claim_locks_reclaim,
    task_claim_worker_id,
)
from src.project.task.task_role import task_role_project_work_dir
from src.project.team.team_session import team_session_restart_role
from src.project.task.task_retry import task_retry_reset_tree
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_WORKER_JOB,
    task_setting_timeout_get,
)
from src.worker.project.task_worker import (
    TASK_WORKER_SINGLE_FLIGHT,
    task_worker_enqueue,
    task_worker_flight_acquire,
    task_worker_flight_release,
)

# ── Отбор и захват: что тик кладёт в очередь ────────────────────────────────────
from src.project.task.task_pipeline_claim import (
    _action_claim,
    _claim_bugfix,
    _claim_developer,
    _claim_manager_plan,
    _claim_manager_review,
    _claim_plan_split,
    _claim_qa,
    _roles_by_project_free,
)

# ── Исполнители: что делает воркер ──────────────────────────────────────────────
from src.project.task.task_pipeline_run import (
    _RUNNERS,
    _log_run,
    _manager_plan_write,
    _retry_subtask,
    _retry_task,
    _run_bug_scan,
    _run_bugfix,
    _run_developer,
    _run_finalize,
    _run_manager_plan,
    _run_manager_review,
    _run_plan_split,
    _run_qa,
    _subtask_branch_save,
    _subtask_dir,
    _subtask_report,
    _task_to_testing,
)

BUG_TASK_SCAN_ENABLED = True  # env: BUG_TASK_SCAN_ENABLED=1

# Сколько кругов Developer/QA допустимо по одной подзадаче — настройка
# `timeout_attempt_max` с `/admin/team`, см. `task_setting_timeout`.


async def task_pipeline_tick(max_actions: int = 1) -> dict:
    """
    Один тик оркестратора: захватить работу и поставить её в очередь.

    Работу не выполняет — ни одного похода к агентам здесь нет, поэтому тик
    укладывается в секунды при любой загрузке конвейера.

    Returns:
        queued: сколько действий поставлено в очередь.
        reclaimed: сколько протухших блокировок сброшено.
        jobs: описания поставленных действий для лога.
    """
    worker = task_claim_worker_id()
    stats = {'queued': 0, 'reclaimed': await task_claim_locks_reclaim(), 'jobs': []}
    # Одно чтение настройки на тик: её же срок получают и job, и ключ single-flight.
    job_timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_WORKER_JOB)

    # Подметальщики (скан багов, финализация) идут вне бюджета действий: захватывать
    # им нечего, работу они ищут сами уже в воркере. Считайся они за действие — при
    # max_actions=1 каждый тик уходил бы на скан, а задачи стояли бы в очереди.
    for kind in TASK_WORKER_SINGLE_FLIGHT:
        if kind == 'bug_scan' and not BUG_TASK_SCAN_ENABLED:
            continue
        if task_worker_flight_acquire(kind, job_timeout):
            _action_queue(stats, {'kind': kind}, job_timeout)

    for _ in range(max(1, int(max_actions))):
        action = await _action_claim(worker)
        if not action:
            break
        _action_queue(stats, action, job_timeout)

    if stats['queued']:
        logger_info(f'[task] тик поставил в очередь: {", ".join(stats["jobs"])}')
    return stats


async def task_pipeline_action_run(action: dict) -> str | None:
    """
    Выполнить одно действие из очереди. Зовётся воркером, не тиком.

    None — делать оказалось нечего: строку успел увести другой воркер или её
    состояние изменил человек, пока сообщение лежало в очереди. Это норма, а не
    ошибка: работу вернёт следующий тик.

    Пока действие идёт, рядом крутится `_lock_hold`: он подновляет блокировку
    строки, и та не стареет до возраста, на котором реклейм считает работу
    брошенной. Без этого час работы агента держался на том, что тик всё это время
    видит job в Redis, — а увидеть его тик может не всегда.
    """
    runner = _RUNNERS.get(str(action.get('kind') or ''))
    if not runner:
        return None

    hold = asyncio.create_task(_lock_hold(action))
    try:
        return await runner(action)
    finally:
        hold.cancel()
        with suppress(asyncio.CancelledError):
            await hold


async def task_pipeline_shells_restart(task: dict) -> list[str]:
    """
    Погасить агентов, зависших на сорванном прогоне задачи. Зовёт ручной повтор.

    Автоповтор перезапускает оболочку сам (`_retry_task`, `_retry_subtask`), но
    последний срыв — тот самый, что увёл задачу в `failed`, — уходит человеку без
    перезапуска: повторов больше нет, и перезапускать было незачем. Значит,
    дочерний Claude Code так и остался с брошенным ходом, и «Перезапустить» без
    этого вызова отдало бы новый прогон оболочке, которая всё ещё дожёвывает
    предыдущий.

    Кого гасить и обнуление серии повторов — за `task_retry_reset_tree`: счётчик
    срывов его, там же и роль сорвавшегося прогона.

    Готовности агента не ждём: это HTTP-запрос человека, а не воркер, и держать
    соединение полминуты нечем. Прогон, который задачу подберёт, перезапустит
    оболочку своим `team_session_restart_role` и дождётся её сам.

    Returns: роли, которым ушёл маркер перезапуска.
    """
    task_id = int(task.get('id') or 0)
    roles = await task_retry_reset_tree(task_id) if task_id else []
    if not roles:
        return []

    work_dir = await task_role_project_work_dir(task.get('project_id'))
    for role in roles:
        await team_session_restart_role(role, work_dir, wait=False)

    logger_info(f'[task] task#{task_id}: ручной повтор, перезапуск оболочек: {", ".join(roles)}')
    return roles


# ── детали реализации ──────────────────────────────────────────────────────────

def _action_queue(stats: dict, action: dict, job_timeout: int) -> None:
    """Поставить действие в очередь и записать его в статистику тика."""
    kind = str(action.get('kind') or '')
    try:
        job_id = task_worker_enqueue(action, job_timeout)
    except Exception:
        # Очередь недоступна — держать за собой single-flight нельзя, иначе тип
        # действия будет заперт до истечения TTL ключа.
        task_worker_flight_release(kind)
        raise
    stats['queued'] += 1
    stats['jobs'].append(_action_label(action, job_id))


def _action_label(action: dict, job_id: str) -> str:
    target = action.get('task_id') and f" task#{action['task_id']}" or ''
    target = target or (action.get('subtask_id') and f" subtask#{action['subtask_id']}" or '')
    return f"{action.get('kind')}{target} [{job_id[:8]}]"


async def _lock_hold(action: dict) -> None:
    """
    Пока действие выполняется — держать его блокировку свежей.

    Реклейм судит о брошенности по возрасту блокировки, и живой строке стареть
    незачем: раз в `TASK_CLAIM_LOCK_TOUCH_SEC` секунд подновляем `pipeline_locked_at`,
    и до возраста «брошена» строка не доживает, пока идёт работа. Это заменяет
    прежнюю опору на запись job в Redis: та живёт своим коротким TTL, и её пропажа
    у часового прогона означала снятую блокировку у работающего агента — а следом
    и лишний захват сверх предела «Parallel LLM».

    Ограничены сроком job: если процесс завис, но не умер, подновление
    прекращается, и дальше работает прежняя страховка по `timeout_task_lock`.
    Отказ `task_claim_lock_touch` — блокировку уже сняли (реклейм, ручной повтор,
    человек на странице задач); тогда просто уходим, чужую метку не ставим.
    """
    row_id = int(action.get('task_id') or action.get('subtask_id') or 0)
    if not row_id:
        return

    deadline = time.monotonic() + await task_setting_timeout_get(TASK_SETTING_TIMEOUT_WORKER_JOB)
    while time.monotonic() < deadline:
        await asyncio.sleep(TASK_CLAIM_LOCK_TOUCH_SEC)
        if not await task_claim_lock_touch(row_id):
            return
