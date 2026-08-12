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
`worker`; своя очередь потребовала бы отдельного процесса в docker-compose.

Соседи по `src/worker/`: `planning_worker` — воркер планирования проекта.
Общие правила обоих — `.claude/docs/worker.md`.
"""
import asyncio

from logging_.logging_ import logger_info, logging_init
from mysql_.mysql_ import mysql_pool_close
from py_modules.ai.ai_thread import ai_thread_framework_run
from queue_.queue_ import queue_init
from redis_.redis_ import redis_conn_get
from redis_queue.redis_queue import redis_queue_get
from src.ai.framework.agent.ai_framework import AiFrameworkAgent

TASK_WORKER_QUEUE_NAME = 'default'

# Потолок job'а лежит между таймаутом менеджера (`task_agent_manager.MANAGER_TIMEOUT`,
# 3600s) и возвратом протухшей блокировки (`task_claim.LOCK_TIMEOUT_SEC`, 4200s):
# job обязан сорваться позже, чем сдастся сам менеджер, но раньше, чем строку
# сочтут брошенной и отдадут другому воркеру. Дефолт rq (180s) сюда не годится.
TASK_WORKER_JOB_TIMEOUT = 3900
TASK_WORKER_RESULT_TTL = 3600

# Действия без захвата строки: от дубликатов их защищает только ключ single-flight.
TASK_WORKER_SINGLE_FLIGHT = ('bug_scan', 'finalize')

_FLIGHT_KEY = 'task_worker:flight:'


def task_worker_enqueue(action: dict) -> str:
    """Поставить действие в очередь. Возвращает id job'а."""
    job = redis_queue_get(TASK_WORKER_QUEUE_NAME).enqueue(
        task_worker_job_run, action,
        job_timeout=TASK_WORKER_JOB_TIMEOUT,
        result_ttl=TASK_WORKER_RESULT_TTL,
        failure_ttl=TASK_WORKER_RESULT_TTL,
    )
    return job.id


def task_worker_flight_acquire(kind: str) -> bool:
    """
    Занять single-flight для действия без захвата строки.

    False — такое действие уже в очереди или выполняется, ставить второе нельзя.
    Ключ живёт не дольше самого job'а: умерший воркер не должен запереть тип
    действия навсегда.
    """
    if kind not in TASK_WORKER_SINGLE_FLIGHT:
        return True
    return bool(redis_conn_get().set(f'{_FLIGHT_KEY}{kind}', '1', nx=True, ex=TASK_WORKER_JOB_TIMEOUT))


def task_worker_flight_release(kind: str) -> None:
    """Освободить single-flight. Повторный вызов безвреден."""
    if kind in TASK_WORKER_SINGLE_FLIGHT:
        redis_conn_get().delete(f'{_FLIGHT_KEY}{kind}')


def task_worker_job_run(action: dict) -> str:
    """
    Точка входа rq: выполнить ровно одно действие конвейера.

    Синхронная намеренно — rq зовёт job как обычную функцию, свой event loop
    поднимаем внутри. Функция обязана быть импортируемой по имени модуля:
    воркер живёт в отдельном контейнере и восстанавливает её по ссылке из Redis.
    """
    return asyncio.run(_job_async(action))


async def _job_async(action: dict) -> str:
    """
    Мини-инфраструктура движка (как в `main_uvicorn`) плюс одно действие.

    Manager — обычный агент: его шаги идут через очередь `ai_framework_model`, а
    её разбирает фоновая задача. Без неё job повиснет на ожидании ответа.
    """
    logging_init()
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
        await mysql_pool_close()
