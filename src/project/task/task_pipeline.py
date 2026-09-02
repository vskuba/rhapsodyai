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
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow_trace import ai_workflow_trace_runs_stale_close
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE, task_agent_bugfixer_run
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE, task_agent_developer_run
from src.project.task.task_agent_manager import task_agent_manager_plan
from src.project.task.task_agent_qa import TASK_QA_ROLE, task_agent_qa_run
from src.project.task.task_spec import task_spec_write
from src.project.task.task_depend import (task_depend_apply,
                                          task_depend_merge_upstream,
                                          task_depend_plan_links)
from src.project.task.task_branch import (task_branch_of, task_branch_pull,
                                          task_branch_push)
from src.project.task.task_claim import (
    TASK_CLAIM_LOCK_TOUCH_SEC,
    task_claim_inflight_by_project,
    task_claim_inflight_by_role,
    task_claim_lock_touch,
    task_claim_release,
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
    TASK_METADATA_KEY_CONTEXT,
    TASK_METADATA_KEY_MR,
    task_metadata_parse,
    task_metadata_update,
)
from src.project.task.task_plan import (
    task_plan_goals_merge,
    task_plan_goals_normalize,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_merge_request import task_merge_request_open
from src.project.task.task_question import (task_question_parse, task_question_set,
                                            task_question_set_many)
from src.project.task.task_report import task_report_subtasks_summary, task_report_write
from src.project.task.task_retry import task_retry_clear, task_retry_reset_tree, task_retry_take
from src.project.team.team_llm_ping import team_llm_ping_all
from src.project.team.team_session_cleanup import cleanup_inactive_sessions
from src.project.team.team_llm_pool import (team_llm_pool_all, team_llm_pool_assign,
                                            team_llm_pool_cloud_items,
                                            team_llm_pool_free_names, team_llm_pool_get,
                                            team_llm_pool_release, team_llm_pool_shell_cloud,
                                            team_llm_pool_touch)
from src.project.team.team_shell_pool import (team_shell_pool_acquire, team_shell_pool_busy,
                                              team_shell_pool_release, team_shell_pool_tasks,
                                              team_shell_pool_touch)
from src.project.task.task_role import (TASK_ROLE_DEFAULT, TASK_ROLE_MANAGER,
                                        TASK_ROLE_PROJECT_NONE, TASK_ROLE_TITLE,
                                        task_role_of_task, task_role_planners_only,
                                        task_role_project_work_dir,
                                        task_role_shell_live_by_project,
                                        task_role_shell_session,
                                        task_role_shell_sessions_by_project)
from src.project.task.task_revision import task_revision_add
from src.project.task.task_shell_dialog import task_shell_dialog_question
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
    task_state_task_revive,
    task_state_task_get,
    task_state_task_requeue,
    task_state_testing_to_dev,
    task_state_type_to_plan,
)
from src.project.task.task_goal_replan import (task_goal_replan_needed,
                                               task_goal_replan_send)
