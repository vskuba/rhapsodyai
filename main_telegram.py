#!/usr/bin/env python3

import queue
import threading
import time

from functools import partial
from openai.types.chat import ChatCompletion
from pydantic import ConfigDict

from ai.ai_thread import ai_thread_framework_run
from logging_.logging_ import logging_init
from queue_.queue_ import queue_set
from source.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai_pydantic.ai_framework_agent_pydantic import AiFrameworkAgentPydantic
from source.telegram_bot import init_telegram_bot
from thread_.thread_ import thread_with_callback

if __name__ == "__main__":
    logging_init()

    print("Starting telegram bot-only mode...")

    ChatCompletion.model_config = ConfigDict(extra='allow')

    queue_set({
        # 'chat': queue.Queue(),
        # 'chat_response': queue.Queue(),
        # 'chat_input_send': queue.Queue(),
        'task': queue.Queue(),
        # 'task_abort': queue.Queue(),
        # 'task_complete': queue.Queue(),
        # 'task_continue': queue.Queue(),
        # 'tool': queue.Queue(),
        'agent': queue.Queue(),
        'agent_abort': queue.Queue(),
        'agent_response': queue.Queue(),
        'telegram_response': queue.Queue(),
    })

    threading.Thread(target=ai_thread_framework_run, args=(
        [
            AiFrameworkAgentPydantic(AiFrameworkAgentManagerPydantic()),
        ],
        None,
    ), daemon=True).start()

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