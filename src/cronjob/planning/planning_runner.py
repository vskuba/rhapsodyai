"""
Planning Runner — фоновый asyncio-таск внутри uvicorn.
Запускает фазы планирования последовательно сразу после завершения предыдущей,
без ожидания Cronicle. После blueprint запускает score + supplements параллельно.
"""
import asyncio

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.cronjob.planning.phase_base import project_planning_phase_run, project_planning_phase_parent_complete

# Каждый элемент — волна фаз, запускаемых параллельно.
# Следующая волна стартует только после завершения всех фаз текущей.
# requires указывает, какие фазы должны быть complete (для _pending_projects_get).
PHASE_GROUPS = [
    [('analyze',   [])],
    [('market',    ['analyze'])],
    [('product',   ['market', 'analyze'])],
    [                                              # tech и gtm не зависят друг от друга
        ('tech', ['product']),
        ('gtm',  ['market', 'product']),
    ],
    [('financial', ['tech', 'gtm', 'market', 'product'])],
    [('blueprint', ['analyze', 'market', 'product', 'tech', 'gtm', 'financial'])],
]

PHASE_AGENTS = {
    'analyze':   'planning_analyzer',
    'market':    'planning_market_researcher',
    'product':   'planning_product_planner',
    'tech':      'planning_tech_architect',
    'gtm':       'planning_gtm_strategist',
    'financial': 'planning_financial_modeler',
    'blueprint': 'planning_blueprint_composer',
    'score':     'planning_scorer',
}

SUPPLEMENT_TYPES = ['market', 'product', 'tech', 'gtm', 'financial', 'launch']

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
    Выполняет фазы проекта по волнам из PHASE_GROUPS.
    Фазы внутри волны запускаются параллельно (asyncio.gather).
    Следующая волна стартует только после завершения всех фаз текущей.
    После blueprint: score + все supplements параллельно.
    """
    logger_info(f'planning_runner: project {project_id} — цепочка запущена')
    try:
        for group in PHASE_GROUPS:
            # Фильтруем уже завершённые, останавливаемся на failed
            pending = []
            for phase, requires in group:
                status = await _phase_status_get(project_id, phase)
                if status == 'complete':
                    logger_info(f'planning_runner: project {project_id} [{phase}] — уже complete, пропуск')
                    continue
                if status == 'failed':
                    logger_info(f'planning_runner: project {project_id} [{phase}] — failed, цепочка остановлена')
                    return
                pending.append((phase, requires))

            if not pending:
                continue

            if len(pending) == 1:
                phase, requires = pending[0]
                logger_info(f'planning_runner: project {project_id} [{phase}] — запуск')
                stats = await _run_phase(project_id, phase, requires)
                if stats.get('errors', 0):
                    logger_info(f'planning_runner: project {project_id} [{phase}] — ошибка, цепочка остановлена')
                    return
                logger_info(f'planning_runner: project {project_id} [{phase}] — complete ✓')
            else:
                names = '+'.join(p for p, _ in pending)
                logger_info(f'planning_runner: project {project_id} [{names}] — параллельный запуск')
                results = await asyncio.gather(
                    *[_run_phase(project_id, phase, requires) for phase, requires in pending],
                    return_exceptions=True,
                )
                for (phase, _), result in zip(pending, results):
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
        logger_info(f'planning_runner: project {project_id} — запуск score + {len(SUPPLEMENT_TYPES)} supplements (последовательно)')
        await asyncio.gather(
            _run_score(project_id),
            _run_supplements_sequential(project_id),
            return_exceptions=True,
        )

    except Exception as e:
        logger_info(f'planning_runner: project {project_id} — необработанная ошибка: {e}')
    finally:
        _active.discard(project_id)


async def _run_phase(project_id: int, phase: str, requires: list[str]) -> dict:
    return await project_planning_phase_run(
        agent_name=PHASE_AGENTS[phase],
        phase=phase,
        requires_phases=requires,
        project_statuses=['pending', 'processing'],
        skip_init=True,
        project_id_filter=project_id,
    )


async def _run_supplements_sequential(project_id: int) -> None:
    """Запускает supplements по одному — агент один, параллельный запуск даёт ошибки busy/TPM."""
    for stype in SUPPLEMENT_TYPES:
        try:
            await _run_supplement(project_id, stype)
        except Exception as e:
            logger_info(f'planning_runner: project {project_id} [supplement_{stype}] — error: {e}')


async def _run_score(project_id: int) -> None:
    await project_planning_phase_run(
        agent_name='planning_scorer',
        phase='score',
        requires_phases=['blueprint'],
        project_statuses=['pending', 'processing', 'complete'],
        restore_project_status='complete',
        skip_init=True,
        project_id_filter=project_id,
    )


async def _run_supplement(project_id: int, supplement_type: str) -> None:
    await project_planning_phase_run(
        agent_name='planning_supplement_writer',
        phase=f'supplement_{supplement_type}',
        requires_phases=['analyze', 'market', 'product', 'tech', 'gtm', 'financial', 'blueprint'],
        extra_variables={'planning_supplement_type': supplement_type},
        # 'error' включён: если предыдущий supplement упал и перевёл проект в error,
        # следующие supplements всё равно должны запуститься.
        project_statuses=['pending', 'processing', 'complete', 'error'],
        skip_init=True,
        project_id_filter=project_id,
    )


async def _phase_status_get(project_id: int, phase: str) -> str | None:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT status FROM project_planning_phase WHERE project_id = %s AND phase = %s",
            (project_id, phase)
        )
        row = await db.fetchone()
    return (row or {}).get('status')


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
        logger_info(f'planning_runner: {count} running-фаз → pending при старте, перезапустятся автоматически (проектов: {len(project_ids)})')


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
