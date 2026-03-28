#!/usr/bin/env python3

import queue
import threading
import chromadb

from functools import partial
from chromadb import Settings
from dotenv import load_dotenv
from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from source.ai.ai_thread import ai_thread_framework_run
from source.faster_whisper_ import faster_whisper_enable
from source.logging_ import logging_init
from source.queue_ import queue_set
from source.state import state_set
from source.telegram_bot import init_telegram_bot
from source.thread_ import thread_with_callback
from source.window_ import WindowAi

if __name__ == "__main__":
    load_dotenv()
    logging_init()

    ChatCompletion.model_config = ConfigDict(extra='allow')
    client = chromadb.Client(Settings(anonymized_telemetry=False))

    queue_set({
        'chat': queue.Queue(),
        'chat_response': queue.Queue(),
        'chat_input_send': queue.Queue(),
        'task': queue.Queue(),
        'task_abort': queue.Queue(),
        'task_complete': queue.Queue(),
        'tool': queue.Queue(),
        'agent': queue.Queue(),
        'agent_abort': queue.Queue(),
        'agent_response': queue.Queue(),
        'telegram_response': queue.Queue(),
    })

    faster_whisper_enable()
    window = WindowAi()
    state_set('window', window)

    threading.Thread(target=ai_thread_framework_run, args=(window,), daemon=True).start()

    telegram_bot_agent_soko = partial(init_telegram_bot, agent_name='soko')
    thread_with_callback(
        init_func=telegram_bot_agent_soko,
        callback_func=lambda res: print(f"Bot status: {res}")
    )

    window.mainloop()