from src.project.task.task_log import TASK_LOG_OUTCOME_OK, task_log_write_run
from src.project.task.task_metric import task_metric_collect, task_metric_lines_advanced
from src.tool.project.task_worktree_state import task_worktree_state
from src.project.task.task_worktree import (task_worktree_base_branch,
                                            task_worktree_ensure,
                                            task_worktree_git,
                                            task_worktree_path,
                                            task_worktree_prune,
                                            task_worktree_refresh)
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

    # Подметальщики (скан багов, финализация, пинг моделей) идут вне бюджета действий:
    # захватывать им нечего, работу они ищут сами уже в воркере. Считайся они за
    # действие — при max_actions=1 каждый тик уходил бы на скан, а задачи стояли бы в
    # очереди.
    #
    # Пинг ставится не каждый тик: его ключ single-flight живёт пять минут и работает
    # расписанием (`TASK_WORKER_FLIGHT_PERIOD`), а не защитой от дублей.
    for kind in TASK_WORKER_SINGLE_FLIGHT:
        if kind == 'bug_scan' and not BUG_TASK_SCAN_ENABLED:
            continue
        if task_worker_flight_acquire(kind, job_timeout):
            _action_queue(stats, {'kind': kind}, job_timeout)

    # Закрываем строки, по которым делать нечего, до отбора работы. Здесь нет ни
    # оболочки, ни похода в LLM — только запись состояния, — поэтому предел
    # «Parallel LLM» их не касается: иначе подзадача с закрытыми целями ждала бы
    # своей очереди за чужими двадцатиминутными кругами, ничего при этом не
    # собираясь делать. Тем же правилом живёт разбор плана (`_claim_plan_split`).
    # Брошенные трассы закрываем тем же тиком. Функция для этого была, но звалась
    # только при старте сервера, а между рестартами записи копились: прогон умер,
    # запись осталась в `running` навсегда — закрыть её больше некому.
    #
    # Живой прогон не пострадает, пока порог молчания (`TRACE_RUN_STALE_SECONDS`,
    # 9000с) больше самого долгого шага конвейера (реализация, 7200с). Соотношение
    # обязано сохраняться: строка трассы пишется по завершении шага, и работающая
    # реализация молчит все свои два часа. Разойдись они — уборка штампует живой
    # работе «Прерван рестартом сервера»; так и случилось, пока шаг рос до 7200,
    # а порог стоял на 3600.
    with suppress(Exception):
        stats['traces_closed'] = await ai_workflow_trace_runs_stale_close()

    stats['finished'] = await _subtasks_goals_finish()

    # Тем же правилом и по тому же месту — возврат безнадёжных строк менеджеру.
    # Тоже без оболочки и без LLM: одна запись состояния. Строка с единственной
    # целью, круг которой не оставил кода, ждать очереди не должна — ей в этой
    # очереди делать нечего, пока охват не переразложат.
    stats['replanned'] = await _subtasks_replan_stuck()

    # Родитель, уехавший на «Тестирование», а потом получивший новые подзадачи в
    # разработку. Тем же местом и правилом: одна запись состояния, ни оболочки, ни LLM.
    #
    # В тике, а не в месте создания подзадачи, потому что дорог туда несколько —
    # продолжение от QA, доразбиение менеджером, строка, заведённая человеком, — и
    # проверка, повешенная на одну из них, молчала бы для остальных. Возвращаем по
    # одной задаче за тик: их единицы, а тик не должен разрастаться уборкой.
    with suppress(Exception):
        returned = await task_state_testing_to_dev()
        if returned:
            stats['returned_to_dev'] = returned
            await task_report_write(
                returned,
                'Появились подзадачи в разработке — задача снова на вкладке '
                '«Разработка». На проверку вернётся, когда все ветки дойдут до QA')

    # Каталоги, которым больше некому принадлежать. Тем же местом и тем же правилом,
    # что и возврат брошенных захватов: уборка, которую надо помнить, не делается.
    # Ошибку глушим — тик не должен вставать из-за не снявшейся папки.
    with suppress(Exception):
        stats['worktrees_pruned'] = await _worktrees_prune()

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
        # Модель освобождаем здесь, а не внутри круга: у каждого шага выходов
        # десяток — отказ, обрыв, ответ на вопрос, — и освобождение в каждом рано или
        # поздно забыли бы в одном. Здесь точка одна и она в `finally`: круг кончился
        # как угодно, включая исключение, — модель свободна.
        await _llm_release(action)


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

    Сверх живости карточек действует предел одновременных прогонов проекта — размер
    его пула моделей: проект, выбравший лимит, из отбора выпадает целиком, см.
    `_roles_by_project_free` и `_parallel_limits`.

    Порядок перебора и есть приоритет ролей: QA → Developer → Manager. Работа,
    начатая раньше, важнее начатой позже: проверить сделанное — значит закрыть
    подзадачу и освободить круг, а взять в планирование новую задачу — значит
    добавить работы к незакрытой. При QA впереди подзадачи идут парами
    dev(1) → qa(1) → dev(2) → qa(2), а не копятся непроверенными.

    Голодания это не создаёт: очередь QA конечна и берётся только из того, что уже
    сделал разработчик, — вычерпав её, тик доходит до разработки, а вычерпав и её,
    до менеджера.
    """
    # Живые оболочки читаем один раз: их спрашивает и фильтр ролей, и предел проекта —
    # облачная оболочка добавляет к пулу свою запись, и оба ответа обязаны считаться
    # по одному и тому же набору, иначе предел разойдётся с тем, кому его применяют.
    sessions_by_project = await task_role_shell_sessions_by_project()
    # Кто из оболочек занят поимённо и какие из них облачные: по этому видно не только
    # «есть ли свободная», но и «есть ли ей чем работать». Пуловая оболочка без
    # свободной модели круга не начнёт, и отдавать ей ход тика значит отнимать его у
    # облачной, которой работать есть чем.
    cloud_by_project = {project_id: await team_llm_pool_cloud_items(by_role)
                        for project_id, by_role in sessions_by_project.items()}
    free_models = {project_id: bool(await team_llm_pool_free_names(project_id))
                   for project_id in sessions_by_project
                   if await team_llm_pool_get(project_id)}
    roles_by_project = _roles_by_project_free(
        sessions_by_project,
        await task_claim_inflight_by_project(),
        await _parallel_limits(sessions_by_project, cloud_by_project),
        await team_shell_pool_busy(),
        busy_sessions=set(await team_shell_pool_tasks()),
        cloud_by_project=cloud_by_project,
        free_models=free_models)
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


async def _parallel_limits(sessions_by_project: dict | None = None,
                           cloud_by_project: dict | None = None) -> dict[int, int]:
    """
    Сколько прогонов проект ведёт одновременно: `{project_id: предел}`.

    Считается по пулу моделей: работать разом можно ровно настолько, насколько их
    хватает. Селекта «Parallel LLM» на странице команды больше нет — два числа об
    одном и том же непременно разошлись бы, а модель, которой нет, всё равно не
    выдалась бы кругу.

    **Живая облачная оболочка добавляет к пулу свою запись** (`team_llm_pool_cloud_items`):
    она модели не берёт, у неё свой бэкенд, — значит её круг ничьей модели не занимает
    и в предел по моделям попадать не должен. Без этого открытая карточка без
    `--litellm` не работала вовсе: проект с пулом из одной модели вёл один круг, а
    вторая карточка стояла.

    Проект без пула идёт напрямую в облачный Anthropic, и для него остаётся прежняя
    настройка (`task_setting_parallel`) — облачные оболочки её не поднимают. Правило
    намеренно узкое: пул описывает, чем проект работает, и там, где его не заводили,
    число одновременных кругов остаётся решением человека, а не следствием того,
    сколько терминалов открыто.
    """
    limits = dict(await task_setting_parallel_all())
    for project_id, items in (await team_llm_pool_all()).items():
        if not items:
            continue
        # Готовый ответ, если его уже посчитал вызывающий: живые оболочки читают и
        # фильтр ролей, и этот предел, и второй запрос дал бы то же самое.
        cloud = (cloud_by_project or {}).get(project_id)
        if cloud is None:
            cloud = await team_llm_pool_cloud_items((sessions_by_project or {}).get(project_id))
        limits[project_id] = len(items) + len(cloud)

    return limits


def _roles_by_project_free(sessions_by_project: dict, inflight: dict, limits: dict,
                           busy_shells: dict | None = None, busy_sessions: set | None = None,
                           cloud_by_project: dict | None = None,
                           free_models: dict | None = None) -> dict:
    """
    Оставить в отборе роли, которым есть чем работать. `{project_id: [role]}`.

    Три условия, и они про разное.

    **У роли заняты все оболочки — выпадает роль.** В оболочке один агент, и два
    круга в одной не идут параллельно, а дерутся: второй промпт прилетает агенту
    посреди чужого хода. Но оболочек у роли столько, сколько терминалов открыл
    человек, — пока есть свободная, роль берёт следующий круг и ведёт их разом
    (`team_shell_pool`).

    **Свободной оболочке нечем работать — роль тоже выпадает.** Пуловой оболочке нужна
    свободная модель; нет её — круг захватит строку, дойдёт до `_llm_assign`, вернёт
    «ждёт свободной модели» и отдаст строку обратно. Сама по себе такая холостая
    попытка дешева, но тик отдаёт за неё единственный захват: живьём QA каждый тик
    забирал ход, упирался в занятую модель и уходил ни с чем, а свободная облачная
    оболочка разработчика всё это время простаивала, хотя работа для неё была.
    Облачной оболочке модель не нужна — её эта проверка не задевает.

    **Проект выбрал потолок — выпадает проект целиком.** Потолок — размер пула плюс
    живые облачные оболочки (`_parallel_limits`): круг занимает либо модель, либо
    оболочку с собственным бэкендом, и взять работы больше значит поставить её ждать.

    Фильтруется список ролей, потому что из него строится условие отбора каждого
    шага — так один фильтр закрывает и планирование, и пересмотр, и Developer, и QA.
    Разбор плана (`_claim_plan_split`) этот словарь не смотрит и под предел не
    попадает: там нет ни оболочки, ни похода в LLM.

    Проекта нет в `limits` — действует `TASK_SETTING_PARALLEL_DEFAULT`.
    """
    busy_shells = busy_shells or {}
    busy_sessions = busy_sessions or set()
    free = {}
    for project_id, roles in (sessions_by_project or {}).items():
        limit = int(limits.get(project_id, TASK_SETTING_PARALLEL_DEFAULT))
        if int(inflight.get(project_id, 0)) >= limit:
            continue
        busy = busy_shells.get(project_id, {})
        cloud = {item['session_uuid'] for item in (cloud_by_project or {}).get(project_id) or []}
        # Пула у проекта нет — модель никому не выдаётся, и требовать её от оболочки
        # нельзя: она пойдёт штатным бэкендом, как ходила до появления пулов.
        has_model = (free_models or {}).get(project_id, True)

        idle = []
        for role, sessions in roles.items():
            if int(busy.get(role, 0)) >= len(sessions):
                continue
            spare = [uuid for uuid in sessions if uuid not in busy_sessions]
            # `spare` пуст, а счётчик занятых говорит обратное — захват отстал от
            # реестра. Верим счётчику: он и раньше решал этот вопрос один.
            if not spare or has_model or any(uuid in cloud for uuid in spare):
                idle.append(role)
        if idle:
            free[project_id] = idle

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
    planners = task_role_planners_only(roles_by_project)
    task = await task_claim_task_review(worker, planners)
    if not task:
        return None
    role = await _plan_role(task, planners)
    await task_report_write(task['id'], f'План отправлен на пересмотр ({_role_title(role)})', ok=None)
    return {'kind': 'manager_review', 'task_id': task['id'], 'revise': True, 'role': role}


async def _claim_manager_plan(worker: str, roles_by_project) -> dict | None:
    planners = task_role_planners_only(roles_by_project)
    task = await task_claim_task_unplanned(worker, planners)
    if not task:
        return None
    # Если план уже есть (есть subtasks), но goals пуст — пересматриваем,
    # а не пишем заново: менеджер удалит subtasks при write-from-scratch.
    _, existing_subtasks = task_plan_parse(task.get('pipeline_plan') or '')
    role = await _plan_role(task, planners)
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

async def _run_session_sweep(action: dict) -> str | None:
    """
    Погасить и убрать сессии оболочек, которых больше нет.

    Уборка звалась только при регистрации новой оболочки — а её не происходит, пока
    человек не откроет терминал. Между перезапусками мёртвые строки копились и висели
    на `/admin/team` живыми карточками: после обрыва сети их набралось шесть при
    восьми работающих, и команда выглядела так, будто роли отваливаются.

    Здесь, подметальщиком тика, потому что это уборка по времени, а не по событию:
    оболочка умирает молча, и узнать об этом можно только не дождавшись её пинга.

    Порог — час без heartbeat (`TEAM_SESSION_CLEANUP_SILENT_MINUTES`), много больше
    порога свежести карточки: тот решает, как рисовать живую строку при заминке сети,
    а этот — когда списать её совсем.
    """
    result = await cleanup_inactive_sessions()
    closed = int(result.get('silent_closed') or 0)
    deleted = int(result.get('registry_deleted') or 0)
    if not closed and not deleted:
        return None

    return f'сессии: погашено {closed}, удалено {deleted}'


async def _run_llm_ping(action: dict) -> str | None:
    """
    Опросить модели пулов: отвечают ли те, кому конвейер раздаёт круги.

    В воркере, а не в тике: опрос ходит к провайдерам и на медленной локальной модели
    занимает секунды на каждую, а тик обязан укладываться в секунды целиком. Интервал
    даёт ключ single-flight (`TASK_WORKER_FLIGHT_PERIOD`) — раз в пять минут.

    Отдельного события планировщика для этого нет намеренно: Cronicle заводят руками
    на каждой инсталляции, и правило «конвейер не выдаёт мёртвую модель» не должно
    зависеть от того, вспомнил ли человек завести событие на проде.

    Мёртвых из пула не вычёркиваем — их пропускает захват (`team_llm_pool_acquire`).
    Здесь только опрос: решение «кому не давать работу» принимается там, где работа и
    раздаётся, иначе оно разъедется с показом на странице.
    """
    pings = await team_llm_ping_all()
    if not pings:
        return None

    # Только `error`: `unknown` значит «проверить не смогли» (каталог оболочки не
    # смонтирован, ключ не назван) — писать про такую модель «не отвечает» значило бы
    # искать поломку у провайдера, когда она в нашей установке.
    dead = sorted(name for name, ping in pings.items() if ping.get('status') == 'error')

    return f"пинг пула: {len(pings)}, не отвечают {', '.join(dead)}" if dead \
        else f'пинг пула: {len(pings)}, все отвечают'


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
    # Зависимости — сразу после создания строк: в плане они позиционные («вторая
    # ждёт первую»), а связать можно только уже существующие номера. Подзадача,
    # опирающаяся на соседнюю, не уйдёт в работу, пока та не закрыта
    # (`task_depend_ready_sql`); всё остальное идёт параллельно, как и раньше.
    links = task_depend_plan_links(subtasks)
    await task_depend_apply(task['id'], links)

    tail = f', зависимостей {sum(len(v) for v in links.values())}' if links else ''
    await task_report_write(
        task['id'], f'План утверждён и разложен на {created} {_task_plural_sub(created)}{tail}'
                    ' — выполнение началось')
    logger_info(f'[task] task#{task["id"]} -> processing ({created} подзадач{tail})')
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

    # Закрывать нечего — круга не будет вовсе. Цели подзадачи проставляет сам QA,
    # разобрав доказательство (`task_goal_mark`), поэтому все закрытые цели это уже
    # состоявшаяся проверка, а не обещание. Разработчику тут делать нечего: он
    # прочитает журнал, увидит сделанное и ответит «остаток вне моей подзадачи» —
    # потратив на это полный круг в десятки минут. Живьём это стоило #1028
    # нескольких кругов подряд.
    #
    # И QA звать незачем: закрывал цели он же, второй заход по той же фактуре даст
    # тот же ответ. Подзадача закрывается сразу.
    if _goals_all_done(subtask):
        await task_state_subtask_set(subtask['id'], 'done', last_error='',
                                     attempt_count=int(subtask['pipeline_attempt_count']))
        await _subtask_report(subtask, 'все цели закрыты QA — круг не нужен, подзадача готова')
        logger_info(f"[task] subtask#{subtask['id']}: все цели закрыты, круг пропущен -> done")
        return f"subtask#{subtask['id']} developer -> done (все цели закрыты)"

    attempt_no = int(subtask['pipeline_attempt_count']) + 1
    started = time.monotonic()
    work_dir = await task_role_project_work_dir((task or {}).get('project_id'))
    subtask_dir = await _subtask_dir(work_dir, subtask['id'], subtask['parent_id'])

    # Модель на круг — из пула проекта. Свободных нет: работа ждёт очереди, ровно как
    # ждала при прежнем пределе «Parallel LLM», только считается он теперь по размеру
    # пула. Пул пуст — `assign` ничего не захватывает, и роль идёт штатным облачным
    # бэкендом, как до появления пулов.
    # Код предшественников — в ветку подзадачи, до начала работы. Зависимость это про
    # код: ждать закрытия соседа мало, его работа лежит в его ветке, а не в master, и
    # исполнитель увидел бы пустое место там, где рассчитывал на готовое.
    #
    # Конфликт слияния круг не начинает: две подзадачи, поправившие одно место, —
    # ошибка разбиения, и чинит её менеджер, а не разработчик посреди круга.
    merge = await task_depend_merge_upstream(work_dir, subtask['id'])
    if merge.get('conflict'):
        # Конфликт содержимого: две подзадачи правят одно место. Это ошибка разбиения, и
        # чинит её менеджер, а не разработчик посреди круга. Текст git кладём в отчёт —
        # без него человек видит «конфликт» и не знает, где именно.
        await _subtask_report(
            subtask, f"ветка {merge['conflict']} не влилась: конфликт с кодом предшественника — "
                     f"нужно переразбить план. {merge.get('error') or ''}".strip(), ok=False)
        await task_state_subtask_set(subtask['id'], 'blocked',
                                     last_error=f"конфликт слияния с {merge['conflict']}")
        return f"subtask#{subtask['id']} developer -> blocked (конфликт с предшественником)"

    if merge.get('failed'):
        # Слияние не состоялось, но конфликта нет: занят индекс соседним git-ом, каталог
        # не готов, git не уложился в срок. Работы не было, и глушить подзадачу не за
        # что — она возвращается в очередь и пойдёт следующим кругом.
        #
        # Раньше сюда попадал тот же путь, что и у конфликта: подзадачи гасли пачками
        # без единого вызова разработчика, а причину никто не видел — текст ошибки в
        # отчёт не попадал вовсе.
        logger_info(f"[task] subtask#{subtask['id']}: слияние {merge['failed']} не состоялось, "
                    f"круг отложен: {merge.get('error') or ''}")
        return await _wait_resource('subtask', subtask['id'], 'developer',
                                    f"слияния ветки {merge['failed']}")

    shell_session = await _shell_assign(action, task, TASK_DEVELOPER_ROLE)
    if action.get('shell_wait'):
        return await _wait_resource('subtask', subtask['id'], 'developer', 'свободной оболочки')

    if (await _llm_assign(action, task, TASK_DEVELOPER_ROLE)).get('wait'):
        return await _wait_resource('subtask', subtask['id'], 'developer', 'свободной модели')

    # Ветка задачи — в ветку подзадачи, перед каждым кругом. В ней лежит вся принятая
    # соседями работа, и без этого шага исполнитель увидел бы пустое место там, где
    # сосед что-то сделал (`task_branch`). Слияние предшественников ниже остаётся: оно
    # закрывает случай, когда сосед закрыт, но в ветку задачи ещё не влит — так бывает
    # у планов, разобранных до появления этого правила.
    pull = await task_branch_pull(work_dir, int(subtask['id']), int(subtask['parent_id'] or 0),
                                  role=TASK_DEVELOPER_ROLE, session=shell_session)
    if pull.get('conflict'):
        await _subtask_report(
            subtask, f"ветка задачи не влилась в подзадачу: конфликт с общей работой — "
                     f"нужно переразбить план. {pull.get('error') or ''}".strip(), ok=False)
        await task_state_subtask_set(subtask['id'], 'blocked',
                                     last_error='конфликт с веткой задачи')
        return f"subtask#{subtask['id']} developer -> blocked (конфликт с веткой задачи)"

    if not pull.get('ok'):
        return await _wait_resource('subtask', subtask['id'], 'developer',
                                    'слияния ветки задачи')

    try:
        result = await task_agent_developer_run(
            task, subtask, str(subtask.get('pipeline_error') or ''),
            role=TASK_DEVELOPER_ROLE, work_dir=work_dir, subtask_dir=subtask_dir,
            shell_session=shell_session,
            shell_task_prev=int(action.get('shell_task_prev') or 0))
    except Exception as e:
        return await _retry_subtask(subtask, 'developer', 'planned', TASK_DEVELOPER_ROLE,
                                    work_dir, attempt_no, started, f'Developer: {e}',
                                    llm_name=str(action.get('llm') or ''), shell=str(action.get('shell') or ''))

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
                                    f"Developer: прогон не состоялся — {result.get('error') or 'сервер подзадачи не отвечает'}",
                                    llm_name=str(action.get('llm') or ''), shell=str(action.get('shell') or ''))

    await task_retry_clear(subtask['id'])
    await task_state_attempt_log(subtask['id'], attempt_no, 'developer', result, started)
    await _subtask_branch_save(subtask['id'], result)
    await _log_run(subtask['id'], work_dir, result, 'developer', attempt_no,
                   llm_name=str(action.get('llm') or ''))

    if result.get('ok'):
        await task_state_subtask_set(subtask['id'], 'qa_pending', last_error='')
        await _subtask_report(subtask, f'разработка завершена (попытка {attempt_no}), ушла на проверку QA')
        await _task_to_testing(task)
        return f"subtask#{subtask['id']} developer -> qa_pending"

    if await _question_hold(subtask, result, 'developer', attempt_no):
        return f"subtask#{subtask['id']} developer -> blocked (вопрос человеку)"

    # Круг кончился без `ok`. Исходов здесь два, и хоронить их одинаково нельзя.
    #
    # «Не доделал, вот что осталось» — работа шла: агент разобрался, написал код,
    # закоммитил и сам назвал недоделанное. «Провалился» — работы не вышло вовсе.
    # Раньше оба сжигали попытку и на последней уводили строку в `blocked`. Живьём
    # подзадача #5219: три прогона подряд не состоялись (оболочка молчала, попытку
    # они не жгут), а четвёртый отработал честно, сделал пять коммитов и написал
    # «нужен следующий круг: записать миграцию, сделать push и MR» — и этим сжёг
    # последнюю попытку.
    #
    # Различаем по коду в ветке, а не по словам агента: отчёт пишет он сам, и «я
    # почти закончил» стало бы способом крутить круги бесконечно. Причём мало того,
    # что код есть — он остаётся от прошлых кругов; смотрим, **прибавился** ли он
    # (`task_metric_lines_advanced`). Строка, которая топчется на месте, попытки
    # жжёт как раньше и до предела дойдёт.
    error = str(result.get('error') or 'ошибка разработчика')
    max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)

    lines_now = await _lines_changed(work_dir, subtask['id'])
    # Номер круга передаём, чтобы его собственный замер не попал в сравнение:
    # `_log_run` выше уже записал его, и без этого сравнивали бы с самим собой.
    advanced = await task_metric_lines_advanced(subtask['id'], lines_now or 0, attempt_no)

    state = await task_state_subtask_fail(subtask['id'], attempt_no, error, max_attempts,
                                          worked=advanced)
    if advanced and attempt_no >= max_attempts:
        await _subtask_report(
            subtask,
            f'круг {attempt_no} не закончил работу, но код в ветке прибавился '
            f'({lines_now} строк) — даём ещё круг вместо остановки: {error}',
            ok=False)
    else:
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

    # Проверять нечего: все цели уже закрыты, и закрывал их QA — своим же
    # инструментом `task_goal_mark`, разобрав доказательство по каждой. Второй заход
    # по той же фактуре даст тот же ответ, поэтому подзадача закрывается сразу.
    # Та же проверка стоит и на входе разработчика: до QA такая строка вообще не
    # доходит, а здесь она остаётся для тех, кто попал в очередь раньше правки.
    if _goals_all_done(subtask):
        await task_state_subtask_set(subtask['id'], 'done', last_error='',
                                     attempt_count=int(subtask['pipeline_attempt_count']))
        await _subtask_report(subtask, 'все цели закрыты QA — проверять нечего, подзадача готова')
        logger_info(f"[task] subtask#{subtask['id']}: все цели закрыты, круг QA пропущен -> done")
        return f"subtask#{subtask['id']} qa -> done (все цели закрыты)"

    attempt_no = int(subtask['pipeline_attempt_count']) + 1
    started = time.monotonic()
    work_dir = await task_role_project_work_dir((task or {}).get('project_id'))
    subtask_dir = await _subtask_dir(work_dir, subtask['id'], subtask['parent_id'])

    # Проверять нечего и по второй причине: разработчик не написал кода. В ветке нет
    # ни коммитов, ни незакоммиченных правок — так бывает, когда работа подзадачи уже
    # лежит в master: её сделала соседняя подзадача, прошлый круг или человек руками.
    #
    # Смотрим до запуска агента, а не спрашиваем его. Три команды git детерминированы
    # и стоят секунды, а круг QA — это оболочка, двадцать минут и попытка. Раньше их
    # тратили впустую: QA видел пустой `master..HEAD`, читал это как «работа не
    # сделана» и возвращал подзадачу разработчику, которому нечего было делать.
    #
    # Состояние своё, а не `done`: «проверено и принято» и «проверять было нечего» —
    # разные факты, и склеив их, мы потеряли бы второй.
    #
    # Каталог обязан существовать. `done_has = no` инструмент отдаёт на два разных
    # случая — «ветка чиста» и «каталога нет вовсе», — а это не одно и то же:
    # пропавший каталог значит сломанную среду, и закрыть по нему подзадачу как
    # «кода нет» означало бы выдать поломку стенда за законный итог работы. Такую
    # строку отдаём обычному кругу: он упрётся в проверку среды и уйдёт в повтор.
    state = await task_worktree_state(subtask['id'], work_dir=work_dir)
    worktree_dir = str(state.get('done_dir') or '')
    if str(state.get('done_has') or '') == 'no' and worktree_dir and os.path.isdir(worktree_dir):
        await task_state_subtask_set(subtask['id'], 'no_code_for_testing', last_error='',
                                     attempt_count=int(subtask['pipeline_attempt_count']))
        await _subtask_report(
            subtask, 'кода в ветке нет — проверять нечего, круг QA не запускался')
        logger_info(f"[task] subtask#{subtask['id']}: пустая ветка -> no_code_for_testing")
        return f"subtask#{subtask['id']} qa -> no_code_for_testing (кода нет)"

    shell_session = await _shell_assign(action, task, TASK_QA_ROLE)
    if action.get('shell_wait'):
        return await _wait_resource('subtask', subtask['id'], 'qa', 'свободной оболочки')

    if (await _llm_assign(action, task, TASK_QA_ROLE)).get('wait'):
        return await _wait_resource('subtask', subtask['id'], 'qa', 'свободной модели')

    try:
        result = await task_agent_qa_run(
            task, subtask, str(subtask.get('pipeline_error') or ''),
            role=TASK_QA_ROLE, work_dir=work_dir, subtask_dir=subtask_dir,
            shell_session=shell_session)
    except Exception as e:
        return await _retry_subtask(subtask, 'qa', 'qa_pending', TASK_QA_ROLE,
                                    work_dir, attempt_no, started, f'QA: {e}',
                                    llm_name=str(action.get('llm') or ''), shell=str(action.get('shell') or ''))

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
                                    f"QA: прогон не состоялся — {result.get('error') or 'сервер подзадачи не отвечает'}",
                                    llm_name=str(action.get('llm') or ''), shell=str(action.get('shell') or ''))

    await task_retry_clear(subtask['id'])
    await task_state_attempt_log(subtask['id'], attempt_no, 'qa', result, started)
    await _log_run(subtask['id'], work_dir, result, 'qa', attempt_no,
                   llm_name=str(action.get('llm') or ''))

    if result.get('ok'):
        await task_state_subtask_set(subtask['id'], 'done', last_error='', attempt_count=attempt_no)
        # Цели подзадачи здесь не трогаем: галочки уже проставил сам QA в ходе
        # прогона — по одной, каждую своим ответом (`src/tool/project/task_goal.py`).
        # Закрыть их отсюда значило бы отметить проверенным и то, что он не подтвердил.
        #
        # Принятая работа уезжает в ветку задачи: следующая подзадача начнёт круг,
        # уже видя её. Только принятую — непринятую ещё будут переделывать, и её код
        # в общей ветке мешал бы соседям (`task_branch`).
        #
        # Неудачу слияния подзадаче в вину не ставим и `done` не отменяем: работа
        # проверена и принята, а не сошедшиеся ветки — это разговор с человеком, и он
        # уже записан в отчёт. Иначе принятая подзадача возвращалась бы в работу из-за
        # чужого кода.
        push = await task_branch_push(work_dir, int(subtask['id']),
                                      int(subtask['parent_id'] or 0),
                                      role=TASK_QA_ROLE, session=shell_session)
        if not push.get('ok'):
            await _subtask_report(
                subtask, f"проверку QA прошла, но в ветку задачи не влилась: "
                         f"{push.get('error') or 'слияние не состоялось'}", ok=None)
        await _subtask_report(subtask, 'проверку QA прошла, подзадача готова')
        return f"subtask#{subtask['id']} qa -> done"

    if await _question_hold(subtask, result, 'qa', attempt_no):
        return f"subtask#{subtask['id']} qa -> blocked (вопрос человеку)"

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

    shell_session = await _shell_assign(action, task, TASK_BUGFIXER_ROLE)
    if action.get('shell_wait'):
        return await _wait_resource('task', task['id'], 'bugfix', 'свободной оболочки')

    if (await _llm_assign(action, task, TASK_BUGFIXER_ROLE)).get('wait'):
        return await _wait_resource('task', task['id'], 'bugfix', 'свободной модели')

    try:
        result = await task_agent_bugfixer_run(
            task, role=TASK_BUGFIXER_ROLE, work_dir=work_dir, task_dir=task_dir,
            shell_session=shell_session)
    except Exception as e:
        return await _retry_task(task, 'bugfix', 'new', TASK_BUGFIXER_ROLE,
                                 work_dir, f'Багфиксер: {e}', shell=str(action.get('shell') or ''))

    # Среда не пригодна для работы (каталог бага не поднялся, ветка выкачена от
    # сломанного master) — работы не было, и вести баг в `blocked` не за что: его никто
    # не смотрел. Возвращаем строку в очередь тем же путём, что и сорвавшийся прогон;
    # лимит повторов не даст крутить это вечно.
    if not result.get('env_ok', True):
        return await _retry_task(
            task, 'bugfix', 'new', TASK_BUGFIXER_ROLE, work_dir,
            f"Багфиксер: прогон не состоялся — {result.get('error') or 'каталог бага не поднялся'}", shell=str(action.get('shell') or ''))

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
    """
    Свести состояние задачи с состоянием её подзадач — в обе стороны.

    Сперва возврат, потом закрытие, и порядок не случаен. Закрытие смотрит на
    мгновенное состояние детей: одного упавшего хватает, чтобы задача стала `failed`.
    Ребёнок оттуда возвращается — его перезапускает человек, оживляет ответ на
    вопрос, забирает следующий круг, — и задача обязана вернуться вместе с ним.
    Идя вторым, возврат разбирал бы то, что закрытие только что поставило в этом же
    тике; идя первым, он чинит хвост прошлых тиков, а закрытие работает по свежему.
    """
    revived = await task_state_task_revive()
    if revived:
        task_id, state = revived
        summary = await task_report_subtasks_summary(task_id)
        await task_report_write(
            task_id,
            f'Задача снова в работе: заблокированных подзадач не осталось ({summary})')
        return f'task#{task_id} failed -> {state}'

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
        # Merge request заводится здесь и только здесь: это первый момент, когда работа
        # задачи полна — QA закрыл последнюю подзадачу. Роли к нему отношения не имеют,
        # это функциональная операция над готовым результатом (`task_merge_request`).
        #
        # Итог всегда идёт в отчёт, удачный и нет: не заведённый merge request человек
        # иначе обнаружит, только не найдя его на GitHub. Конфликт тоже сюда — его
        # разбирает человек, и узнать о нём он должен на странице задачи.
        await _merge_request_open(task_id)
    else:
        # Не через `task_state_task_fail`: та ставит состояние сама, а его уже
        # выставила финализация — второй UPDATE только затёр бы блокировки.
        await task_report_write(
            task_id, f'Задача завершена со сбоем: часть подзадач заблокирована ({summary})', ok=False)
    return f"task#{task_id} -> {final}"


async def _merge_request_open(task_id: int) -> None:
    """
    Завести merge request по закрытой задаче и записать итог в её отчёт.

    Отдельной функцией, а не строкой в `_run_finalize`: там разбирается состояние
    задачи, а здесь — работа с чужим сервисом, у которой свои исходы. Смешав их, мы
    получили бы шаг, где половина кода про GitHub.

    Сбой не поднимаем наверх: задача уже принята, и merge request её судьбы не меняет.
    В отчёт он попадает в любом случае — по нему человек видит, свести ветки ему самому
    или ссылка уже есть.
    """
    project_id = int((await task_state_task_get(int(task_id)) or {}).get('project_id') or 0)
    work_dir = await task_role_project_work_dir(project_id)
    if not work_dir:
        return

    result = await task_merge_request_open(int(task_id), work_dir)
    await task_report_write(task_id, result['message'], ok=result['ok'] or None)
    logger_info(f"[task] task#{task_id}: {result['message']}")


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

    # Каталог подтягиваем к master перед разведкой. Он режется один раз и дальше
    # стоит: для подзадачи это верно, её работа привязана к состоянию среза, а для
    # менеджера нет — он планирует по коду, и вчерашний срез даёт план, который
    # разошёлся с действительностью ещё до начала работы. Живьём каталог задачи
    # #4798 отстал от master на два коммита за сутки.
    if task_dir:
        logger_info(f"[task] task#{task['id']} каталог менеджера: "
                    f'{await task_worktree_refresh(work_dir, int(task["id"]))}')

    # Модель на круг — из пула проекта, тем же порядком, что у разработчика и QA.
    # Планирование ходит в ту же оболочку и стоит тех же токенов: оставь мы менеджера
    # без выдачи, он молча работал бы облачным Anthropic мимо пула — при том, что
    # оболочку подняли с `--litellm` и она ждёт модель именно отсюда.
    shell_session = await _shell_assign(action, task, role)
    if action.get('shell_wait'):
        return await _wait_resource('task', task['id'], label, 'свободной оболочки')

    if (await _llm_assign(action, task, role)).get('wait'):
        return await _wait_resource('task', task['id'], label, 'свободной модели')

    try:
        result = await task_agent_manager_plan(task, revise=revise, role=role,
                                               work_dir=work_dir, task_dir=task_dir,
                                               shell_session=shell_session)
    except Exception as e:
        return await _retry_task(task, label, state_retry, role, work_dir, f'Manager: {e}',
                                 shell=str(action.get('shell') or ''))

    subtasks = result.get('subtasks') or []
    if not subtasks:
        return await _retry_task(task, label, state_retry, role, work_dir,
                                 'Manager не вернул ни одной подзадачи', shell=str(action.get('shell') or ''))

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
        # `work_dir` — чтобы пути легли от корня репозитория: исполнитель работает в
        # своей выкладке, и абсолютный путь увёл бы его в чужой каталог (#4799).
        task_plan_serialize(plan_text, subtasks, goals, repo_dir=work_dir),
        goals_json=goals_json,
    )
    # Ревизию пишем здесь, а не внутри `task_state_plan_save`: там один UPDATE без
    # побочных таблиц, и спрятанная в нём запись истории читалась бы как сюрприз.
    # В ревизию идут те же слитые цели, что легли в задачу, — иначе восстановление
    # вернуло бы только предложенное агентом, потеряв цели человека.
    await task_revision_add(task['id'], plan_text, task_plan_goals_normalize(goals_json),
                            subtasks, author_kind='manager')

    # Вопрос менеджера — развилка, которую решает заказчик, а не код: разведка
    # упёрлась в неё и составила план по своему допущению. Кладём вопрос на задачу
    # рядом с планом, там же, где его задаёт роль по подзадаче, — человек ответит
    # тем же попапом (`task_question`).
    #
    # Круг за вопрос не жжём и работу не останавливаем: у планирования человеческий
    # шаг и так впереди — утверждение плана. Останавливать задачу ради вопроса
    # значило бы завести второе ожидание человека перед первым.
    question = result.get('question') or {}
    if question:
        await task_question_set(task['id'], question, role)

    # Развилки разведки — те, что менеджер не смог закрыть по коду. Раньше они не
    # доезжали никуда: перевод разведки в машинный вид забирал два поля, `task_done` и
    # `task_size`, а вопросы оставались текстом в контексте агента и человек их не
    # видел никогда. Единственной дверью был ключ `question` в плане — ровно один
    # вопрос и только если менеджер о нём вспомнит.
    #
    # Задачу они, как и одиночный вопрос, не держат: план написан по допущению,
    # допущение названо вслух, ответ придёт к пересмотру.
    questions = result.get('questions') or []
    if questions:
        taken = await task_question_set_many(task['id'], questions, role)
        logger_info(f"[task] task#{task['id']}: разведка оставила {taken} вопрос(ов) человеку")

    # Пометка «в разработку» — заранее данное человеком согласие: план готов, ждать
    # ещё и нажатия «Утвердить» не за чем. Задача сама меняет тип на `dev` и уходит
    # в `approved`, дальше её подберёт разбор плана на подзадачи.
    #
    # Заданный вопрос эту пометку перевешивает: согласие давали на план вообще, а не
    # на план, у которого менеджер спрашивает про развилку. Утвердить его молча
    # значит принять допущение менеджера за решение человека.
    to_dev = not question and await task_state_plan_to_development(task['id'])
    state = 'approved' if to_dev else 'plan_approval'
    tail  = ('. Задача помечена «в разработку» — план утверждён без человека, '
             'тип сменён на «Разработка»') if to_dev else '. Ждёт утверждения человеком'
    if question:
        tail += '; менеджер задал вопрос'

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
                      work_dir: str, error: str, shell: str = '') -> str:
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
    if await _dialog_hold(task, role, error, parent_id=None, back_state=state_retry):
        return f"task#{task['id']} {label} -> вопрос человеку (диалог оболочки)"

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
    # Перезапускаем **свою** оболочку, а не самую свежую у роли. Оболочек у роли
    # столько, сколько терминалов открыл человек, и маркер, ушедший соседу, сносит
    # его ход посреди работы — тот получает «Оболочка перезапущена, ответ на
    # сообщение потерян». Живьём это выходило петлёй: срыв перезапускал соседа,
    # сосед срывался, перезапускал следующего, и подзадача #5238 сожгла три повтора
    # подряд, не сделав ни одной проверки. Адрес известен — его дал захват
    # (`_shell_assign`); пуст он только там, где оболочки у роли не нашлось вовсе,
    # и тогда работает прежний путь по роли и каталогу.
    await team_session_restart_role(role, work_dir, session_uuid=shell)
    await task_state_task_requeue(task['id'], state_retry, error)
    return f"task#{task['id']} {label} -> retry {retry['count']}/{retry['max']}"


async def _retry_subtask(subtask: dict, step: str, state_retry: str, role: str, work_dir: str,
                         attempt_no: int, started: float, error: str,
                         llm_name: str = '', shell: str = '') -> str:
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
    # Строку могли закрыть, пока прогон висел: круг отваливается по таймауту через
    # двадцать минут, и за это время подзадачу закрывает пропуск по целям или
    # человек. Возвращать её в очередь после этого значит воскрешать работу,
    # которой нет. Поймано живьём на #1028.
    fresh = await task_state_subtask_get(int(subtask['id']))
    if (fresh or {}).get('pipeline_state') == 'done':
        logger_info(f"[task] subtask#{subtask['id']}: круг {role} опоздал, строка уже закрыта")
        return f"subtask#{subtask['id']} {step} -> опоздал, строка закрыта"

    result = {'ok': False, 'output': '', 'error': error}
    await task_state_attempt_log(subtask['id'], attempt_no, step, result, started)
    # Ради этого журнал и заводили: ответа нет, но шаги, что успели пройти, в
    # трассе остались — следующий круг начнёт с них, а не с чистого листа.
    await _log_run(subtask['id'], work_dir, result, role, attempt_no, error, llm_name)

    if await _dialog_hold(subtask, role, error, parent_id=subtask.get('parent_id'),
                          back_state=state_retry):
        return f"subtask#{subtask['id']} {step} -> вопрос человеку (диалог оболочки)"

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
    # Перезапускаем **свою** оболочку, а не самую свежую у роли. Оболочек у роли
    # столько, сколько терминалов открыл человек, и маркер, ушедший соседу, сносит
    # его ход посреди работы — тот получает «Оболочка перезапущена, ответ на
    # сообщение потерян». Живьём это выходило петлёй: срыв перезапускал соседа,
    # сосед срывался, перезапускал следующего, и подзадача #5238 сожгла три повтора
    # подряд, не сделав ни одной проверки. Адрес известен — его дал захват
    # (`_shell_assign`); пуст он только там, где оболочки у роли не нашлось вовсе,
    # и тогда работает прежний путь по роли и каталогу.
    await team_session_restart_role(role, work_dir, session_uuid=shell)
    await task_state_subtask_set(subtask['id'], state_retry, unless_done=True)
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


async def _subtasks_goals_finish() -> int:
    """
    Закрыть подзадачи, у которых все цели уже проставлены QA.

    Отметку «цель закрыта» ставит QA, разобрав доказательство, поэтому все
    закрытые цели — состоявшаяся проверка. Круг такой строке не нужен ни от
    разработчика, ни от QA; та же проверка стоит и на входе обоих раннеров, но
    туда строка попадает только выиграв очередь, а очередь у проекта одна на
    всех и занята чужими кругами по двадцать минут.

    Берём только незанятые строки в состояниях, из которых конвейер и так взял
    бы их в работу. Идущий круг не трогаем: его итог придёт своим путём, а
    закрытую строку он уже не воскресит (`unless_done`).

    Returns: сколько строк закрыли.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, parent_id, title, goals FROM project_task "
            " WHERE parent_id IS NOT NULL AND pipeline_locked_at IS NULL "
            "   AND pipeline_state IN ('planned', 'failed_qa', 'qa_pending')")
        rows = await db.fetchall()

    closed = 0
    for row in rows:
        if not _goals_all_done(row):
            continue
        await task_state_subtask_set(row['id'], 'done', last_error='')
        await _subtask_report(row, 'все цели закрыты QA — круг не нужен, подзадача готова')
        logger_info(f"[task] subtask#{row['id']}: все цели закрыты, закрыта тиком")
        closed += 1

    return closed


