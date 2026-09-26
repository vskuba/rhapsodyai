"""
Воркер планирования проекта: кто ставит проект в очередь — тот его не планирует.

Инструмент, роутер и восстановление при старте только кладут сообщение в Redis-очередь
и сразу возвращаются. Всю цепочку фаз (analyze → … → blueprint, затем score и
supplements) прогоняет пул `rq worker-pool` из контейнера `worker_planning`.

Очередь своя (`planning`), не общая с конвейером задач. Причина в длине работы: цепочка
фаз идёт до 13 часов, шаг конвейера — до часа. В одной очереди запланированный проект
занимал бы исполнителя на весь день, и задачи стояли бы за ним. Исполнителей в пуле
несколько, от гонок по одному проекту защищает single-flight.

Дубликаты. У фаз нет захвата строки, как у задач, поэтому вся защита — ключ Redis
`planning_worker:flight:<project_id>`: пока цепочка проекта не закончилась, второе
сообщение по этому проекту не поставится. Ключ живёт не дольше самого job'а — умерший
воркер не должен запереть проект навсегда.

Переживает рестарт: задание лежит в Redis, а не в памяти uvicorn. Поэтому
`planning_worker_recover()` при старте сбрасывает в `pending` только те `running`-фазы,
чей проект НЕ держит flight-ключ: остальные прямо сейчас планируются в контейнере
`worker_task`, и трогать их нельзя.

Это основной путь обработки; пакетный `planning_batch` из Cronicle — подстраховка.
Цепочка фаз общая для обоих, описана в `planning_chain`.

Соседи по `src/worker/`: `task_worker` — воркер конвейера задач (очередь `default`,
контейнер `worker_task`).
Общие правила обоих — `.claude/docs/worker.md`.
"""
import asyncio

from logging_.logging_ import logger_info, logging_init
from src.journal.journal_handler import journal_handler_install
from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close
from ai.ai_thread import ai_thread_framework_run
from queue_.queue_ import queue_init
from redis_.redis_ import redis_conn_get
from redis_queue.redis_queue import redis_queue_get
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from src.project.planning.planning_chain import (
    PLANNING_CHAIN,
    PLANNING_SCORE_AGENT,
    PLANNING_SCORE_REQUIRES,
    PLANNING_SUPPLEMENT_AGENT,
    PLANNING_SUPPLEMENT_REQUIRES,
    PLANNING_SUPPLEMENT_TYPES,
)
from src.project.planning.planning_phase import planning_phase_run
from src.project.planning.planning_phase_query import planning_phase_query_status

PLANNING_WORKER_QUEUE_NAME = 'planning'

# Один job = вся цепочка проекта. Последовательных фаз двенадцать: шесть волн
# (analyze, market, product, tech+gtm, financial, blueprint) плюс шесть supplements,
# которые идут строго по одному. Каждая фаза сама срывается по
# `planning_phase.PHASE_TIMEOUT_MAX` (3600s), значит потолок job'а обязан быть выше
# суммы: 12 × 3600 = 43200s. Убьёт rq раньше — фаза останется в `running` до
# следующего рестарта uvicorn. Час сверху — на запросы к БД между фазами.
# Дефолт rq (180s) сюда не годится на два порядка.
PLANNING_WORKER_JOB_TIMEOUT = 46800
PLANNING_WORKER_RESULT_TTL = 3600

_FLIGHT_KEY = 'planning_worker:flight:'


def planning_worker_enqueue(project_id: int) -> str | None:
    """
    Поставить проект в очередь планирования. Возвращает id job'а либо None,
    если проект уже планируется (single-flight занят).

    Безопасно вызывать из инструментов и роутеров: постановка занимает миллисекунды,
    цепочку фаз выполняет контейнер `worker_task`.
    """
    project_id = int(project_id)
    if not planning_worker_flight_acquire(project_id):
        logger_info(f'planning_worker: project {project_id} — уже в работе, пропуск')
        return None
    try:
        job = redis_queue_get(PLANNING_WORKER_QUEUE_NAME).enqueue(
            planning_worker_job_run, project_id,
            job_timeout=PLANNING_WORKER_JOB_TIMEOUT,
            result_ttl=PLANNING_WORKER_RESULT_TTL,
            failure_ttl=PLANNING_WORKER_RESULT_TTL,
        )
    except Exception:
        # Ключ занят, а задания нет — проект заперся бы до истечения TTL.
        planning_worker_flight_release(project_id)
        raise
    logger_info(f'planning_worker: project {project_id} — поставлен в очередь [{job.id[:8]}]')
    return job.id


