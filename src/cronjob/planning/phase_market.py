"""
Фаза 2: Исследование рынка.
Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/planning/phase_market.py","metadata":{},"timeout":300}
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
        agent_name='planning_market_researcher',
        phase='market',
        requires_phases=['analyze'],
    )
    print(json.dumps(stats))


if __name__ == '__main__':
    asyncio.run(main())