async def _worktrees_prune() -> int:
    """
    Снять каталоги подзадач, которым больше некому принадлежать. Returns: снятых.

    Каталоги убираются в двух штатных местах — при удалении задачи и после слияния
    кнопкой. Любой шаг в сторону оставляет папку: задачу удалили запросом мимо ручки,
    ветку влили руками, снятие отказало из-за правок и никто не вернулся. Живьём на
    рабочей установке скопилось пять таких, три из них — от задач, которых уже нет:
    по списку каталогов стало не видно, что в работе.

    Решает, что снимать, `task_worktree_prune`: строки задачи нет либо задача
    закрыта и её ветка целиком в главной. Ветку не трогаем никогда — по ней работает
    и просмотр диффа, и кнопка слияния, так что снятый каталог ничего не отнимает.

    Ходим по проектам с известным каталогом: у задач без проекта своего чекаута нет.
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, work_dir FROM project WHERE COALESCE(work_dir, '') <> ''")
        projects = await db.fetchall() or []
        await db.execute('SELECT id, project_id, pipeline_state FROM project_task')
        tasks = await db.fetchall() or []

    by_project: dict[int, dict] = {}
    for task in tasks:
        by_project.setdefault(int(task.get('project_id') or 0), {})[int(task['id'])] = \
            task.get('pipeline_state')

    total = 0
    for project in projects:
        result = await task_worktree_prune(str(project['work_dir']),
                                           by_project.get(int(project['id']), {}))
        total += len(result.get('removed') or [])

    return total


async def _subtasks_replan_stuck() -> int:
    """
    Вернуть менеджеру строки, которые встали, а работы не дали.

    Три условия разом (`task_goal_replan_needed`): строка встала, цель ровно одна
    и круг не оставил кода. Спрашивать тут нечего — раздробить единственную цель
    нечем, а повтор с тем же охватом кончится тем же. Значит, ошиблось не
    исполнение, а планирование, и правильный ход один: пусть менеджер разложит
    строку на подзадачи следующего уровня.

    Делаем сами, без вопроса человеку, потому что выбор здесь не выбор: человек
    видит ровно то же, что и мы, и ответить может только это же. Второй такой же
    тупик подряд уже показываем вопросом — пометка `replanned` одноразовая.

    Здесь, в тике, а не в конце круга: круг мог и не состояться вовсе (оболочка
    молчала), а строка всё равно стоит и ждёт решения.

    Returns: сколько строк вернули на планирование.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, parent_id, title, goals, metadata, pipeline_state FROM project_task "
            " WHERE parent_id IS NOT NULL AND pipeline_locked_at IS NULL "
            "   AND pipeline_state IN ('failed_qa', 'blocked')")
        rows = await db.fetchall() or []

    sent = 0
    for row in rows:
        row = dict(row)
        # Каталог свой у каждой строки: подзадачи разных задач живут в разных
        # проектах, и один каталог на всех давал бы чужой ответ.
        work_dir = await task_role_project_work_dir(row.get('project_id'))
        changed = await _lines_changed(work_dir, row['id'])
        if changed is None:
            # Не посчитали — не знаем, была ли работа. Отправлять на переразбиение
            # вслепую нельзя: так теряется сделанное.
            logger_info(f"[task] subtask#{row['id']}: правки не посчитаны, переразбиение пропущено")
            continue

        goals = task_plan_goals_normalize(row.get('goals'))
        if not task_goal_replan_needed(row, goals, changed):
            continue

        result = await task_goal_replan_send(row)
        if not result.get('ok'):
            continue

        await _subtask_report(
            row, 'круг не оставил кода, а цель одна — дробить нечего. Возвращена менеджеру '
                 'на разбиение: охват задан неподъёмный', ok=None)
        sent += 1

    return sent


