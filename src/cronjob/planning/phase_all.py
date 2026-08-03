"""
Единый кронджоб для всех фаз планирования.
Заменяет отдельные кронджобы для каждой фазы.
Запускает фазы последовательно; score и supplements — параллельно после blueprint.

Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/planning/phase_all.py","metadata":{},"timeout":7200}
"""
import asyncio
import json
import sys

from src.cronjob.planning.phase_base import project_planning_phase_run

PHASE_CHAIN = [
    ('analyze',   'planning_analyzer',            []),
    ('market',    'planning_market_researcher',   ['analyze']),
    ('product',   'planning_product_planner',     ['market']),
    ('tech',      'planning_tech_architect',      ['product']),
    ('gtm',       'planning_gtm_strategist',      ['tech']),
    ('financial', 'planning_financial_modeler',   ['gtm']),
    ('blueprint', 'planning_blueprint_composer',  ['analyze', 'market', 'product', 'tech', 'gtm', 'financial']),
]

SUPPLEMENT_TYPES = ['market', 'product', 'tech', 'gtm', 'financial', 'launch']


async def main():
    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            pass

    total = {'processed': 0, 'errors': 0}

    # Последовательные фазы
    for phase, agent_name, requires in PHASE_CHAIN:
        stats = await project_planning_phase_run(
            agent_name=agent_name,
            phase=phase,
            requires_phases=requires,
        )
        total['processed'] += stats['processed']
        total['errors'] += stats['errors']

    # После blueprint: score + supplements параллельно
    parallel_tasks = [
        project_planning_phase_run(
            agent_name='planning_scorer',
            phase='score',
            requires_phases=['blueprint'],
            project_statuses=['pending', 'processing', 'complete'],
            restore_project_status='complete',
        ),
        *[
            project_planning_phase_run(
                agent_name='planning_supplement_writer',
                phase=f'supplement_{stype}',
                requires_phases=['analyze', 'market', 'product', 'tech', 'gtm', 'financial', 'blueprint'],
                extra_variables={'planning_supplement_type': stype},
                project_statuses=['pending', 'processing', 'complete'],
            )
            for stype in SUPPLEMENT_TYPES
        ],
    ]
    results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, dict):
            total['processed'] += r.get('processed', 0)
            total['errors'] += r.get('errors', 0)

    print(json.dumps(total))


if __name__ == '__main__':
    asyncio.run(main())
