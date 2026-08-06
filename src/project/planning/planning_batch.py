"""
Пакетный прогон планирования — то, что дёргает Cronicle.

В отличие от `planning_runner` (событийный, обрабатывает конкретный проект внутри
uvicorn), здесь фазы прогоняются по всем подходящим проектам сразу. Это подстраховка:
если раннер не отработал, пакетный проход раз в час доведёт проекты до конца.
"""
import asyncio

from src.project.planning.planning_chain import (
    PLANNING_CHAIN,
    PLANNING_SCORE_AGENT,
    PLANNING_SCORE_REQUIRES,
    PLANNING_SUPPLEMENT_AGENT,
    PLANNING_SUPPLEMENT_REQUIRES,
    PLANNING_SUPPLEMENT_TYPES,
    planning_chain_phase_get,
)
from src.project.planning.planning_phase import planning_phase_run


async def planning_batch_run_all() -> dict:
    """Вся цепочка по волнам, затем score и supplements параллельно."""
    total = {'processed': 0, 'errors': 0}

    for wave in PLANNING_CHAIN:
        for phase, agent_name, requires in wave:
            _stats_add(total, await planning_phase_run(
                agent_name=agent_name, phase=phase, requires_phases=requires))

    results = await asyncio.gather(
        planning_batch_run_score(),
        *[planning_batch_run_supplement(stype) for stype in PLANNING_SUPPLEMENT_TYPES],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, dict):
            _stats_add(total, result)

    return total


async def planning_batch_run_phase(phase: str) -> dict:
    """Одна фаза цепочки по имени. Заменяет прежние отдельные `phase_*.py`."""
    if phase == 'score':
        return await planning_batch_run_score()

    item = planning_chain_phase_get(phase)
    if not item:
        raise ValueError(f'Неизвестная фаза: {phase!r}')
    _, agent_name, requires = item
    return await planning_phase_run(agent_name=agent_name, phase=phase, requires_phases=requires)


async def planning_batch_run_score() -> dict:
    return await planning_phase_run(
        agent_name=PLANNING_SCORE_AGENT,
        phase='score',
        requires_phases=PLANNING_SCORE_REQUIRES,
        project_statuses=['pending', 'processing', 'complete'],
        restore_project_status='complete',
    )


async def planning_batch_run_supplement(supplement_type: str) -> dict:
    if supplement_type not in PLANNING_SUPPLEMENT_TYPES:
        raise ValueError(f'Неизвестный supplement: {supplement_type!r}')
    return await planning_phase_run(
        agent_name=PLANNING_SUPPLEMENT_AGENT,
        phase=f'supplement_{supplement_type}',
        requires_phases=PLANNING_SUPPLEMENT_REQUIRES,
        extra_variables={'planning_supplement_type': supplement_type},
        # 'error' включён: если предыдущий supplement упал и перевёл проект в error,
        # следующие supplements всё равно должны запуститься.
        project_statuses=['pending', 'processing', 'complete', 'error'],
    )


def _stats_add(total: dict, stats: dict) -> None:
    total['processed'] += stats.get('processed', 0)
    total['errors'] += stats.get('errors', 0)
