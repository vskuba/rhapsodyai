"""
Оркестратор планирования — единственный кронджоб модуля.
Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/planning_orchestrator.py","metadata":{},"timeout":7200}

metadata:
    {}                            — вся цепочка + score + supplements
    {"phase":"analyze"}           — одна фаза цепочки (либо "score")
    {"supplement_type":"market"}  — один supplement
"""
import asyncio
import json
import sys

from logging_.logging_ import logging_init
from src.journal.journal_handler import journal_handler_install
from mysql_.mysql_ import mysql_pool_close
from src.project.planning.planning_batch import (
    planning_batch_run_all,
    planning_batch_run_phase,
    planning_batch_run_supplement,
)


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (страница «Журнал»,
    # /admin/journal): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    journal_handler_install('cronjob')

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            pass

    try:
        supplement_type = metadata.get('supplement_type')
        phase = metadata.get('phase')

        if supplement_type:
            stats = await planning_batch_run_supplement(supplement_type)
        elif phase:
            stats = await planning_batch_run_phase(phase)
        else:
            stats = await planning_batch_run_all()

        print(json.dumps(stats, ensure_ascii=False))
    finally:
        # Процесс отдельный, пул свой — закрываем явно, иначе соединения утекают.
        await mysql_pool_close()


if __name__ == '__main__':
    asyncio.run(main())
