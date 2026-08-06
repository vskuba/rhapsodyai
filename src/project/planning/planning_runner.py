"""
Planning Runner — фоновый asyncio-таск внутри uvicorn.
Запускает фазы планирования сразу после завершения предыдущей, не дожидаясь Cronicle.
После blueprint запускает score + supplements параллельно.

Это основной путь обработки; пакетный `planning_batch` из Cronicle — подстраховка.
Цепочка фаз общая для обоих, описана в `planning_chain`.
"""
import asyncio

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
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

_queue: asyncio.Queue = asyncio.Queue()
_active: set[int] = set()
_queued: set[int] = set()  # дополнительная защита от дублей в очереди


async def planning_runner_enqueue(project_id: int) -> None:
    """Добавить project_id в очередь обработки. Безопасно вызывать из инструментов."""
    if project_id not in _active and project_id not in _queued:
        _queued.add(project_id)
        await _queue.put(project_id)
        logger_info(f'planning_runner: project {project_id} — поставлен в очередь')


async def planning_runner_start() -> None:
    """
    Главный цикл runner'а. Запускать один раз через asyncio.create_task() в lifespan.
    Каждый проект обрабатывается в отдельном asyncio.Task — проекты параллельны,
    фазы внутри проекта — строго последовательны.
    """
    await _startup_reset()
    await _recover_pending()

    logger_info('planning_runner: запущен')
    while True:
        project_id = await _queue.get()
        _queued.discard(project_id)
        if project_id in _active:
            continue
        _active.add(project_id)
        asyncio.create_task(_run_project_chain(project_id))


async def _run_project_chain(project_id: int) -> None:
    """
    Выполняет фазы проекта по волнам из PLANNING_CHAIN.
    Фазы внутри волны запускаются параллельно (asyncio.gather).
    Следующая волна стартует только после завершения всех фаз текущей.
    После blueprint: score + все supplements параллельно.
    """
    logger_info(f'planning_runner: project {project_id} — цепочка запущена')
    try:
        for wave in PLANNING_CHAIN:
            # Фильтруем уже завершённые, останавливаемся на failed
            pending = []
            for phase, agent_name, requires in wave:
                status = await planning_phase_query_status(project_id, phase)
                if status == 'complete':
                    logger_info(f'planning_runner: project {project_id} [{phase}] — уже complete, пропуск')
                    continue
                if status == 'failed':
                    logger_info(f'planning_runner: project {project_id} [{phase}] — failed, цепочка остановлена')
                    return
                pending.append((phase, agent_name, requires))

            if not pending:
                continue

            if len(pending) == 1:
                phase, agent_name, requires = pending[0]
                logger_info(f'planning_runner: project {project_id} [{phase}] — запуск')
                stats = await _run_phase(project_id, phase, agent_name, requires)
                if stats.get('errors', 0):
                    logger_info(f'planning_runner: project {project_id} [{phase}] — ошибка, цепочка остановлена')
                    return
                logger_info(f'planning_runner: project {project_id} [{phase}] — complete ✓')
            else:
                names = '+'.join(p for p, _, _ in pending)
                logger_info(f'planning_runner: project {project_id} [{names}] — параллельный запуск')
                results = await asyncio.gather(
                    *[_run_phase(project_id, phase, agent_name, requires)
                      for phase, agent_name, requires in pending],
                    return_exceptions=True,
                )
                for (phase, _, _), result in zip(pending, results):
                    if isinstance(result, Exception):
                        logger_info(f'planning_runner: project {project_id} [{phase}] — исключение: {result}')
                        return
                    if result.get('errors', 0):
                        logger_info(f'planning_runner: project {project_id} [{phase}] — ошибка, цепочка остановлена')
                        return
                    logger_info(f'planning_runner: project {project_id} [{phase}] — complete ✓')

        # После blueprint: score параллельно с supplements, supplements — строго последовательно.
        # Supplements используют одного агента (planning_supplement_writer), параллельный запуск
        # приводит к "занят" (TTL-дроп) и превышению TPM-лимита провайдера.
        logger_info(f'planning_runner: project {project_id} — запуск score '
                    f'+ {len(PLANNING_SUPPLEMENT_TYPES)} supplements (последовательно)')
        await asyncio.gather(
            _run_score(project_id),
            _run_supplements_sequential(project_id),
            return_exceptions=True,
        )

    except Exception as e:
        logger_info(f'planning_runner: project {project_id} — необработанная ошибка: {e}')
    finally:
        _active.discard(project_id)


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
            logger_info(f'planning_runner: project {project_id} [supplement_{stype}] — error: {e}')


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
    При старте runner'а сбрасывает фазы застрявшие в 'running' обратно в 'pending' —
    они прерваны рестартом uvicorn, а не упали сами. _recover_pending подхватит
    их проекты и runner перезапустит фазу автоматически.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT DISTINCT project_id FROM project_planning_phase WHERE status = 'running'"
        )
        rows = await db.fetchall()
        project_ids = [int(r['project_id']) for r in (rows or [])]

        await db.execute(
            "UPDATE project_planning_phase SET status = 'pending', error = NULL WHERE status = 'running'"
        )
        count = db.rowcount

        if project_ids:
            placeholders = ', '.join(['%s'] * len(project_ids))
            await db.execute(
                f"UPDATE project SET status = 'pending' WHERE id IN ({placeholders})",
                project_ids,
            )

        await db.connection.commit()

    if count:
        logger_info(f'planning_runner: {count} running-фаз → pending при старте, '
                    f'перезапустятся автоматически (проектов: {len(project_ids)})')


async def _recover_pending() -> None:
    """Подхватывает проекты pending/processing при старте — они могли быть в очереди до рестарта."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project WHERE status IN ('pending', 'processing') ORDER BY id ASC"
        )
        rows = await db.fetchall()

    count = 0
    for row in (rows or []):
        project_id = int(row['id'])
        if project_id not in _queued:
            _queued.add(project_id)
            await _queue.put(project_id)
            count += 1

    if count:
        logger_info(f'planning_runner: recovery — {count} проектов поставлено в очередь')
