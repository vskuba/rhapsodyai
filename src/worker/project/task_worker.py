"""
Воркер конвейера задач: тик оркестратора ставит сообщение, воркер выполняет работу.

Cronicle-тик — триггер, а не исполнитель. Он сбрасывает протухшие блокировки,
захватывает строки и кладёт в Redis-очередь по сообщению на каждое действие,
после чего сразу завершается. Саму работу (менеджер в живой shell-оболочке,
Developer, QA) делает `rq worker` из docker-compose. Воркеров может быть много:
очередь одна, а от гонок защищает захват строки в `task_claim`.

Дубликаты. У действий с захватом их не бывает по построению: строка уже уведена
в переходное состояние, и следующий тик её не увидит. У сканера багов и
финализации захватывать нечего — работу они ищут уже внутри воркера, поэтому на
них ставится redis-ключ single-flight: пока прошлый job не закончился, тик не
поставит второй такой же.

Очередь `default` — та же, что поднимает `main_uvicorn` и разбирает контейнер
`worker_task`; своя очередь потребовала бы отдельного процесса в docker-compose.

Соседи по `src/worker/`: `planning_worker` — цепочка фаз планирования, та же очередь.
Общие правила обоих — `.claude/docs/worker.md`.
"""
import asyncio

from rq import Worker
from rq.job import Job

from logging_.logging_ import logger_info, logging_init
from src.journal.journal_handler import journal_handler_install
from src.journal.journal_mysql import (journal_mysql_watch_start,
                                       journal_mysql_watch_stop)
from mysql_.mysql_ import mysql_pool_close
from ai.ai_thread import ai_thread_framework_run
from queue_.queue_ import queue_init
from redis_.redis_ import redis_conn_get
from redis_queue.redis_queue import redis_queue_get
from src.ai.framework.agent.ai_framework import AiFrameworkAgent

TASK_WORKER_QUEUE_NAME = 'default'

# Потолок job'а — настройка `timeout_worker_job`, её приносит вызывающий (тик
# конвейера читает её один раз на тик, см. `task_pipeline_tick`). Значение лежит
# между таймаутом агента (`timeout_manager_run`) и возвратом протухшей блокировки
# (`timeout_task_lock`): job обязан сорваться позже, чем сдастся сам агент, но
# раньше, чем строку сочтут брошенной и отдадут другому воркеру. Дефолт rq (180s)
# сюда не годится. Правится на `/admin/team`, см. `task_setting_timeout`.
TASK_WORKER_RESULT_TTL = 3600

# Действия без захвата строки: от дубликатов их защищает только ключ single-flight.
TASK_WORKER_SINGLE_FLIGHT = ('bug_scan', 'finalize', 'llm_ping', 'session_sweep')

# Действия, которые идут не при каждой возможности, а по расписанию: сколько секунд
# ждать до следующего запуска.
#
# Пинг моделей пула — раз в пять минут. Каждый опрос это настоящий запрос к каждой
# модели, а локальная отвечает секунд десять и считает его на той же карте, что и
# работу ролей: частый пинг отнимал бы у круга то самое время, ради которого он
# заведён. Круг роли идёт минутами, так что мёртвая модель успеет испортить один
# круг, а не десять, — этого достаточно.
#
# Уборка сессий — раз в пять минут по той же причине: оболочка умирает молча, и
# заметить это можно только не дождавшись пинга. Чаще незачем — порог списания час.
TASK_WORKER_FLIGHT_PERIOD = {'llm_ping': 300, 'session_sweep': 300}

# Сколько времени строка имеет право быть заблокированной без job'а в очереди.
# Тик сперва блокирует строку и только следующим шагом кладёт сообщение — в этот
# зазор живого job'а у неё ещё нет, и без запаса реклейм отбирал бы строку у
# самого себя. Секунды хватило бы, но тик ходит в БД и в Redis, а часы контейнеров
# в docker расходятся — берём заведомо больше любого разумного зазора.
TASK_WORKER_ENQUEUE_GRACE_SEC = 120

# Ключи сообщений, по которым видно, к какой строке относится job.
TASK_WORKER_TARGET_KEYS = ('task_id', 'subtask_id')

_FLIGHT_KEY = 'task_worker:flight:'


def task_worker_enqueue(action: dict, job_timeout: int) -> str:
    """
    Поставить действие в очередь. Возвращает id job'а.

    `job_timeout` — секунды из настройки `timeout_worker_job`; читает её вызывающий,
    чтобы модуль воркера не тянул за собой обращение к базе (сюда он импортируется
    и из тика, и из rq-процесса).
    """
    job = redis_queue_get(TASK_WORKER_QUEUE_NAME).enqueue(
        task_worker_job_run, action,
        job_timeout=int(job_timeout),
        result_ttl=TASK_WORKER_RESULT_TTL,
        failure_ttl=TASK_WORKER_RESULT_TTL,
    )
    return job.id


