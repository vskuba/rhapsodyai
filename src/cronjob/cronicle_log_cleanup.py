"""
Крон уборки логов Cronicle: сносит архивы суточной ротации старше N дней.

Сам Cronicle логи ротирует, но архивы не удаляет никогда — на проде их набралось
208 файлов и 30 МБ за месяц. Историю прогонов (`data/jobs`) этот крон не трогает:
её чистит сам Cronicle по `job_data_expire_days` (переменная
`CRONICLE_job_data_expire_days` в `docker-compose.yml`).

Запуск через Cronicle: POST /cronjob {"cronjob_path": "src/cronjob/cronicle_log_cleanup.py",
"metadata": {"keep_days": 3}, "timeout": 120}
"""
import asyncio
import json
import sys

from logging_.logging_ import logging_init
from src.cronicle.cronicle_log import CRONICLE_LOG_KEEP_DAYS, cronicle_log_prune


async def main():
    logging_init()

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}

    stats = cronicle_log_prune(int(metadata.get('keep_days') or CRONICLE_LOG_KEEP_DAYS))
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
