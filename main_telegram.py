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
from src.journal.journal_handler import journal_handler_install
from src.telegram_bot import telegram_bot_init
from state.state import state_set
from thread_.thread_ import thread_with_callback

if __name__ == "__main__":
    logging_init()
    # Ошибки бота — в общий журнал установки (страница «Журнал»,
    # /admin/journal): свой контейнер, и без этого его падения видны только
    # в его же `docker logs`.
    journal_handler_install('telegram')

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
        asyncio.run(ai_thread_framework_run(
            [
                AiFrameworkAgent(),
            ]
        ))
    except KeyboardInterrupt:
        print("Shutting down...")