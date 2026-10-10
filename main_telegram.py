#!/usr/bin/env python3

import asyncio
import time

from functools import partial
from openai.types.chat import ChatCompletion
from pydantic import ConfigDict

from ai.ai_thread import ai_thread_framework_run
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from logging_.logging_ import logging_init
from queue_.queue_ import queue_init
from dashboard.src.page.journal.journal_install import journal_install_here
from dashboard.src.page.journal.journal_mysql import (journal_mysql_flush_forever,
                                      journal_mysql_watch_start)
from src.telegram_bot import telegram_bot_init
from state.state import state_set
from thread_.thread_ import thread_with_callback


async def telegram_main() -> None:
    """Главный цикл процесса: обработчик очереди плюс сброс счётчика запросов.

    Отдельной функцией, а не `asyncio.run(ai_thread_framework_run(...))` на
    месте: фоновую задачу нельзя завести до того, как цикл событий запущен
    (`create_task` вне работающего цикла падает `RuntimeError: no running event
    loop`), а второй `asyncio.run` завёл бы второй цикл — и пул базы, привязанный
    к первому, перестал бы работать.

    ⚠ Счёт запросов включается здесь же, а не в `__main__`: выключатель живёт
    настройкой в таблице, читать её надо из базы — то есть уже внутри цикла
    событий.
    """
    await journal_mysql_watch_start('telegram')
    asyncio.create_task(journal_mysql_flush_forever('telegram'))
    await ai_thread_framework_run([AiFrameworkAgent()])


if __name__ == "__main__":
    logging_init()
    # Ошибки бота — в общий журнал установки (страница «Журнал»,
    # /admin/journal): свой контейнер, и без этого его падения видны только
    # в его же `docker logs`.
    journal_install_here('telegram')

    print("Starting telegram bot-only mode...")

    ChatCompletion.model_config = ConfigDict(extra='allow')

    # Очереди бота + очереди движка workflow: LLM-шаги идут через ai_framework_model,
    # ответы/ошибки фреймворк кладет в chat
    queue_init([
        'chat',
        'chat_response',
        'chat_input_send',
        'task',
        'task_abort',
        'task_complete',
        'task_continue',
        'tool',
        'agent',
        'agent_abort',
        'agent_response',
        'telegram_response',
        'ai_framework_model',
    ])

    state_set('mode_telegram', True)

    #========== Soko Telegram Bot ==========

    telegram_bot_agent_soko = partial(telegram_bot_init, agent_name='soko')
    thread_with_callback(
        init_func=telegram_bot_agent_soko,
        callback_func=lambda res: print(f"Telegram bot Soko status: {res}")
    )

    # ========== Soko Telegram Bot End ==========

    print("Telegram bot is running. Press Ctrl+C to stop.")
    try:
        # Главный event loop процесса: вечный обработчик очереди ai_framework_model
        # (create_task вне запущенного loop падает RuntimeError: no running event loop)
        asyncio.run(telegram_main())
    except KeyboardInterrupt:
        print("Shutting down...")