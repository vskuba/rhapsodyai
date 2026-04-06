#!/usr/bin/env python3

import queue
import threading

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from source.ai.ai_thread import ai_thread_framework_run
from source.faster_whisper.faster_whisper_ import faster_whisper_enable
from source.logging_ import logging_init
from source.queue_ import queue_set
from source.state import state_set
from source.window_ import WindowAi

if __name__ == "__main__":
    logging_init()

    ChatCompletion.model_config = ConfigDict(extra='allow')

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
    state_set('mode_gui', True)

    threading.Thread(target=ai_thread_framework_run, args=(window,), daemon=True).start()

    window.mainloop()
