"""
Фаза 8: Scoring — оценка Blueprint по ключевым критериям.
Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/planning/phase_score.py","metadata":{},"timeout":300}
"""
import asyncio
import sys
import json

from src.cronjob.planning.phase_base import project_planning_phase_run


async def main():
    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            pass

    stats = await project_planning_phase_run(
        agent_name='planning_scorer',
        phase='score',
        requires_phases=['blueprint'],
        project_statuses=['pending', 'processing', 'complete'],
        restore_project_status='complete',
    )
    print(json.dumps(stats))


if __name__ == '__main__':
    asyncio.run(main())