def _goals_all_done(subtask: dict) -> bool:
    """
    У подзадачи есть цели и все они закрыты.

    Подзадача без целей сюда не попадает: пустой список означает не «всё
    сделано», а «принимать не по чему», и пропускать по нему разработку значило
    бы отдать QA пустую строку и закрыть её ни за что.
    """
    goals = task_plan_goals_normalize(subtask.get('goals'))

    return bool(goals) and all(goal.get('done') for goal in goals)


async def _question_hold(subtask: dict, result: dict, role: str, attempt_no: int) -> bool:
    """
    Роль спросила человека — придержать подзадачу до ответа. Вопроса нет — False.

    Круг за вопрос не жжём и `task_state_subtask_fail` не зовём: работа встала не
    оттого, что агент не справился, а оттого, что дальше без решения нельзя, и
    следующие два круга упёрлись бы в ту же развилку. Счётчик попыток остаётся
    прежним — `task_state_subtask_set` без `attempt_count` его не трогает.

    Состояние всё равно `blocked`: его смысл — «нужен человек», и это ровно тот
    случай. Отличает вопрос от исчерпанных попыток не состояние, а сам вопрос в
    мешке — по нему страница задач и рисует кнопку с ответами.

    Вопрос смотрим только на несошедшемся круге. Роль, которая доделала работу и
    всё-таки спросила, спрашивает уже задним числом: придержать за это готовую
    подзадачу значило бы наказать за любознательность.
    """
    question = result.get('question')
    if not question or result.get('ok'):
        return False

    await task_question_set(subtask['id'], question, role)
    text = str(question.get('text') or '').strip()
    await task_state_subtask_set(subtask['id'], 'blocked', last_error=f'Вопрос человеку: {text}')
    await _subtask_report(subtask, f'{_role_title(role)} задал вопрос (попытка {attempt_no} не засчитана): {text}',
                          ok=False, blocked=True)
    logger_info(f"[task] subtask#{subtask['id']} -> blocked, вопрос от {role}: {text[:120]}")

    return True


