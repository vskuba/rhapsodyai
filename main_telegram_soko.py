#!/usr/bin/env python3

import queue
import threading
import time
import chromadb

from functools import partial
from chromadb import Settings
from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from source.ai.ai_thread import ai_thread_framework_run
from source.logging_ import logging_init
from source.queue_ import queue_set
from source.telegram_bot import init_telegram_bot
from source.thread_ import thread_with_callback

if __name__ == "__main__":
    # 1. Инициализация логов
    logging_init()
    print("Starting MarinaAI in Bot-only mode...")

    ChatCompletion.model_config = ConfigDict(extra='allow')
    client = chromadb.Client(Settings(anonymized_telemetry=False))

    queue_set({
        # 'chat': queue.Queue(),
        # 'chat_response': queue.Queue(),
        # 'chat_input_send': queue.Queue(),
        'task': queue.Queue(),
        # 'task_abort': queue.Queue(),
        # 'task_complete': queue.Queue(),
        # 'tool': queue.Queue(),
        'agent': queue.Queue(),
        'agent_abort': queue.Queue(),
        'agent_response': queue.Queue(),
        'telegram_response': queue.Queue(),
    })

    threading.Thread(target=ai_thread_framework_run, args=(None,), daemon=True).start()

    telegram_bot_agent_soko = partial(init_telegram_bot, agent_name='soko')
    thread_with_callback(
        init_func=telegram_bot_agent_soko,
        callback_func=lambda res: print(f"Bot status: {res}")
    )

    print("MarinaAI Bot is running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")