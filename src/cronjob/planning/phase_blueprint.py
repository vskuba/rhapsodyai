"""
Фаза 7: Blueprint документ (главный сводный документ).
Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/planning/phase_blueprint.py","metadata":{},"timeout":420}
"""
import asyncio
import sys
import json

from src.cronjob.planning.phase_base import planning_phase_run


async def main():
    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            pass

    stats = await planning_phase_run(
        agent_name='planning_blueprint_composer',
        phase='blueprint',
        requires_phases=['analyze', 'market', 'product', 'tech', 'gtm', 'financial'],
    )
    print(json.dumps(stats))


if __name__ == '__main__':
    asyncio.run(main())