async def _log_run(task_id: int, work_dir: str, result: dict, role: str,
                   attempt_no: int, error: str = '', llm_name: str = '') -> None:
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

    with suppress(Exception):
        await _metric_collect(task_id, work_dir, result, role, attempt_no, llm_name)


async def _metric_collect(task_id: int, work_dir: str, result: dict,
                          role: str, attempt_no: int, llm_name: str = '') -> None:
    """
    Записать замеры круга: объём контекста против времени, токенов и правок.

    Здесь, а не в самих агентных модулях, по той же причине, что и журнал: это
    единственное место, куда сходятся все три роли с уже готовым результатом и
    номером круга.

    Строки контекста берём из мешка строки — это оценка менеджера при разбиении,
    та самая, по которой решали дробить. Изменённый код считаем по ветке
    подзадачи: сколько круг реально написал, видно только там.

    Название задачи кладём копией: замер задачу переживает (`project_task_metric`
    без FK), а по одному номеру удалённую строку в отчёте не прочесть.
    """
    row = await task_state_subtask_get(int(task_id)) or {}
    meta = task_metadata_parse(row.get('metadata'))

    await task_metric_collect(
        task_id=int(task_id),
        parent_id=row.get('parent_id'),
        role=role,
        attempt_no=attempt_no,
        session_uuid=str(result.get('session_uuid') or ''),
        context_lines=int(meta.get(TASK_METADATA_KEY_CONTEXT) or 0),
        task_title=str(row.get('title') or ''),
        # Не посчитали — пишем ноль: в замерах это поле справочное, и пустое
        # значение там честнее выдумки. Решение о переразбиении принимается
        # не здесь, и `None` туда не попадёт.
        lines_changed=await _lines_changed(work_dir, task_id) or 0,
        # Модель круга — из захвата (`_llm_assign`). По ней замеры читаются в разрезе
        # моделей: какая быстрее, какая чаще срывается. Пусто — пул проекта пуст, и
        # круг шёл облачным бэкендом.
        llm_name=llm_name,
    )


