#!/usr/bin/env python3

import asyncio
import os
import traceback

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from ai.ai_thread import ai_thread_framework_run
from src.ai.ai_tool import ai_tool_sync
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from config.config import config_get
from logging_.logging_ import logging_init, logger_info
from mysql_.migration.mysql_migration_up import mysql_migration_up
from mysql_.mysql_ import mysql_pool_get, mysql_pool_close
from queue_.queue_ import queue_init
from redis_queue.redis_queue import redis_queue_init
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.uvicorn.routers.chat import chat
from src.uvicorn.routers import html
from src.uvicorn.routers.agent import agent
from src.uvicorn.routers.auth import auth as auth_router
from src.uvicorn.routers.cronjob import cronjob
from src.uvicorn.routers.fact import fact, fact_collection
from src.uvicorn.routers.llm import llm
from src.uvicorn.routers.node import node
from src.uvicorn.routers.session import session
from src.uvicorn.routers.setting import setting
from src.uvicorn.routers.tool import tool
from src.uvicorn.routers.workflow import workflow, workflow_step
from src.uvicorn.routers.user import user


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_init()
    mysql_migration_up()
    await mysql_pool_get()

    print("Starting Uvicorn (Fast-Api) mode...")

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
        'agent_abort',
        'agent_response',
        'ai_framework_model',
    ])

    redis_queue_init([
        'default',
    ])

    # ======================== Chat ===========================

    asyncio.create_task(ai_thread_framework_run(
        [
            AiFrameworkAgent()
        ]
    ))

    await ai_tool_sync()

    print("Background thread started.")

    # ======================== Chat End ===========================

    yield

    await mysql_pool_close()

    # Код здесь выполнится ПРИ ОСТАНОВКЕ (аналог shutdown)
    print("Shutting down background processes...")


async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        # Формируем полный стек ошибки
        err_stack = traceback.format_exc()

        # Логируем ошибку с деталями запроса
        logger_info(
            f"❌ Сбой в роутере: {request.url.path}\n"
            f"Ошибка: {str(e)}\n"
            f"Стек вызовов:\n{err_stack}"
        )

        # Возвращаем клиенту понятный JSON, чтобы фронтенд не гас
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Внутренняя ошибка сервера",
                "details": str(e)  # В продакшене лучше скрыть детали
            }
        )


async def auth_middleware(request: Request, call_next):
    """Redirect unauthenticated users to login page for admin routes."""
    path = request.url.path

    # Allow public paths
    public_paths = ['/login', '/auth/login', '/auth/logout', '/cronjob', '/favicon.ico', '/static']
    if any(path.startswith(p) for p in public_paths):
        return await call_next(request)

    # Check if user is authenticated via session
    user_id = request.session.get("user_id")
    if not user_id:
        # For HTML routes, redirect to login
        if path.startswith('/admin') or path == '/':
            from starlette.responses import RedirectResponse
            return RedirectResponse(url='/login')
        # For API routes, return 401
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Not authenticated"}
        )

    return await call_next(request)


middleware = [
    Middleware(
        SessionMiddleware,  # type: ignore
        secret_key=config_get('SESSION_SECRET_KEY'),
        session_cookie="uvicorn_session",
        max_age=3600,
        same_site="lax",
        https_only=False
    ),
    Middleware(BaseHTTPMiddleware, dispatch=catch_exceptions_middleware),
    Middleware(BaseHTTPMiddleware, dispatch=auth_middleware),
]

app = FastAPI(lifespan=lifespan, middleware=middleware)


current_dir = os.path.dirname(os.path.abspath(__file__))

public_static_path = os.path.join(current_dir, config_get('DATA_DIR'), config_get('UVICORN_DIR'), "public")
jinja2_template_path = os.path.join(current_dir, config_get('DATA_DIR'), config_get('UVICORN_DIR'), "template")

app.state.agent_manager = AiFrameworkAgentManager()
app.state.jinja2_template = Jinja2Templates(directory=jinja2_template_path)

app.mount("/static", StaticFiles(directory=public_static_path), name="static")

app.include_router(html.router, include_in_schema=False)
app.include_router(chat.router)
app.include_router(agent.router, include_in_schema=False)
app.include_router(auth_router.router, include_in_schema=False)
app.include_router(user.router, include_in_schema=False)
app.include_router(cronjob.router, include_in_schema=False)
app.include_router(fact.router, include_in_schema=False)
app.include_router(setting.router, include_in_schema=False)
app.include_router(llm.router, include_in_schema=False)
app.include_router(session.router, include_in_schema=False)
app.include_router(node.router, include_in_schema=False)
app.include_router(workflow.router, include_in_schema=False)
app.include_router(workflow_step.router, include_in_schema=False)
app.include_router(tool.router, include_in_schema=False)
app.include_router(fact_collection.router, include_in_schema=False)