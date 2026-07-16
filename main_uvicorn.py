#!/usr/bin/env python3

import asyncio
import os
import traceback

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from py_modules.ai.ai_thread import ai_thread_framework_run
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
from src.uvicorn.routers import dashboard
from src.uvicorn.routers.agent import agent
from src.uvicorn.routers.auth import auth as auth_router
from src.uvicorn.routers.cronjob import cronjob
from src.uvicorn.routers.fact import fact, fact_collection
from src.uvicorn.routers.llm import llm
from src.uvicorn.routers.node import node
from src.uvicorn.routers.session import session
from src.uvicorn.routers.setting import setting
from src.uvicorn.routers.tool import tool
from src.uvicorn.routers.translate import translate
from src.uvicorn.routers.workflow import workflow, workflow_step, workflow_variable, workflow_trace
from src.uvicorn.routers.user import user
from src.uvicorn.routers.companion import companion
from src.uvicorn.routers.role import role


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
        instance = type(e).__name__
        err_stack = traceback.format_exc()

        # Логируем ошибку с деталями запроса
        logger_info(
            f"❌ Сбой в роутере: {request.url.path}\n"
            f"Ошибка: {str(e)}\n"
            f"Instance: {instance}\n"
            f"Стек вызовов:\n{err_stack}"
        )

        # Если это ошибка лимитов AI или HTTPException c кодом 429
        if instance == 'AgentRateLimitError':
            return JSONResponse(
                status_code=429,
                content={
                    "status": "error",
                    "message": str(e),
                }
            )

        # Некорректный ответ AI-провайдера (502 Bad Gateway — сбой вышестоящего сервиса)
        if instance == 'LlmProviderError':
            return JSONResponse(
                status_code=502,
                content={
                    "status": "error",
                    "message": str(e),
                }
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

    # Разрешаем все OPTIONS запросы (CORS preflight) без авторизации
    if request.method == "OPTIONS":
        return await call_next(request)

    # Allow public paths
    public_paths = {
        "startswith": {
            'ANY': [
                '/docs',
                '/login',
                '/auth/login',
                '/auth/logout',
                '/cronjob',
                '/favicon.ico',
                '/static',
                '/user'
            ],
        },
        "exact": {
            'GET': ['/openapi.json'],
            'POST': ['/agent/list']
        }
    }

    method = request.method

    # 1. Проверка startswith: ищем метод, если его нет — берем 'ANY', если и его нет — пустой список
    startswith_patterns = public_paths['startswith'].get(method, public_paths['startswith'].get('ANY', []))
    is_public_startswith = any(path.startswith(p) for p in startswith_patterns)

    # 2. Проверка точного совпадения
    is_public_exact = path in public_paths['exact'].get(method, [])

    if is_public_startswith or is_public_exact:
        return await call_next(request)

    # Check if user is authenticated via session
    user_id = request.session.get("user_id")
    if not user_id:
        # Если передан X-API-KEY, разрешаем пропустить редирект/блокировку и доверяем авторизацию FastAPI
        if request.headers.get("X-API-KEY") or request.headers.get("x-api-key"):
            return await call_next(request)

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


async def logging_middleware(request: Request, call_next):
    """Log incoming requests and outgoing responses, redacting sensitive headers."""
    import time
    start_time = time.time()

    method = request.method
    path = request.url.path
    query_params = request.url.query

    request_body = await request.body()

    # Подменяем поток, чтобы эндпоинты FastAPI могли прочитать тело заново
    async def receive():
        return {"type": "http.request", "body": request_body, "more_body": False}

    request._receive = receive

    # Copy headers to redact sensitive information
    headers = dict(request.headers)
    for sensitive_header in ['authorization', 'cookie', 'x-api-key']:
        if sensitive_header in headers:
            headers[sensitive_header] = '***'
        # Also check uppercase
        if (upper_header := sensitive_header.upper()) in headers:
            headers[upper_header] = '***'

    # Process request
    response = await call_next(request)

    # 4. Безопасно вычитываем тело ответа (StreamingResponse)
    response_body = b""
    async for chunk in response.body_iterator:
        response_body += chunk

    duration = time.time() - start_time
    status_code = response.status_code

    status_code_icon = '✅'
    if status_code == 400:
        status_code_icon = '⚠️'
    elif status_code == 401:
        status_code_icon = '🔒'
    elif status_code == 403:
        status_code_icon = '⛔'
    elif status_code == 404:
        status_code_icon = '❓'
    elif status_code == 500:
        status_code_icon = '❌'

    response_headers = {str(k): str(v) for k, v in response.headers.items()}

    request_data = f", data: {request_body.decode('utf-8', errors='ignore')}" if len(request_body) > 3 else ''
    response_data = f", data: {response_body.decode('utf-8', errors='ignore')}" if len(response_body) > 0 else ''

    logger_info(
        f"🌐 [HTTP] Request {method} {path}"
        f"{'?' + query_params if query_params else ''}"
        f"{request_data}\n\n"
        f"Response: [{status_code} {status_code_icon}] {duration:.3f}s"
        f"{response_data}\n\n"
        f"Request headers: {headers}\n"
        f"Response headers: {response_headers}"
    )

    # Удаляем content-length, чтобы избежать конфликтов при сборке нового Response
    response_headers.pop("content-length", None)

    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.media_type
    )