async def _lines_changed(work_dir: str, task_id: int) -> int | None:
    """
    Сколько строк кода в ветке подзадачи отличается от главной. Не выяснить — 0.

    Считаем по ветке целиком, а не по одному кругу: круг мог доделывать начатое
    прошлым, и разделить их вклад нечем — коммиты не подписаны номером круга.
    Поэтому в замер идёт накопленный итог, и складывать эти числа по кругам
    нельзя (в таблице оно и стоит один раз на круг, а не на каждый шаг).

    **`None` — не посчитали, `0` — посчитали и работы нет.** Разница
    принципиальная: по этому числу решают, вернуть ли строку менеджеру, и
    молчаливый ноль от ненайденного каталога отправлял бы на переразбиение
    сделанную работу. Живьём: подзадача #1626 с готовым коммитом на 18 строк
    уехала к менеджеру, потому что каталог не нашёлся и ноль сошёл за факт.
    """
    directory = task_worktree_path(work_dir, task_id)
    if not directory or not os.path.isdir(directory):
        return None

    base = await task_worktree_base_branch(directory)
    code, out = await task_worktree_git(directory, 'diff', '--numstat', f'{base}...HEAD')
    if code:
        return None

    total = 0
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            total += int(parts[0]) + int(parts[1])

    return total


