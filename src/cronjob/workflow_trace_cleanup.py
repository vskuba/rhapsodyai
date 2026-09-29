"""Крон уборки трассы workflow: сносит прогоны старше срока пачками.

## Зачем отдельный крон

Уборка жила первой строкой ручки `/workflow_trace/run/list`, то есть шла на
**каждое** открытие страницы трасс — а страница зовёт список дважды при заходе и
ещё раз на каждое переключение вкладки, отбора и страницы.

Замерено на проде: 119 мс полного прохода по таблице в 174 МБ, и снесённых строк
при этом **ноль** — 26 тысяч прогонов набегают меньше чем за неделю, до порога не
доживает никто. Плюс next-key-замки на всё просмотренное: открытие страницы
запирало запись трассы для идущих в этот момент workflow. Подробности и
устройство самого `DELETE` — в докстринге `ai_workflow_trace_trim`.

## Запуск

Через Cronicle, как уборка логов:

    POST /cronjob {"cronjob_path": "src/cronjob/workflow_trace_cleanup.py",
                   "metadata": {}, "timeout": 300}

Разумный срок — раз в час. Чаще незачем: за час набегает пара сотен прогонов, и
уборка каждый раз находит ровно их.

Сроки и размер пачки — аргументами: `{"keep_days": 3, "batch": 500}`.

## ⚠ Молчит намеренно

Доклада в Telegram здесь нет, в отличие от соседних кронджобов. Уборка старья —
это не событие: ежечасное «снесено 187» перестают читать через день, а вместе с
ним перестают читать и соседние сообщения, ради которых доклады заведены. Сколько
снесено — видно в журнале прогона Cronicle и в `app.log`.
"""
import asyncio
import json
import sys

from logging_.logging_ import logger_info, logging_init
from mysql_.mysql_ import mysql_pool_close

from src.ai.ai_workflow_trace import (TRACE_KEEP_DAYS, TRACE_TRIM_BATCH,
                                      TRACE_TRIM_MAX, ai_workflow_trace_trim)
from src.journal.journal_handler import journal_handler_install
from src.journal.journal_mysql import (journal_mysql_watch_start,
                                       journal_mysql_watch_stop)


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (страница «Журнал»,
    # /admin/journal): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    journal_handler_install('cronjob')
    # Счёт запросов к базе — подвкладка «MySQL» той же страницы. Сбрасывает
    # его `journal_mysql_watch_stop` перед выходом: процесс короткий.
    await journal_mysql_watch_start('cronjob')

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}

    keep_days = int(metadata.get('keep_days') or TRACE_KEEP_DAYS)
    batch = int(metadata.get('batch') or TRACE_TRIM_BATCH)
    limit = int(metadata.get('limit') or TRACE_TRIM_MAX)

    removed = await ai_workflow_trace_trim(keep_days=keep_days, batch=batch, limit=limit)

    # ⚠ Счёт запросов сбрасываем ДО закрытия пула: сброс ходит в базу тем же
    # пулом, и после закрытия ему не на чем ехать.
    await journal_mysql_watch_stop()
    # ⚠ Пул закрываем сами: без этого процесс не выйдет, пока соединения не
    # отвалятся по таймауту базы, и Cronicle досчитает job до своего.
    await mysql_pool_close()

    report = f'трасса: снесено прогонов {removed} (старше {keep_days} дн.)'
    logger_info(f'[trace] {report}')

    print(report)
    print(json.dumps({'removed': removed, 'keep_days': keep_days}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
