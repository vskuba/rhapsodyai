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
from src.telegram_bot import init_telegram_bot
from state.state import state_set
from thread_.thread_ import thread_with_callback

if __name__ == "__main__":
    logging_init()

    print("Starting telegram bot-only mode...")

    ChatCompletion.model_config = ConfigDict(extra='allow')

    queue_init([
        'task',
        'agent',
        'agent_abort',
        'agent_response',
        'telegram_response'
    ])

    asyncio.create_task(ai_thread_framework_run(
        [
            AiFrameworkAgent(),
        ]
    ))

    state_set('mode_telegram', True)

    #========== Soko Telegram Bot ==========

    telegram_bot_agent_soko = partial(init_telegram_bot, agent_name='soko')
    thread_with_callback(
        init_func=telegram_bot_agent_soko,
        callback_func=lambda res: print(f"Telegram bot Soko status: {res}")
    )

    # ========== Soko Telegram Bot End ==========

    print("Telegram bot is running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")