def planning_worker_flight_acquire(project_id: int) -> bool:
    """
    Занять single-flight проекта. False — цепочка уже в очереди или выполняется.

    Захвата строки, как у конвейера задач, у фаз нет, поэтому ключ — единственная
    защита от двух цепочек по одному проекту в разных воркерах.
    """
    return bool(redis_conn_get().set(f'{_FLIGHT_KEY}{int(project_id)}', '1',
                                     nx=True, ex=PLANNING_WORKER_JOB_TIMEOUT))


def planning_worker_flight_release(project_id: int) -> None:
    """Освободить single-flight проекта. Повторный вызов безвреден."""
    redis_conn_get().delete(f'{_FLIGHT_KEY}{int(project_id)}')


def planning_worker_flight_busy(project_id: int) -> bool:
    """Держит ли проект flight-ключ, то есть планируется ли он прямо сейчас."""
    return bool(redis_conn_get().exists(f'{_FLIGHT_KEY}{int(project_id)}'))


def planning_worker_job_run(project_id: int) -> str:
    """
    Точка входа rq: прогнать цепочку планирования одного проекта.

    Синхронная намеренно — rq зовёт job как обычную функцию, свой event loop
    поднимаем внутри. Функция обязана быть импортируемой по имени модуля: воркер
    живёт в отдельном контейнере и восстанавливает её по ссылке из Redis.
    """
    return asyncio.run(_job_async(int(project_id)))


async def planning_worker_recover() -> None:
    """
    Восстановление при старте uvicorn. Звать один раз из lifespan, после `ai_tool_sync`.

    Сбрасывает фазы, брошенные смертью воркера, и доставляет в очередь проекты,
    которые ждут планирования. Проекты, что планируются прямо сейчас, не трогает —
    их отличает flight-ключ.
    """
    await _startup_reset()
    await _recover_pending()


async def _job_async(project_id: int) -> str:
    """
    Мини-инфраструктура движка (как в `main_uvicorn`) плюс цепочка одного проекта.

    Агенты фаз ходят через очередь `ai_framework_model`, а её разбирает фоновая
    задача. Без неё job повиснет на ожидании ответа.
    """
    logging_init()
    # Ошибки воркера — в общий журнал установки (страница «Журнал»,
    # /admin/journal): job падает в своём контейнере, и без этого его
    # падения видны только в `docker logs worker_task`.
    journal_handler_install('worker')
    queue_init([
        'chat', 'chat_response', 'chat_input_send',
        'task', 'task_abort', 'task_complete', 'task_continue',
        'tool', 'agent_abort', 'agent_response', 'ai_framework_model',
    ])
    framework_task = asyncio.create_task(ai_thread_framework_run([AiFrameworkAgent()]))
    try:
        return await _run_project_chain(project_id)
    finally:
        framework_task.cancel()
        planning_worker_flight_release(project_id)
        # Процесс отдельный, пул свой — закрываем явно, иначе соединения утекают.
        await mysql_pool_close()


async def _run_project_chain(project_id: int) -> str:
    """
    Выполняет фазы проекта по волнам из PLANNING_CHAIN.
    Фазы внутри волны запускаются параллельно (asyncio.gather).
    Следующая волна стартует только после завершения всех фаз текущей.
    После blueprint: score + все supplements параллельно.
    """
    logger_info(f'planning_worker: project {project_id} — цепочка запущена')
    try:
        for wave in PLANNING_CHAIN:
            # Фильтруем уже завершённые, останавливаемся на failed
            pending = []
            for phase, agent_name, requires in wave:
                status = await planning_phase_query_status(project_id, phase)
                if status == 'complete':
                    logger_info(f'planning_worker: project {project_id} [{phase}] — уже complete, пропуск')
                    continue
                if status == 'failed':
                    logger_info(f'planning_worker: project {project_id} [{phase}] — failed, цепочка остановлена')
                    return f'{phase}: failed'
                pending.append((phase, agent_name, requires))

            if not pending:
                continue

            if len(pending) == 1:
                phase, agent_name, requires = pending[0]
                logger_info(f'planning_worker: project {project_id} [{phase}] — запуск')
                stats = await _run_phase(project_id, phase, agent_name, requires)
                if stats.get('errors', 0):
                    logger_info(f'planning_worker: project {project_id} [{phase}] — ошибка, цепочка остановлена')
                    return f'{phase}: error'
                logger_info(f'planning_worker: project {project_id} [{phase}] — complete ✓')
            else:
                names = '+'.join(p for p, _, _ in pending)
                logger_info(f'planning_worker: project {project_id} [{names}] — параллельный запуск')
                results = await asyncio.gather(
                    *[_run_phase(project_id, phase, agent_name, requires)
                      for phase, agent_name, requires in pending],
                    return_exceptions=True,
                )
                for (phase, _, _), result in zip(pending, results):
                    if isinstance(result, Exception):
                        logger_info(f'planning_worker: project {project_id} [{phase}] — исключение: {result}')
                        return f'{phase}: {result}'
                    if result.get('errors', 0):
                        logger_info(f'planning_worker: project {project_id} [{phase}] — ошибка, цепочка остановлена')
                        return f'{phase}: error'
                    logger_info(f'planning_worker: project {project_id} [{phase}] — complete ✓')

        # После blueprint: score параллельно с supplements, supplements — строго последовательно.
        # Supplements используют одного агента (planning_supplement_writer), параллельный запуск
        # приводит к "занят" (TTL-дроп) и превышению TPM-лимита провайдера.
        logger_info(f'planning_worker: project {project_id} — запуск score '
                    f'+ {len(PLANNING_SUPPLEMENT_TYPES)} supplements (последовательно)')
        await asyncio.gather(
            _run_score(project_id),
            _run_supplements_sequential(project_id),
            return_exceptions=True,
        )
        return 'complete'

    except Exception as e:
        logger_info(f'planning_worker: project {project_id} — необработанная ошибка: {e}')
        return f'error: {e}'


