"""Крон E2E-прогона: снять страницы панели и записать вердикты.

## Запуск

Через Cronicle, как соседние кронджобы:

    POST /cronjob {"cronjob_path": "src/cronjob/e2e_run.py",
                   "metadata": {}, "timeout": 1800}

Разумный срок — раз в сутки, в ночное окно. Чаще незачем: случаи стерегут
вёрстку и содержимое страниц, а те меняются выкладками, а не минутами.

⚠ Таймаут щедрый не зря: на случай × ширину приходится два запуска Chrome
(кадр и живой прогон), каждый — секунды. Десять случаев в трёх ширинах легко
занимают четверть часа.

⚠⚠ Контейнер-браузер этому прогону НЕ нужен: браузер есть в самом контейнере
приложения (playwright ставит его при сборке). Поэтому общий пул вкладок на 25
мест не занимается, и запрет «автоматически — никогда» из `testing_browser.md`
сюда не относится — он про тот пул и про живого Chromium рядом с человеком.

Устройство — `.claude/docs/e2e.md`, каркас — `py_modules/tests_e2e/`.
"""
import asyncio
import json
import sys

from logging_.logging_ import logger_info, logging_init
from mysql_.mysql_ import mysql_pool_close

from src.e2e.e2e_runner import e2e_runner_all
from src.journal.journal_handler import journal_handler_install
from src.journal.journal_mysql import (journal_mysql_watch_start,
                                       journal_mysql_watch_stop)


async def main():
    logging_init()
    journal_handler_install('cronjob')
    await journal_mysql_watch_start('cronjob')

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}

    report = await e2e_runner_all(folder=metadata.get('folder') or '',
                                  base=metadata.get('base') or '')

    # ⚠ Счёт запросов сбрасываем ДО закрытия пула: сброс ходит в базу тем же
    # пулом, и после закрытия ему не на чем ехать.
    await journal_mysql_watch_stop()
    # ⚠ Пул закрываем сами, иначе процесс доживёт до таймаута базы.
    await mysql_pool_close()

    line = (f"E2E: тестов {report['tests']}, провалов {report['failed']}, "
            f"сорвалось {report['errored']}")
    logger_info(f'[e2e] {line}')

    print(line)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
