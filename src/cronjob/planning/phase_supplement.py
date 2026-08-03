"""
Фаза 8: Supplements (детализированные дополнения к Blueprint).
Запускается 6 раз — по одному на каждый тип дополнения.
Cronicle (пример): POST /cronjob {"cronjob_path":"src/cronjob/planning/phase_supplement.py","metadata":{"supplement_type":"market"},"timeout":420}

supplement_type: market | product | tech | gtm | financial | launch
"""
import asyncio
import sys
import json

from src.cronjob.planning.phase_base import project_planning_phase_run

SUPPLEMENT_TYPES = ['market', 'product', 'tech', 'gtm', 'financial', 'launch']


async def main():
    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            pass

    supplement_type = str(metadata.get('supplement_type', '') or '').strip()
    if supplement_type not in SUPPLEMENT_TYPES:
        # Если тип не указан — запускаем все типы последовательно
        total = {'processed': 0, 'errors': 0}
        for stype in SUPPLEMENT_TYPES:
            stats = await _run_supplement(stype)
            total['processed'] += stats['processed']
            total['errors'] += stats['errors']
        print(json.dumps(total))
        return

    stats = await _run_supplement(supplement_type)
    print(json.dumps(stats))


async def _run_supplement(supplement_type: str) -> dict:
    phase_name = f'supplement_{supplement_type}'
    stats = await project_planning_phase_run(
        agent_name='planning_supplement_writer',
        phase=phase_name,
        requires_phases=['analyze', 'market', 'product', 'tech', 'gtm', 'financial', 'blueprint'],
        extra_variables={'planning_supplement_type': supplement_type},
        project_statuses=['pending', 'processing', 'complete'],
    )
    return stats


if __name__ == '__main__':
    asyncio.run(main())
