#!/usr/bin/env python3

import asyncio
import threading

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict

from ai.ai_thread import ai_thread_framework_run
from logging_.logging_ import logging_init
from queue_.queue_ import queue_init
from state.state import state_set
from src.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from src.ai_pydantic.ai_framework_agent_pydantic import AiFrameworkAgentPydantic
from src.ai_pydantic.ai_framework_task_manager_pydantic import AiFrameworkTaskManagerPydantic
from src.ai_pydantic.ai_framework_task_pydantic import AiFrameworkTaskPydantic
from src.faster_whisper.faster_whisper_ import faster_whisper_enable
from src.window_ import WindowAi


def ai_framework_run(window):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(ai_thread_framework_run(
        [
            AiFrameworkAgentPydantic(AiFrameworkAgentManagerPydantic()),
            AiFrameworkTaskPydantic(AiFrameworkTaskManagerPydantic()),
        ],
        window
    ))


if __name__ == "__main__":
    logging_init()

    ChatCompletion.model_config = ConfigDict(extra='allow')

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
        'telegram_response'
    ])

    faster_whisper_enable()
    window = WindowAi()
    state_set('window', window)
    state_set('mode_gui', True)

    threading.Thread(target=ai_framework_run, args=(window,), daemon=True).start()

    window.mainloop()