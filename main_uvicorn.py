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

from src.tool.env.env_ import env_is_prod
from py_modules.ai.ai_thread import ai_thread_framework_run
from src.ai.ai_tool import ai_tool_sync
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from config.config import config_get
from logging_.logging_ import logging_init, logger_info
from mysql_.migration.mysql_migration_up import mysql_migration_up
from mysql_.mysql_ import mysql_pool_get, mysql_pool_close
from src.mysql_.seed.mysql_seed_up import mysql_seed_up
from queue_.queue_ import queue_init
from redis_queue.redis_queue import redis_queue_init
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.ai.ai_workflow_trace import workflow_trace_runs_stale_close
from src.event.event_handlers import event_handlers_register
from src.telegram_.telegram_notify import telegram_notify_bot_setup
from src.uvicorn.routers.chat import chat
from src.uvicorn.routers import dashboard
from src.uvicorn.routers.event import event as event_router
from src.uvicorn.routers.agent import agent
from src.uvicorn.routers.auth import auth as auth_router
from src.uvicorn.routers.cronjob import cronjob
from src.uvicorn.routers.fact import fact, fact_collection
from src.uvicorn.routers.plan import plan
from src.uvicorn.routers.project import (
    project_planning as project_router,
    project_idea,
    project_prototype as project_prototype_router,
    project_document,
    project_task,
    project_task_pipeline,
    project_phase_source,
    project as project_admin,
)
from src.uvicorn.routers.project.design import design_block, design as design_router, design_browser, \
    design_prototype as design_prototype_router
