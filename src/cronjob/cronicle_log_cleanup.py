"""
Крон уборки логов Cronicle: сносит архивы суточной ротации старше N дней.

Сам Cronicle логи ротирует, но архивы не удаляет никогда — на проде их набралось
208 файлов и 30 МБ за месяц. Историю прогонов (`data/jobs`) этот крон не трогает:
её чистит сам Cronicle по `job_data_expire_days` (переменная
`CRONICLE_job_data_expire_days` в `docker-compose.yml`).

После уборки шлёт владельцу в Telegram строку с размерами обеих куч. Размер
истории прогонов там не ради красоты: `CRONICLE_job_data_expire_days` живёт в
переменной окружения и применяется в память, на диске в `config.json` остаётся
прежнее значение — убедиться, что настройка доехала, можно только по каталогу.

Запуск через Cronicle: POST /cronjob {"cronjob_path": "src/cronjob/cronicle_log_cleanup.py",
"metadata": {"keep_days": 3}, "timeout": 120}

Прогон вручную без сообщения в Telegram — `"metadata": {"notify": false}`.
"""
import asyncio
import json
import sys

from cronicle_.cronicle_log import (CRONICLE_LOG_KEEP_DAYS, cronicle_log_prune,
                                    cronicle_log_report, cronicle_log_sizes)
from logging_.logging_ import logger_info, logging_init
from src.error.error_log_handler import error_log_handler_install

from src.telegram_.telegram_notify import telegram_notify_send_owner


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (вкладка «Журнал» на
    # странице трасс): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    error_log_handler_install('cronjob')

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}

    stats = cronicle_log_prune(int(metadata.get('keep_days') or CRONICLE_LOG_KEEP_DAYS))
    sizes = cronicle_log_sizes()
    report = cronicle_log_report(stats, sizes)

    # `notify: false` в metadata — прогон вручную, без сообщения владельцу.
    if metadata.get('notify', True):
        try:
            await telegram_notify_send_owner(report)
        except Exception as e:
            # Уборка уже состоялась, и молчащий Telegram её не отменяет: пишем
            # в лог и выходим успешно, иначе Cronicle отметит job провалившимся
            # из-за того, что не относится к его работе.
            logger_info(f'🧹 Логи Cronicle: отчёт в Telegram не ушёл — {type(e).__name__}: {e}')

    print(report)
    print(json.dumps({**stats, 'sizes': sizes}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
