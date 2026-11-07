"""Крон уборки журнала вызовов LLM: сносит строки `agent_session` старше срока.

## Зачем

Срока у этого журнала не было вовсе. Замерено на проде 2026-11-07: таблица росла
с 19 июля и набрала **2.29 млн строк на 7.3 ГБ** — 80% базы в 9.2 ГБ при
буферном пуле MySQL в 1 ГБ. Цена не в месте на диске, а в кэше: мёртвый хвост
вытесняет живые страницы, и база читает с диска то, что должна была помнить —
568 млн физических чтений и 6408 ожиданий свободной страницы в пуле за 39 суток.

Живому разговору срок не мешает: историю везде читают по свежим
(`WHERE session_uuid = … ORDER BY created_at DESC LIMIT N`), древний хвост не
спрашивает никто. Устройство самого `DELETE` — в докстринге `ai_session_trim`.

## Запуск

Через Cronicle, как уборка трасс:

    POST /cronjob {"cronjob_path": "src/cronjob/agent_session_cleanup.py",
                   "metadata": {}, "timeout": 300}

Разумный срок — раз в час. ⚠ Первая уборка на проде разгребает 806 тыс. строк
(замерено 2026-11-07), а потолок захода — `SESSION_TRIM_MAX` (50 000): часовой
крон размелет завал за ~16 часов, не держа базу под замком. Торопить его разовым
большим `limit` не надо — в таблицу в это время пишут живые вызовы.

Сроки и размер пачки — аргументами: `{"keep_days": 14, "batch": 500}`.

## ⚠ Молчит намеренно

Доклада в Telegram здесь нет, как и у уборки трасс: ежечасное «снесено 870»
перестают читать через день, а вместе с ним перестают читать и соседние
сообщения, ради которых доклады заведены. Сколько снесено — видно в журнале
прогона Cronicle и в `app.log`.
"""
import asyncio
import json
import sys

from logging_.logging_ import logger_info, logging_init
from mysql_.mysql_ import mysql_pool_close

from src.ai.ai_session import (SESSION_KEEP_DAYS, SESSION_TRIM_BATCH,
                               SESSION_TRIM_MAX, ai_session_trim)
from dashboard.src.page.journal.journal_install import journal_install_here
from dashboard.src.page.journal.journal_mysql import (journal_mysql_watch_start,
                                      journal_mysql_watch_stop)


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (страница «Журнал»,
    # /admin/journal): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    journal_install_here('cronjob')
    # Счёт запросов к базе — подвкладка «MySQL» той же страницы. Сбрасывает
    # его `journal_mysql_watch_stop` перед выходом: процесс короткий.
    await journal_mysql_watch_start('cronjob')

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}

    keep_days = int(metadata.get('keep_days') or SESSION_KEEP_DAYS)
    batch = int(metadata.get('batch') or SESSION_TRIM_BATCH)
    limit = int(metadata.get('limit') or SESSION_TRIM_MAX)

    removed = await ai_session_trim(keep_days=keep_days, batch=batch, limit=limit)

    # ⚠ Счёт запросов сбрасываем ДО закрытия пула: сброс ходит в базу тем же
    # пулом, и после закрытия ему не на чем ехать.
    await journal_mysql_watch_stop()
    # ⚠ Пул закрываем сами: без этого процесс не выйдет, пока соединения не
    # отвалятся по таймауту базы, и Cronicle досчитает job до своего.
    await mysql_pool_close()

    report = f'журнал вызовов: снесено строк {removed} (старше {keep_days} дн.)'
    logger_info(f'[session] {report}')

    print(report)
    print(json.dumps({'removed': removed, 'keep_days': keep_days}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