from src.uvicorn.routers.llm import llm
from src.uvicorn.routers.node import node
from src.uvicorn.routers.session import session
from src.uvicorn.routers.setting import setting
from src.uvicorn.routers.telegram_app import telegram_app
from src.uvicorn.routers.telegram_app import telegram_app_chat
from src.uvicorn.routers.telegram_app import telegram_app_claude
from src.uvicorn.routers.telegram_app import telegram_app_claude_session
from src.uvicorn.routers.telegram_app import telegram_app_plan
from src.uvicorn.routers.tool import tool
from src.uvicorn.routers.translate import translate
from src.uvicorn.routers.workflow import workflow, workflow_step, workflow_variable, workflow_trace
from src.uvicorn.routers.user import user
from src.uvicorn.routers.companion import companion
from src.uvicorn.routers.role import role
from src.uvicorn.routers.detective import detective
from src.uvicorn.routers.seed import seed
from src.uvicorn.routers.backup import backup
from src.uvicorn.routers.project import project_team as project_team_router
from src.uvicorn.routers.playwright import playwright
from src.uvicorn.routers.browser import (browser_author, browser_error, browser_proxy,
                                         browser_record, browser_scenario, browser_site,
                                         browser_workflow)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_init()
    mysql_migration_up()
    mysql_seed_up()
    await mysql_pool_get()

    print("Starting Uvicorn (Fast-Api) mode...")

    ChatCompletion.model_config = ConfigDict(extra='allow')

    event_handlers_register()
    await telegram_notify_bot_setup()

    await workflow_trace_runs_stale_close()

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
        'default',  # конвейер задач — контейнер worker
        'planning',  # цепочки фаз планирования — контейнер worker_planning
    ])

    # ======================== Chat ===========================

    asyncio.create_task(ai_thread_framework_run(
        [
            AiFrameworkAgent()
        ]
    ))

    # force=True: без этого синк молча пропускается, если в tool уже есть
    # хоть одна запись (а после первого деплоя она есть всегда) - новые/
    # переименованные/перемещенные инструменты в коде иначе никогда не
    # попадут в БД без ручного форс-синка (именно так тихо не подхватились
    # mysql_migration_prod_create и env_is_prod после деплоя на прод)
    # ВАЖНО: восстановление планирования идёт ПОСЛЕ sync — ai_tool_sync(force=True)
    # вызывает empty() и временно очищает таблицу tool; если проект встанет в
    # очередь раньше и воркер вызовет _tools_load() в этот момент — получит {}
    # и упадёт с "инструмент не найден".
    if await env_is_prod():
        await ai_tool_sync(force=True)
    else:
        await ai_tool_sync()

    # ======================== Planning worker ================

    # Не запуск воркера, а восстановление: цепочки фаз выполняет контейнер
    # `worker_task` из Redis-очереди. Здесь только чиним фазы, брошенные смертью
    # воркера, и доставляем недоделанные проекты в очередь заново.
    from src.worker.project.planning_worker import planning_worker_recover
    await planning_worker_recover()

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
                '/auth/guest',
                '/cronjob',
                '/favicon.ico',
                '/static',
                '/play',
                '/user',
                '/telegram-app',
            ],
        },
        "exact": {
            'GET': ['/openapi.json', '/events'],
            'DELETE': ['/events'],
            # /api/team/{ping,activate,deactivate} — heartbeat внешней claude-shell,
            # у неё нет сессионной cookie. Читающие GET /api/team и /api/team/types
            # публичными быть не должны: они отдают work_dir, pid и session_uuid.
            'POST': ['/agent/list', '/event-log',
                     '/api/team/ping', '/api/team/activate', '/api/team/deactivate']
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
        # Пришёл токен доступа (`Authorization: Bearer …` либо `X-API-KEY`) или
        # секрет claude-shell — пропускаем, а проверку делает сам роутер
        # (`AuthChecker` / `_require_claude_secret`). Разбор заголовков — общий с
        # `AuthChecker`: две копии этого условия разошлись бы, и заголовок,
        # который роутер принимает, здесь молча отсекался бы (так и было с
        # `Authorization`: до проверки прав запрос не доходил вовсе).
        from src.auth.auth import auth_token_of
        if auth_token_of(request) or request.headers.get("X-Claude-Secret"):
            return await call_next(request)

        # For HTML routes, redirect to login with ?next= for post-login return
        if path.startswith('/admin') or path == '/':
            import urllib.parse
            from starlette.responses import RedirectResponse
            next_path = path
            if request.url.query:
                next_path += '?' + request.url.query
            next_param = urllib.parse.quote(next_path, safe='')
            return RedirectResponse(url=f'/login?next={next_param}')
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
    # x-claude-secret — такой же ключ доступа, как x-api-key: в логи он попадал
    # открытым текстом, хотя пускает к тем же роутерам claude-shell.
    for sensitive_header in ['authorization', 'cookie', 'x-api-key', 'x-claude-secret']:
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

# Ссылки на админ-инструменты в шапке открываются в браузере админа, поэтому ведут на его
# `localhost`: до прод-сервисов он ходит через SSH-туннель (`LocalForward` в
# `~/.ssh/config`), до локальных — напрямую. На сервис одна переменная `<NAME>_PORT` и
# одна ссылка: страница прода даёт прод-порт (туннель), страница локальной установки —
# локальный. Порт у сервиса с обеих сторон одинаковый, но на машине разработчика туннель
# забирает его первым, поэтому локальные контейнеры уведены на соседние
# (`docker-compose.override.yml`), а расхождение записано в `.env.local` этой машины.
# Номеров здесь нет вовсе — все значения из `.env` (список ключей — в `.env.dist`).
UVICORN_TOOL_NAMES = (
    'QDRANT',
    'CRONICLE',
    'OPENSEARCH_DASHBOARDS',
    'RQ_DASHBOARD',
    'PHPMYADMIN',
    'GATUS',
)
for tool_name in UVICORN_TOOL_NAMES:
    tool_key = f'{tool_name}_PORT'
    app.state.jinja2_template.env.globals[tool_key] = config_get(tool_key)

# Grafana живёт вне docker-compose, на отдельной машине — не порт, а целый адрес.
app.state.jinja2_template.env.globals['GRAFANA_URL'] = config_get('GRAFANA_URL')


class NoCacheStaticFiles(StaticFiles):
    """Статика без heuristic-кэша браузера: no-cache заставляет ревалидировать
    файл (304 по ETag/Last-Modified, если не менялся) — правки js/css видны
    после обычного обновления страницы, без версионирования импортов."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers['Cache-Control'] = 'no-cache'
        return response


app.mount("/static", NoCacheStaticFiles(directory=public_static_path), name="static")

# PWA-подпроекты (apps/<name>/) - публичные игровые фронтенды, отдаются
# статикой по /play/<name>/. html=True - индекс отдается на корне папки
# (нужно для start_url/scope PWA-манифеста и открытия без явного /index.html)
apps_static_path = os.path.join(current_dir, "apps")
if os.path.isdir(apps_static_path):
    app.mount("/play", NoCacheStaticFiles(directory=apps_static_path, html=True), name="play")

app.include_router(detective.router)
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
app.include_router(plan.router, include_in_schema=False)
app.include_router(project_router.router, include_in_schema=False)
app.include_router(project_idea.router, include_in_schema=False)
app.include_router(design_block.router, include_in_schema=False)
app.include_router(project_prototype_router.router, include_in_schema=False)
app.include_router(project_document.router, include_in_schema=False)
app.include_router(project_task.router, include_in_schema=False)
app.include_router(project_task_pipeline.router, include_in_schema=False)
app.include_router(project_phase_source.router, include_in_schema=False)
app.include_router(project_admin.router, include_in_schema=False)
app.include_router(design_browser.router, include_in_schema=False)
app.include_router(design_router.router, include_in_schema=False)
app.include_router(design_prototype_router.router, include_in_schema=False)
app.include_router(companion.router, include_in_schema=False)
app.include_router(telegram_app.router, include_in_schema=False)
app.include_router(telegram_app_chat.router, include_in_schema=False)
app.include_router(telegram_app_claude.router, include_in_schema=False)
app.include_router(telegram_app_claude_session.router, include_in_schema=False)
app.include_router(telegram_app_plan.router, include_in_schema=False)
app.include_router(event_router.router, include_in_schema=False)
app.include_router(seed.router, include_in_schema=False)
app.include_router(backup.router, include_in_schema=False)
app.include_router(project_team_router.router, include_in_schema=False)
app.include_router(playwright.router, include_in_schema=False)
app.include_router(browser_proxy.router, include_in_schema=False)
app.include_router(browser_scenario.router, include_in_schema=False)
app.include_router(browser_author.router, include_in_schema=False)
app.include_router(browser_record.router, include_in_schema=False)
app.include_router(browser_site.router)
app.include_router(browser_workflow.router)
app.include_router(browser_error.router)