async def _subtask_dir(work_dir: str, subtask_id: int, parent_id: int = 0) -> str:
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
        # Отрез от ветки задачи, а не от главной: вся принятая работа соседей уже
        # там (`task_branch`). Задачи нет (менеджерская выкладка, баг) — прежний
        # путь, от главной.
        path = await task_worktree_ensure(work_dir, subtask_id,
                                          base_branch=await task_branch_of(parent_id))
        # Спецификация ложится рядом с журналом, в тот же каталог: её читает агент, а
        # он живёт в каталоге и читает файлы, а не таблицы. Перезаписываем на каждом
        # круге — план и зависимости меняются пересмотром, и вчерашний документ увёл
        # бы исполнителя по старому плану.
        await task_spec_write(work_dir, subtask_id)

        return path
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

    **Тем же ударом подтверждаются захваты оболочки и модели.** Круг держит три вещи —
    строку задачи, оболочку и модель, — и умирают они вместе с ним. Раньше первую
    подновляли, а две другие снимал только `finally`, которого у убитого job'а не
    бывает: захват висел до протухания, а срок его был два часа. Живьём круг, погибший
    при перезапуске воркера, час держал оболочку и единственную модель проекта —
    страница показывала работу, которой не было, а соседняя роль голодала. Теперь
    подтверждение общее, и срок протухания короткий (`TEAM_SHELL_POOL_STALE_SECONDS`).

    Ограничены сроком job: если процесс завис, но не умер, подновление
    прекращается, и дальше работает прежняя страховка по `timeout_task_lock`.
    Отказ `task_claim_lock_touch` — блокировку уже сняли (реклейм, ручной повтор,
    человек на странице задач); тогда просто уходим, чужую метку не ставим — ни на
    строку, ни на оболочку с моделью: круг уже не наш.

    **Заминку базы отказом не считаем.** «Сняли блокировку» — это `False`, а не
    исключение: на исключении удар сердца просто пропускаем и бьём снова через срок.
    Разница дорогая с обеих сторон. Прекрати мы биться из-за одного сбойного запроса —
    круг остался бы без подтверждений и через `TEAM_SHELL_POOL_STALE_SECONDS` потерял бы
    оболочку и модель прямо во время работы. А не поймай мы исключение вовсе — оно
    всплыло бы из этой задачи в `finally` вызывающего (`await hold`) и подменило бы собой
    результат уже сделанного круга.
    """
    row_id = int(action.get('task_id') or action.get('subtask_id') or 0)
    if not row_id:
        return

    deadline = time.monotonic() + await task_setting_timeout_get(TASK_SETTING_TIMEOUT_WORKER_JOB)
    while time.monotonic() < deadline:
        await asyncio.sleep(TASK_CLAIM_LOCK_TOUCH_SEC)
        try:
            if not await task_claim_lock_touch(row_id):
                return
        except Exception as e:
            logger_info(f'[task] удар сердца строки #{row_id} не прошёл, повторим: {e}')
            continue
        await _resources_touch(action)


async def _dialog_hold(row: dict, role: str, error: str, parent_id, back_state: str) -> bool:
    """
    Оболочка встала на вопросе Claude Code: спросить человека вместо повтора.

    Повтор здесь бессмыслен и вреден. Повтор лечит случайный срыв, а диалог —
    не случайность: пока на него не ответят, хода не будет, и следующий круг
    упрётся туда же. Хуже того, повтор идёт с перезапуском оболочки, а перезапуск
    сносит и сам диалог, и ход за ним. Живьём: планирование #1027 потеряло так
    четыре круга и час.

    Поэтому круг не жжём (`task_retry_take` не зовём вовсе), оболочку не трогаем,
    а вопрос кладём на строку — тем же механизмом, каким его задают роли.

    **Строку при этом обязательно останавливаем.** Оставить её в переходном
    состоянии нельзя: блокировку перестанет обновлять закончившийся job,
    `task_claim_locks_reclaim()` через таймаут вернёт строку в отбор, и круг
    пойдёт заново — мимо всего, ради чего мы его придержали. Состояние берём то
    же, что у вопроса роли (`_question_hold`): подзадача — `blocked`, задача —
    `failed`. Смысл у обоих один, «нужен человек», а отличает вопрос от
    исчерпанных попыток не состояние, а сам вопрос в мешке.

    `back_state` — куда вернуть строку, когда человек ответит. Помним его здесь,
    потому что только здесь он известен: у планирования это `new`, у пересмотра
    плана — `reviewing`, и перепутать их значит переписать план вместо правки.

    Returns: `True` — вопрос задан, вызывающему больше делать нечего. `False` —
        отказ обычный, повторяем как раньше.
    """
    dialog = task_shell_dialog_question(error, _role_title(role))
    if not dialog:
        return False

    row_id = int(row['id'])
    question = {**task_question_parse({'question': dialog}), 'dialog': True,
                'back_state': str(back_state or '')}
    await task_question_set(row_id, question, role)

    text = f'Оболочка {_role_title(role)} ждёт ответа на вопрос Claude Code'
    if parent_id:
        await task_state_subtask_set(row_id, 'blocked', last_error=text)
        await _subtask_report(row, f'{text}. Круг не засчитан', ok=False, blocked=True)
    else:
        await task_state_task_fail(row_id, text)
        await task_report_write(row_id, f'{text}. Круг не засчитан', ok=False)

    logger_info(f'[task] #{row_id}: диалог в оболочке {role} — задан вопрос человеку')

    return True


async def _plan_role(task: dict, planners: dict) -> str:
    """
    Кто пишет план — и заодно приведение типа задачи к фазе.

    Планирует менеджер. Тип `dev` у ещё не разложенной задачи описывает будущую
    работу, а не текущий шаг, и без этого перевода план писала бы карточка
    разработчика: роль выбирается по типу (`task_role_by_type`). Поэтому взятой в
    планирование задаче ставим тип `plan` — он и есть то, что с ней происходит, — а
    разработка достаётся подзадачам. Обратно тип вернёт утверждение плана
    (`task_state_type_to_dev`).

    Роль не выдумываем второй раз, а перечитываем задачу: тип сменён — и
    `task_role_of_task` сама вернёт менеджера. Два места, решающих одно и то же,
    разошлись бы при первой правке карты типов.

    Тип не трогаем, когда живой карточки менеджера у проекта нет: перевод увёл бы
    задачу к роли, до которой некому дойти, и прогон сорвался бы на первом обращении
    к оболочке. Тогда планирует тот, за кем задачу и взяли, — как и раньше.

    `planners` — живые роли-планировщики по проектам (`task_role_planners_only`), тот
    же словарь, по которому шёл захват.
    """
    live = planners.get(task.get('project_id') or TASK_ROLE_PROJECT_NONE) or []
    if TASK_ROLE_MANAGER in live and await task_state_type_to_plan(int(task['id'])):
        task = await task_state_task_get(int(task['id'])) or task

    return await task_role_of_task(task)


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
    'llm_ping':       _run_llm_ping,
    'session_sweep':  _run_session_sweep,
    'manager_review': _run_manager_review,
    'manager_plan':   _run_manager_plan,
    'plan_split':     _run_plan_split,
    'developer':      _run_developer,
    'qa':             _run_qa,
    'bugfix':         _run_bugfix,
    'finalize':       _run_finalize,
}


async def _shell_assign(action: dict, task: dict, role: str) -> str:
    """
    Захватить роли оболочку на круг. Возвращает `session_uuid` или пустую строку.

    У роли столько оболочек, сколько терминалов открыл человек, и круг держит свою до
    конца: все шаги workflow ходят в один и тот же Claude Code — иначе шаг плана не
    увидит того, что нашла разведка. Адрес едет в прогон переменной
    `task_shell_session`.

    Пустая строка — свободных оболочек нет, круг начинать нельзя. Отличить это от
    «захват не понадобился» вызывающему помогает `action['shell_wait']`: его ставят
    здесь же, и по нему шаг решает, ждать очереди или идти дальше.

    Оболочек нет вовсе (роль не запущена) — не ждём и не мешаем: шаг сорвётся сам с
    понятным `no_session`, а конвейер отдаст задачу на повтор. Тормозить её здесь
    значило бы спрятать причину: карточка роли на `/admin/team` серая, и это видно.
    """
    project_id = int((task or {}).get('project_id') or 0)
    task_id = int((task or {}).get('id') or 0)
    try:
        by_role = (await task_role_shell_sessions_by_project()).get(project_id, {})
        sessions = by_role.get(role, [])
        if not sessions:
            return ''

        sessions, sticky_within = await _shell_order(project_id, by_role, sessions)
        # Чем оболочка была занята прошлый круг — до захвата: захват перепишет `task_id`
        # на нынешнюю задачу, и спросить станет уже нечего. По этому числу агент решает,
        # перезапускать ли себя: задача та же — контекст полезен, другая — вреден.
        was = await team_shell_pool_tasks(project_id)
        session_uuid = await team_shell_pool_acquire(project_id, role, task_id, sessions,
                                                    sticky_within=sticky_within)
        if not session_uuid:
            logger_info(f'[task] {role}: все оболочки проекта #{project_id} заняты '
                        f'({len(sessions)} шт.)')
            action['shell_wait'] = True
            return ''

        action['shell'] = session_uuid
        action['shell_task_prev'] = int(was.get(session_uuid) or 0)

        return session_uuid
    except Exception as e:
        logger_info(f'[task] захват оболочки для {role} не удался: {e}')

        return ''


async def _resources_touch(action: dict) -> None:
    """
    Подтвердить захваты круга — оболочку и модель. Зовётся ударом сердца `_lock_hold`.

    Адреса берём из самого действия: их положили туда выдачи (`_shell_assign`,
    `_llm_assign`), и они же нужны освобождению в `finally`. Чего в действии нет, того
    круг и не захватывал — облачная оболочка идёт без модели, и подтверждать ей нечего.

    Сбой подтверждения круг не роняет: одна пропущенная отметка запаса не съедает
    (`TEAM_SHELL_POOL_STALE_SECONDS` — это шесть с лишним ударов), а падать в фоновой
    задаче из-за заминки в базе значило бы уронить работу ради уборки.
    """
    with suppress(Exception):
        session_uuid = str(action.get('shell') or '')
        if session_uuid:
            await team_shell_pool_touch(session_uuid)

        llm = str(action.get('llm') or '')
        if llm:
            await team_llm_pool_touch(llm, int(action.get('llm_task_id') or 0),
                                      str(action.get('llm_role') or ''))


async def _wait_resource(kind: str, row_id: int, label: str, what: str) -> str:
    """
    Круг не начался — ресурс занят. Вернуть строку в очередь и сказать об этом.

    Захват и работа разнесены: тик переводит строку в переходное состояние, а круг
    начинается позже — и может не начаться, если все оболочки роли заняты или в пуле
    нет свободной модели. Работы при этом не было ни на секунду.

    Раньше такая строка оставалась захваченной до реклейма, то есть две минуты. И всё
    это время она мешала дважды: на странице задача числилась «в работе», хотя ею никто
    не занимался, а её захват занимал место в пределе параллельности проекта — то самое
    место, на которое могла бы прийти настоящая работа. Живьём #5238 каждые две минуты
    отбирал круг у свободной облачной оболочки, не делая ничего.

    Попытку не жжём и в журнал задачи не пишем: работы не было, записывать нечего.
    Ждать строка будет в своём прежнем состоянии, и следующий тик возьмёт её заново —
    когда ресурс освободится.
    """
    state = await task_claim_release(int(row_id or 0))

    return f'{kind}#{row_id} {label} ждёт {what}' + (f' -> {state}' if state else '')


async def _shell_order(project_id: int, by_role: dict, sessions: list) -> tuple[list, list]:
    """
    Разложить оболочки роли по предпочтению. Возвращает `(порядок, где липнуть)`.

    **Локальная модель всегда вперёд облачного агента.** Пока в пуле свободна модель,
    круг обязан идти в пуловую оболочку. Без этого порядок решала гонка: освободилась
    локальная модель, за круг брались обе карточки, и выигрывала любая — сплошь и рядом
    работа уходила за облачные токены, а оплаченная локальная модель простаивала.

    Когда свободных моделей нет, порядок обратный: пуловой оболочке идти не с чем, она
    упрётся в «ждёт свободной модели» и потратит на это захват, — а облачная работает
    своим бэкендом и круг возьмёт.

    Второй возврат — где разрешено прилипание (`team_shell_pool_acquire`). Оно
    предпочитает оболочку прошлого круга ради прогретого контекста, но правило старше
    предпочтения: липнуть можно только внутри ведущей группы, иначе «прошлый раз
    работали в облачной» раз за разом уводило бы круг мимо свободной локальной модели.

    Пул пуст — делить нечего: порядок остаётся прежним, прилипание по всему списку.
    """
    order = [str(s).strip() for s in (sessions or []) if str(s).strip()]
    cloud = {item['session_uuid'] for item in await team_llm_pool_cloud_items(by_role)}
    if not cloud or not await team_llm_pool_get(project_id):
        return order, order

    local = [uuid for uuid in order if uuid not in cloud]
    remote = [uuid for uuid in order if uuid in cloud]
    if not local or not remote:
        return order, order

    lead, tail = (local, remote) if await team_llm_pool_free_names(project_id) else (remote, local)

    return lead + tail, lead


async def _llm_assign(action: dict, task: dict, role: str) -> dict:
    """
    Выдать роли модель на круг и сказать её оболочке переключиться.

    Returns: `{'llm', 'context', 'wait'}`. `wait = True` — свободных моделей нет, круг
    начинать нельзя: работа ждёт очереди. Это не сбой, а тот же предел, что раньше
    задавался числом «Parallel LLM», — теперь он равен размеру пула.

    Выданную модель кладём в само действие (`action['llm']`): освобождает её
    `_llm_release` из `finally`, и знать, что именно было захвачено, ему больше
    неоткуда. Освобождение по одному лишь `task_id` было бы шире круга — у задачи
    рядом идут круги других ролей с тем же номером, и им сняли бы модель посреди
    работы.

    Пул пуст — ничего не захватываем и `wait` не ставим: проект работает облачным
    Anthropic, где предел прежний.

    **Оболочка без `--litellm` пула не касается** — и по той же причине не ждёт
    очереди: работать ей есть чем, у неё родной облачный агент Claude Code. Это и есть
    смысл флага; выдай мы ей модель, `__SWITCH_LLM__` перевёл бы её на пул, перезапустив
    агента, и запуск без флага ничем не отличался бы от запуска с ним.

    Сбой захвата круг не срывает: без модели роль пошла бы на штатный бэкенд, а это
    хуже ожидания — счёт за чужой прогон человек увидит уже постфактум. Поэтому любая
    неожиданность здесь тоже даёт `wait`.
    """
    project_id = int((task or {}).get('project_id') or 0)
    try:
        pool = await team_llm_pool_get(project_id)
        if not pool:
            return {'llm': '', 'context': '', 'wait': False}

        # Оболочка — та, что захватил круг (`_shell_assign`), а не «самая свежая у
        # роли»: у роли их несколько, и маркер `__SWITCH_LLM__` ушёл бы в чужой
        # терминал. Живьём это выглядело так: карточка занята работой, а модель на
        # ней «ждёт круга» — переключение уехало соседу, который ничего не делал.
        # Заодно по этому же адресу гасятся прошлые захваты (`_holder_locks_clear`),
        # и с чужим адресом круг снимал модель у соседа.
        #
        # Захвата нет (оболочек у роли не нашлось) — прежний путь: спрашиваем
        # свежайшую, как было до появления `team_shell_pool`.
        session_uuid = (str(action.get('shell') or '')
                        or await task_role_shell_session(project_id, role))

        # Облачная оболочка идёт мимо пула — и мимо ожидания: занятый пул её не
        # держит, у неё свой бэкенд. Проверяем после выбора адреса, потому что режим
        # это свойство конкретной оболочки, а не роли: у одной роли рядом бывают и
        # пуловые, и облачные терминалы.
        if await team_llm_pool_shell_cloud(session_uuid):
            logger_info(f'[task] {role}: оболочка {session_uuid[:8]} поднята без --litellm, '
                        f'круг идёт облачным агентом мимо пула')
            return {'llm': '', 'context': '', 'wait': False}

        given = await team_llm_pool_assign(project_id, int((task or {}).get('id') or 0),
                                           role, session_uuid)
        if not given['llm']:
            logger_info(f"[task] {role}: свободных моделей в пуле проекта #{project_id} нет")
            return {'llm': '', 'context': '', 'wait': True}

        action['llm'] = given['llm']
        action['llm_role'] = role
        action['llm_task_id'] = int((task or {}).get('id') or 0)

        return {**given, 'wait': False}
    except Exception as e:
        logger_info(f'[task] выдача модели для {role} не удалась: {e}')

        return {'llm': '', 'context': '', 'wait': True}


async def _llm_release(action: dict) -> None:
    """
    Освободить ресурсы круга — оболочку и модель. Чужие захваты не трогает.

    Оболочку снимаем по её `session_uuid`: он записан при выдаче, и другой круг под
    ним стоять не может — захват атомарен.

    Снимаем ровно свой захват — по тройке «модель + задача + роль», записанной при
    выдаче. Тройка, а не одно имя: пока круг шёл, модель могла протухнуть по сроку и
    уйти другой работе, и снять её значило бы отобрать чужую.

    Действие без модели (пул пуст, круг до неё не дошёл) сюда просто не попадает:
    ключа в нём нет.

    Строка при этом не удаляется, гаснет только отметка занятости: `task_id` в ней
    остаётся, и следующий круг той же задачи получит ту же модель обратно
    (прилипание, см. `team_llm_pool_acquire`).

    Сбой освобождения круг не роняет: модель протухнет сама
    (`TEAM_LLM_POOL_STALE_SECONDS`), а падать в `finally` из-за уборки значило бы
    потерять результат уже сделанной работы.
    """
    session_uuid = str(action.get('shell') or '')
    if session_uuid:
        try:
            await team_shell_pool_release(session_uuid=session_uuid)
        except Exception as e:
            logger_info(f'[task] оболочка не освободилась: {e}')

    llm = str(action.get('llm') or '')
    if not llm:
        return

    try:
        await team_llm_pool_release(llm_name=llm,
                                    task_id=int(action.get('llm_task_id') or 0),
                                    role=str(action.get('llm_role') or ''))
    except Exception as e:
        logger_info(f'[task] модель не освободилась: {e}')