async def _run_phase(project_id: int, phase: str, agent_name: str, requires: list[str]) -> dict:
    return await planning_phase_run(
        agent_name=agent_name,
        phase=phase,
        requires_phases=requires,
        project_statuses=['pending', 'processing'],
        skip_init=True,
        project_id_filter=project_id,
    )


async def _run_supplements_sequential(project_id: int) -> None:
    """Запускает supplements по одному — агент один, параллельный запуск даёт ошибки busy/TPM."""
    for stype in PLANNING_SUPPLEMENT_TYPES:
        try:
            await _run_supplement(project_id, stype)
        except Exception as e:
            logger_info(f'planning_worker: project {project_id} [supplement_{stype}] — error: {e}')


async def _run_score(project_id: int) -> None:
    await planning_phase_run(
        agent_name=PLANNING_SCORE_AGENT,
        phase='score',
        requires_phases=PLANNING_SCORE_REQUIRES,
        project_statuses=['pending', 'processing', 'complete'],
        restore_project_status='complete',
        skip_init=True,
        project_id_filter=project_id,
    )


async def _run_supplement(project_id: int, supplement_type: str) -> None:
    await planning_phase_run(
        agent_name=PLANNING_SUPPLEMENT_AGENT,
        phase=f'supplement_{supplement_type}',
        requires_phases=PLANNING_SUPPLEMENT_REQUIRES,
        extra_variables={'planning_supplement_type': supplement_type},
        # 'error' включён: если предыдущий supplement упал и перевёл проект в error,
        # следующие supplements всё равно должны запуститься.
        project_statuses=['pending', 'processing', 'complete', 'error'],
        skip_init=True,
        project_id_filter=project_id,
    )


async def _startup_reset() -> None:
    """
    Сбрасывает фазы, застрявшие в 'running', обратно в 'pending' — их прервала смерть
    воркера, а не собственная ошибка. `_recover_pending` подхватит проекты и поставит
    цепочки заново.

    Проекты с живым flight-ключом пропускаются: задание в Redis переживает рестарт
    uvicorn, и такие фазы прямо сейчас выполняются в контейнере `worker_task`.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT DISTINCT project_id FROM project_planning_phase WHERE status = 'running'"
        )
        rows = await db.fetchall()
        project_ids = [int(r['project_id']) for r in (rows or [])
                       if not planning_worker_flight_busy(int(r['project_id']))]
        if not project_ids:
            return

        placeholders = ', '.join(['%s'] * len(project_ids))
        await db.execute(
            f"UPDATE project_planning_phase SET status = 'pending', error = NULL "
            f"WHERE status = 'running' AND project_id IN ({placeholders})",
            project_ids,
        )
        count = db.rowcount

        await db.execute(
            f"UPDATE project SET status = 'pending' WHERE id IN ({placeholders})",
            project_ids,
        )
        await db.connection.commit()

    if count:
        logger_info(f'planning_worker: {count} running-фаз → pending при старте, '
                    f'перезапустятся автоматически (проектов: {len(project_ids)})')


async def _recover_pending() -> None:
    """Ставит в очередь проекты pending/processing — их цепочка не доведена до конца."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project WHERE status IN ('pending', 'processing') ORDER BY id ASC"
        )
        rows = await db.fetchall()

    count = 0
    for row in (rows or []):
        if planning_worker_enqueue(int(row['id'])):
            count += 1

    if count:
        logger_info(f'planning_worker: recovery — {count} проектов поставлено в очередь')
