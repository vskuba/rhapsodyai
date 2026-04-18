#!/usr/bin/env python3

import queue
import threading

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from fastapi import FastAPI

from contextlib import asynccontextmanager
from ai.ai_thread import ai_thread_framework_run
from logging_.logging_ import logging_init
from queue_.queue_ import queue_set
from source.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai_pydantic.ai_framework_agent_pydantic import AiFrameworkAgentPydantic
from source.ai_pydantic.ai_framework_task_manager_pydantic import AiFrameworkTaskManagerPydantic
from source.ai_pydantic.ai_framework_task_pydantic import AiFrameworkTaskPydantic
from source.routers import chat, index, agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_init()
    print("Starting Web (Fast-Api) mode...")

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
    })

    # Запускаем фоновый поток
    thread = threading.Thread(target=ai_thread_framework_run, args=(
        [
            AiFrameworkAgentPydantic(AiFrameworkAgentManagerPydantic()),
            AiFrameworkTaskPydantic(AiFrameworkTaskManagerPydantic()),
        ],
        None,
    ), daemon=True)
    thread.start()

    print("Background thread started.")

    yield

    # Код здесь выполнится ПРИ ОСТАНОВКЕ (аналог shutdown)
    print("Shutting down background processes...")


app = FastAPI(lifespan=lifespan)

app.state.agent_manager = AiFrameworkAgentManagerPydantic()

app.include_router(chat.router)
app.include_router(index.router)
app.include_router(agent.router)