middleware = [
    Middleware(
        SessionMiddleware,  # type: ignore
        secret_key=config_get('SESSION_SECRET_KEY'),
        session_cookie="uvicorn_session",
        max_age=3600,
        same_site="lax",
        https_only=False
    ),
    Middleware(BaseHTTPMiddleware, dispatch=logging_middleware),
    Middleware(BaseHTTPMiddleware, dispatch=catch_exceptions_middleware),
    Middleware(
        BaseMessageMiddleware := None or BaseHTTPMiddleware if False else BaseHTTPMiddleware,
        dispatch=auth_middleware
    ),
]

app = FastAPI(lifespan=lifespan, middleware=middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_dir = os.path.dirname(os.path.abspath(__file__))

public_static_path = os.path.join(current_dir, config_get('DATA_DIR'), config_get('UVICORN_DIR'), "public")
jinja2_template_path = os.path.join(current_dir, config_get('DATA_DIR'), config_get('UVICORN_DIR'), "template")

app.state.agent_manager = AiFrameworkAgentManager()
app.state.jinja2_template = Jinja2Templates(directory=jinja2_template_path)

class NoCacheStaticFiles(StaticFiles):
    """Статика без heuristic-кэша браузера: no-cache заставляет ревалидировать
    файл (304 по ETag/Last-Modified, если не менялся) — правки js/css видны
    после обычного обновления страницы, без версионирования импортов."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers['Cache-Control'] = 'no-cache'
        return response


app.mount("/static", NoCacheStaticFiles(directory=public_static_path), name="static")

app.include_router(dashboard.router, include_in_schema=False)
app.include_router(chat.router)
app.include_router(agent.router)
app.include_router(auth_router.router, include_in_schema=False)
app.include_router(user.router, include_in_schema=False)
app.include_router(cronjob.router, include_in_schema=False)
app.include_router(fact.router, include_in_schema=False)
app.include_router(setting.router, include_in_schema=False)
app.include_router(translate.router, include_in_schema=False)
app.include_router(llm.router, include_in_schema=False)
app.include_router(session.router, include_in_schema=False)
app.include_router(node.router, include_in_schema=False)
app.include_router(role.router, include_in_schema=False)
app.include_router(workflow.router, include_in_schema=False)
app.include_router(workflow_step.router, include_in_schema=False)
app.include_router(workflow_variable.router, include_in_schema=False)
app.include_router(workflow_trace.router, include_in_schema=False)
app.include_router(tool.router, include_in_schema=False)
app.include_router(fact_collection.router, include_in_schema=False)
app.include_router(companion.router, include_in_schema=False)
