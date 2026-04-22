#!/usr/bin/env python3

import queue
import threading

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict

from ai.ai_thread import ai_thread_framework_run
from logging_.logging_ import logging_init
from queue_.queue_ import queue_set
from state.state import state_set
from source.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai_pydantic.ai_framework_agent_pydantic import AiFrameworkAgentPydantic
from source.ai_pydantic.ai_framework_task_manager_pydantic import AiFrameworkTaskManagerPydantic
from source.ai_pydantic.ai_framework_task_pydantic import AiFrameworkTaskPydantic
from source.faster_whisper.faster_whisper_ import faster_whisper_enable
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
        'task_continue': queue.Queue(),
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

    threading.Thread(target=ai_thread_framework_run, args=(
        [
            AiFrameworkAgentPydantic(AiFrameworkAgentManagerPydantic()),
            AiFrameworkTaskPydantic(AiFrameworkTaskManagerPydantic()),
         ],
        window,
    ), daemon=True).start()

    window.mainloop()