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

Соседние модули: `task_claim` — захват и блокировки, `src/worker/project/task_worker` — очередь и
job для воркера, `task_state` — запись результатов, `task_agent_manager` — Manager
через shell-оболочку, `task_agent_developer` — Developer через свою оболочку,
`task_agent_qa` — QA через свою, `task_plan` — формат плана.
"""
import asyncio
import os
import time
from contextlib import suppress

from logging_.logging_ import logger_info
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE, task_agent_bugfixer_run
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE, task_agent_developer_run
from src.project.task.task_agent_manager import task_agent_manager_plan
from src.project.task.task_agent_qa import TASK_QA_ROLE, task_agent_qa_run
from src.project.task.task_claim import (
    TASK_CLAIM_LOCK_TOUCH_SEC,
    task_claim_inflight_by_project,
    task_claim_lock_touch,
    task_claim_locks_reclaim,
    task_claim_subtask_developable,
    task_claim_subtask_testable,
    task_claim_task,
    task_claim_task_bug,
    task_claim_task_review,
    task_claim_task_unplanned,
    task_claim_worker_id,
)
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
from src.project.task.task_retry import task_retry_clear, task_retry_reset_tree, task_retry_take
from src.project.task.task_role import (TASK_ROLE_DEFAULT, TASK_ROLE_TITLE, task_role_of_task,
                                        task_role_planners_only, task_role_project_work_dir,
                                        task_role_shell_live_by_project)
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
from src.project.task.task_log import TASK_LOG_OUTCOME_OK, task_log_write_run
from src.project.task.task_worktree import task_worktree_ensure
from src.project.team.team_session import team_session_restart_role
from src.project.task.task_setting_parallel import (
    TASK_SETTING_PARALLEL_DEFAULT,
    task_setting_parallel_all)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    TASK_SETTING_TIMEOUT_WORKER_JOB,
    task_setting_timeout_get)
from src.worker.project.task_worker import (
    TASK_WORKER_SINGLE_FLIGHT,
    task_worker_enqueue,
    task_worker_flight_acquire,
    task_worker_flight_release,
)

# ── Автосоздание баг-задач из workflow trace ───────────────────────────────────
from src.project.task.task_bug_scan import task_bug_scan_trace
from src.project.task.task_bug_create import (
    task_bug_create as _task_bug_create_impl,
)
from src.project.task.task_bug_dedup import task_bug_dedup_check

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


# ─── Отбор работы: что тик кладёт в очередь ────────────────────────────────────

async def _action_claim(worker: str) -> dict | None:
    """
    Захватить первое подошедшее действие. None — работы нет.

    Планирование отбирается только для живых карточек своего проекта: план пишет
    владелец вкладки (менеджер, разработчик или QA — см. `task_role`) той команды,
    которой задача принадлежит. Захватывать задачу для погасшей карточки нельзя —
    прогон сорвался бы на первом же шаге, а задача ушла бы в `failed`; захватывать
    её карточкой чужого проекта нельзя тем более — оболочка работает в чужом
    каталоге и о задаче ничего не знает.

    Так же отбирается и работа Developer: подзадачу берём только там, где жива
    карточка разработчика своего проекта — он работает в оболочке каталога этого
    проекта. Без живой карточки прогон сорвался бы и сжёг попытку из отведённых.

    Тем же порядком отбирается и круг QA — по живой карточке роли `qa` своего
    проекта. Роль здесь именно `qa`, а не `developer`: проверяющая оболочка обязана
    быть не той, что писала код.

    Разбор плана на подзадачи проектом не ограничен: там оболочки нет вовсе,
    подзадачи создаются прямо в воркере.

    Сверх живости карточек действует предел «Parallel LLM» проекта: проект,
    выбравший свой лимит прогонов, из отбора выпадает целиком — см.
    `_roles_by_project_free`.

    Порядок перебора и есть приоритет ролей: QA → Developer → Manager. Работа,
    начатая раньше, важнее начатой позже: проверить сделанное — значит закрыть
    подзадачу и освободить круг, а взять в планирование новую задачу — значит
    добавить работы к незакрытой. При QA впереди подзадачи идут парами
    dev(1) → qa(1) → dev(2) → qa(2), а не копятся непроверенными.

    Голодания это не создаёт: очередь QA конечна и берётся только из того, что уже
    сделал разработчик, — вычерпав её, тик доходит до разработки, а вычерпав и её,
    до менеджера.
    """
    roles_by_project = _roles_by_project_free(
        await task_role_shell_live_by_project(),
        await task_claim_inflight_by_project(),
        await task_setting_parallel_all())
    for claim in (
        _claim_qa,
        _claim_developer,
        # Починка бага — такая же работа роли, как разработка, поэтому идёт до
        # планирования: закрыть начатое важнее, чем добавить незакрытого. После
        # разработки, а не до неё: подзадача идущего плана ближе к финишу, чем баг,
        # которым ещё не занимались.
        _claim_bugfix,
        # Разбор плана на подзадачи — перед менеджерскими шагами, но после работы
        # ролей: оболочки и похода в LLM тут нет, зато он даёт разработчику работу.
        _claim_plan_split,
        # Пересмотр — первый из менеджерских: на другом конце этого шага человек,
        # который нажал «Обновить план» и ждёт результата.
        _claim_manager_review,
        _claim_manager_plan,
    ):
        action = await claim(worker, roles_by_project)
        if action:
            return action
    return None


def _roles_by_project_free(roles_by_project: dict, inflight: dict, limits: dict) -> dict:
    """
    Убрать из отбора проекты, выбравшие свой предел «Parallel LLM».

    Предел один на проект и считается прогонами агента, а не карточками: карточки
    одного проекта ходят в один аккаунт и один рабочий каталог, и второй прогон
    при пределе 1 перебивал бы первый — агент менеджера получал бы второй промпт
    посреди чужого хода. Пока лимит выбран, задачи проекта просто ждут своей
    очереди, а следующий тик подберёт их сразу, как только прогон завершится.

    Фильтруется именно `roles_by_project`, потому что из него строится условие
    отбора каждого шага — так один фильтр закрывает и планирование, и пересмотр,
    и Developer, и QA. Разбор плана (`_claim_plan_split`) этот словарь не смотрит и
    под предел не попадает: там нет ни оболочки, ни похода в LLM.

    Проекта нет в `limits` — действует `TASK_SETTING_PARALLEL_DEFAULT`.
    """
    free = {}
    for project_id, roles in (roles_by_project or {}).items():
        limit = int(limits.get(project_id, TASK_SETTING_PARALLEL_DEFAULT))
        if int(inflight.get(project_id, 0)) < limit:
            free[project_id] = roles

    return free


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


async def _claim_manager_review(worker: str, roles_by_project) -> dict | None:
    # Багфиксер плана не пишет: тип `bug` принадлежит ему, и без отсева менеджерский
    # шаг забрал бы баг себе (`task_role_planners_only`).
    task = await task_claim_task_review(worker, task_role_planners_only(roles_by_project))
    if not task:
        return None
    role = await task_role_of_task(task)
    await task_report_write(task['id'], f'План отправлен на пересмотр ({_role_title(role)})', ok=None)
    return {'kind': 'manager_review', 'task_id': task['id'], 'revise': True, 'role': role}


async def _claim_manager_plan(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task_unplanned(worker, task_role_planners_only(roles_by_project))
    if not task:
        return None
    # Если план уже есть (есть subtasks), но goals пуст — пересматриваем,
    # а не пишем заново: менеджер удалит subtasks при write-from-scratch.
    _, existing_subtasks = task_plan_parse(task.get('pipeline_plan') or '')
    role = await task_role_of_task(task)
    await task_report_write(task['id'], f'Задача взята в планирование ({_role_title(role)})', ok=None)
    return {'kind': 'manager_plan', 'task_id': task['id'],
            'revise': len(existing_subtasks) > 0, 'role': role}


async def _claim_plan_split(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task('approved', 'processing', worker)
    return {'kind': 'plan_split', 'task_id': task['id']} if task else None


async def _claim_developer(worker: str, roles_by_project) -> dict | None:
    max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)
    subtask = await task_claim_subtask_developable(worker, roles_by_project, max_attempts)
    return {'kind': 'developer', 'subtask_id': subtask['id']} if subtask else None


async def _claim_qa(worker: str, roles_by_project) -> dict | None:
    subtask = await task_claim_subtask_testable(worker, roles_by_project)
    return {'kind': 'qa', 'subtask_id': subtask['id']} if subtask else None


async def _claim_bugfix(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task_bug(worker, roles_by_project)
    if not task:
        return None
    await task_report_write(task['id'], 'Баг взят в работу (Багфиксер)', ok=None)
    return {'kind': 'bugfix', 'task_id': task['id']}


def _action_label(action: dict, job_id: str) -> str:
    target = action.get('task_id') and f" task#{action['task_id']}" or ''
    target = target or (action.get('subtask_id') and f" subtask#{action['subtask_id']}" or '')
    return f"{action.get('kind')}{target} [{job_id[:8]}]"


# ─── Шаги конвейера: что делает воркер ─────────────────────────────────────────

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

    # `env_ok = false` значит «прогона не было» — и причин у этого две. Среда
    # непригодна (сервер подзадачи не поднялся, ветка от сломанного master) —
    # это шаг проверки среды. Или агент не ответил вовсе: таймаут, мёртвая
    # оболочка, ошибка провайдера — это шаги-заглушки. Работы не было ни там, ни
    # там, и жечь попытку не за что: строка идёт в повтор тем же путём, что и
    # сорвавшийся прогон. Лимит повторов не даст крутить это вечно.
    #
    # Формулировка нейтральная именно поэтому. Раньше стояло «среда не готова», и
    # на таймауте это врало: среда была готова, шаг её проверки прошёл за десять
    # секунд, — а человек шёл смотреть каталог и сервер вместо зависшей оболочки.
    if not result.get('env_ok', True):
        return await _retry_subtask(subtask, 'developer', 'planned', TASK_DEVELOPER_ROLE,
                                    work_dir, attempt_no, started,
                                    f"Developer: прогон не состоялся — {result.get('error') or 'сервер подзадачи не отвечает'}")

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

    # `env_ok = false` значит «прогона не было» — и причин у этого две. Среда
    # непригодна (сервер подзадачи не поднялся, ветка от сломанного master) —
    # это шаг проверки среды. Или агент не ответил вовсе: таймаут, мёртвая
    # оболочка, ошибка провайдера — это шаги-заглушки. Работы не было ни там, ни
    # там, и жечь попытку не за что: строка идёт в повтор тем же путём, что и
    # сорвавшийся прогон. Лимит повторов не даст крутить это вечно.
    #
    # Формулировка нейтральная именно поэтому. Раньше стояло «среда не готова», и
    # на таймауте это врало: среда была готова, шаг её проверки прошёл за десять
    # секунд, — а человек шёл смотреть каталог и сервер вместо зависшей оболочки.
    if not result.get('env_ok', True):
        return await _retry_subtask(subtask, 'qa', 'qa_pending', TASK_QA_ROLE,
                                    work_dir, attempt_no, started,
                                    f"QA: прогон не состоялся — {result.get('error') or 'сервер подзадачи не отвечает'}")

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
            f"Багфиксер: прогон не состоялся — {result.get('error') or 'каталог бага не поднялся'}")

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
    # Исход круга определяет `ok`, а не наличие текста в `error`. QA при успешном
    # вердикте всё равно возвращает замечания на будущее («стоит явно пометить»,
    # «можно уточнить формулировку»), и по прежнему правилу закрытая подзадача
    # подписывалась в журнале как затык — а следующий круг прочёл бы это как
    # «работу не приняли» и пошёл переделывать принятое.
    note = str(error or result.get('error') or '').strip()
    if error or not result.get('ok'):
        outcome = note or 'работа не сошлась'
    else:
        outcome = (f'{TASK_LOG_OUTCOME_OK}, с замечаниями: {note}' if note
                   else TASK_LOG_OUTCOME_OK)

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
