#!/usr/bin/env python3

import queue
import threading

import chromadb
from chromadb import Settings
from dotenv import load_dotenv
from openai.types.chat import ChatCompletion
from pydantic import ConfigDict

from source.ai.ai_thread import ai_thread_framework_run
from source.faster_whisper_ import faster_whisper_enable
from source.logging_ import logging_adjust, logging_http_adjust
from source.queue import queue_set
from source.window_ import WindowAi

if __name__ == "__main__":
    load_dotenv()

    ChatCompletion.model_config = ConfigDict(extra='allow')
    client = chromadb.Client(Settings(anonymized_telemetry=False))

    logging_adjust()
    logging_http_adjust()

    queue_set({
        'chat': queue.Queue(),
        'task': queue.Queue(),
        'task_abort': queue.Queue(),
        'tool': queue.Queue(),
    })

    faster_whisper_enable()
    window = WindowAi()

    threading.Thread(target=ai_thread_framework_run, args=(window,), daemon=True).start()

    window.mainloop()