def task_worker_live_targets() -> dict[str, set[int]] | None:
    """
    Строки конвейера, за которыми в очереди ещё стоит job.

    Возвращает `{'task_id': {…}, 'subtask_id': {…}}` — id из сообщений всех job'ов,
    которые ещё могут выполниться. `None` — очередь не ответила: тогда считать, что
    работы нет, нельзя, иначе реклейм отберёт строку у живого job'а.

    Живым считается job в очереди, отложенный, запланированный — и выполняющийся,
    но только пока в Redis числится взявший его воркер. Разница существенна: убитый
    контейнер оставляет свой job в `StartedJobRegistry` до ближайшей уборки rq
    (минуты), а регистрация самого воркера протухает по TTL, и это единственный
    признак потери, который виден без ожидания. Пустое `worker_name` считаем живым:
    job только что забрали из очереди и имя ещё не записали.

    Провалившиеся и завершённые job'ы сюда не попадают намеренно — именно они
    означают, что строку доводить до конца больше некому.
    """
    live: dict[str, set[int]] = {key: set() for key in TASK_WORKER_TARGET_KEYS}
    try:
        queue = redis_queue_get(TASK_WORKER_QUEUE_NAME)
        alive = {worker.name for worker in Worker.all(queue=queue)}
        waiting = (list(queue.get_job_ids())
                   + list(queue.deferred_job_registry.get_job_ids())
                   + list(queue.scheduled_job_registry.get_job_ids()))
        started = list(queue.started_job_registry.get_job_ids())
        jobs = _jobs_fetch(queue, waiting)
        jobs += [job for job in _jobs_fetch(queue, started)
                 if not job.worker_name or job.worker_name in alive]
    except Exception as e:
        logger_info(f'[task] очередь не опрошена, блокировки только по таймауту: {e}')
        return None

    for job in jobs:
        action = (list(job.args or []) or [None])[0]
        if not isinstance(action, dict):
            continue
        for key in TASK_WORKER_TARGET_KEYS:
            target = int(action.get(key) or 0)
            if target:
                live[key].add(target)
    return live


def task_worker_flight_acquire(kind: str, job_timeout: int) -> bool:
    """
    Занять single-flight для действия без захвата строки.

    False — такое действие уже в очереди или выполняется, ставить второе нельзя.
    Ключ живёт не дольше самого job'а (`job_timeout`, настройка `timeout_worker_job`):
    умерший воркер не должен запереть тип действия навсегда.

    У периодических действий (`TASK_WORKER_FLIGHT_PERIOD`) ключ живёт свой срок и
    работает не защитой от дублей, а расписанием: тик идёт каждую минуту, а пинг
    моделей нужен раз в пять — ключ на 300 секунд и даёт этот интервал, не требуя
    заводить отдельное событие планировщика на каждой инсталляции.
    """
    if kind not in TASK_WORKER_SINGLE_FLIGHT:
        return True

    seconds = TASK_WORKER_FLIGHT_PERIOD.get(kind) or int(job_timeout)

    return bool(redis_conn_get().set(f'{_FLIGHT_KEY}{kind}', '1', nx=True, ex=seconds))


def task_worker_flight_release(kind: str) -> None:
    """
    Освободить single-flight. Повторный вызов безвреден.

    Периодические действия не освобождаем: их ключ — это интервал до следующего
    запуска, и сняв его по завершении работы, мы получили бы запуск каждый тик,
    то есть каждую минуту вместо пяти.
    """
    if kind in TASK_WORKER_SINGLE_FLIGHT and kind not in TASK_WORKER_FLIGHT_PERIOD:
        redis_conn_get().delete(f'{_FLIGHT_KEY}{kind}')


def task_worker_job_run(action: dict) -> str:
    """
    Точка входа rq: выполнить ровно одно действие конвейера.

    Синхронная намеренно — rq зовёт job как обычную функцию, свой event loop
    поднимаем внутри. Функция обязана быть импортируемой по имени модуля:
    воркер живёт в отдельном контейнере и восстанавливает её по ссылке из Redis.
    """
    return asyncio.run(_job_async(action))


def _jobs_fetch(queue, job_ids: list) -> list:
    """
    Достать job'ы пачкой, пропустив исчезнувшие.

    `fetch_many` отдаёт `None` на месте job'а, чей ключ уже истёк между
    перечислением id и чтением — для нас это ровно то же, что «job'а нет».
    """
    if not job_ids:
        return []
    jobs = Job.fetch_many(job_ids, connection=queue.connection, serializer=queue.serializer)
    return [job for job in jobs if job is not None]


async def _job_async(action: dict) -> str:
    """
    Мини-инфраструктура движка (как в `main_uvicorn`) плюс одно действие.

    Manager — обычный агент: его шаги идут через очередь `ai_framework_model`, а
    её разбирает фоновая задача. Без неё job повиснет на ожидании ответа.
    """
    logging_init()
    # Ошибки воркера — в общий журнал установки (страница «Журнал»,
    # /admin/journal): job падает в своём контейнере, и без этого его
    # падения видны только в `docker logs worker_task`.
    journal_handler_install('worker')
    # Счёт запросов к базе — подвкладка «MySQL» той же страницы. Сбрасывает
    # его `journal_mysql_watch_stop` перед выходом: процесс короткий.
    await journal_mysql_watch_start('worker')
    queue_init([
        'chat', 'chat_response', 'chat_input_send',
        'task', 'task_abort', 'task_complete', 'task_continue',
        'tool', 'agent_abort', 'agent_response', 'ai_framework_model',
    ])
    framework_task = asyncio.create_task(ai_thread_framework_run([AiFrameworkAgent()]))

    # Импорт внутри функции — `task_pipeline` ставит задания через этот модуль,
    # на верхнем уровне вышел бы круговой импорт.
    from src.project.task.task_pipeline import task_pipeline_action_run

    kind = str(action.get('kind') or '')
    try:
        step = await task_pipeline_action_run(action)
        logger_info(f'[task] worker {kind}: {step or "работы не нашлось"}')
        return step or ''
    finally:
        framework_task.cancel()
        task_worker_flight_release(kind)
        # Процесс отдельный, пул свой — закрываем явно, иначе соединения утекают.
        # ⚠ Счёт запросов сбрасываем ДО закрытия пула: сброс ходит в базу
        # тем же пулом, и после закрытия ему не на чем ехать.
        await journal_mysql_watch_stop()
        await mysql_pool_close()
