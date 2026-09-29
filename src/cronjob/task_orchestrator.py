"""
Оркестратор конвейера задач: один тик машины состояний за запуск.
Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/task_orchestrator.py","metadata":{"max_actions":1},"timeout":60}

metadata:
    max_actions — сколько действий поставить в очередь за запуск (по умолчанию 1).

Работу здесь никто не делает. Тик — триггер: сбросить протухшие блокировки,
захватить строки, положить по сообщению на действие в Redis-очередь и выйти.
Выполняет контейнер `worker_task` (`rq worker default`), и воркеров может быть много —
см. `src/worker/project/task_worker.py`.

Поэтому `timeout` в теле запроса — секунды, а не часы: тик не ждёт ни менеджера,
ни агентов, и зависнуть ему негде. Долгие таймауты живут на другом конце:
настройка `timeout_worker_job` у job'а и `timeout_task_lock` у блокировки (обе
правятся на `/admin/team`, см. `src/project/task/task_setting_timeout.py`).
"""
import asyncio
import json
import sys

from logging_.logging_ import logging_init
from src.journal.journal_handler import journal_handler_install
from src.journal.journal_mysql import (journal_mysql_watch_start,
                                       journal_mysql_watch_stop)
from mysql_.mysql_ import mysql_pool_close
from src.project.task.task_pipeline import task_pipeline_tick


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
            pass

    try:
        stats = await task_pipeline_tick(max_actions=int(metadata.get('max_actions') or 1))
        # ⚠⚠ Сброс счётчика запросов — ДО печати итога, а не в `finally`. Контракт
        # кронджоба: итоговый JSON — **последняя непустая строка** stdout, по ней
        # его читает и Cronicle, и сюита (`_tick` в `tests/test_task_pipeline.py`).
        # Сброс ходит в базу, а пул печатает про каждый чекаут (`[MySQL POOL]`), и
        # из `finally` эти строки легли бы после JSON — тик переставал читаться.
        await journal_mysql_watch_stop()
        print(json.dumps(stats, ensure_ascii=False))
    finally:
        # Процесс отдельный, пул свой — закрываем явно, иначе соединения утекают.
        await mysql_pool_close()


if __name__ == '__main__':
    asyncio.run(main())
