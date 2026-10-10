#!/usr/bin/env python3

import asyncio
import json
import os

from openai.types.chat import ChatCompletion
from pydantic import ConfigDict
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from starlette.templating import Jinja2Templates
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src.tool.env.env_ import env_is_prod
from ai.ai_thread import ai_thread_framework_run
from src.ai.ai_tool import ai_tool_sync
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from config.config import config_get
from logging_.logging_ import logging_init, logger_exception, logger_info
from mysql_.migration.mysql_migration_up import mysql_migration_up
from mysql_.mysql_ import mysql_pool_get, mysql_pool_close
from mysql_.mysql_seed import mysql_seed_up
from queue_.queue_ import queue_init
from panel_.panel_backup_api import panel_backup_api_router
from panel_.panel_static import panel_static_files
from panel_.panel_user_api import panel_user_api_router
from panel_.panel_seed_api import panel_seed_api_router
from panel_.panel_setting_api import panel_setting_api_router
from redis_.redis_queue import redis_queue_init
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.ai.ai_workflow_trace import ai_workflow_trace_runs_stale_close
from src.auth.auth_permission import AuthPermission
from src.auth.auth_store import AUTH_STORE_EXTRA
from src.auth.auth_session_slide import auth_session_slide_touch

# Таблицы, которые в списке seed **есть, но не отмечены**: их наполняет работа
# установки, а не человек — сессии, трассы, журналы, замки, метрики задач.
#
# ⚠ Собрано не на глаз: это ровно то, что оставалось неотмеченным в прежней
# серверной памяти выбора (`seed_table_config`). Сама память убрана — выбор
# таблиц держать в базе значит платить схемой за галочку, и общий скелет его не
# хранит; умолчание считает сервер, остальное помнит страница.
#
# ⚠ Живёт здесь, а не в слое: какие таблицы рабочие, знает установка.
MAIN_UVICORN_SEED_RUNTIME = (
    'agent_session', 'agent_workflow_history', 'agent_workflow_trace',
    'agent_workflow_trace_step', 'ai_claude_session',
    'ai_claude_session_registry', 'browser_error', 'browser_proxy',
    'browser_scenario_run', 'companion', 'companion_session', 'detective_case',
    'developing_project', 'developing_task', 'event_log', 'fact', 'journal',
    'journal_mysql', 'llm_request', 'migration_manual_log', 'plan',
    'project_design_prototype_page', 'project_design_prototype_page_block',
    'project_design_prototype_widget', 'project_planning_document',
    'project_task_attempt', 'project_task_depend', 'project_task_metric',
    'project_task_plan_revision', 'session', 'team_llm_lock', 'team_shell_lock',
    'test_e2e', 'test_e2e_case', 'tool', 'tool_group')
from src.journal.journal_handler import journal_handler_install
from src.journal.journal_mysql import (journal_mysql_flush_forever,
                                       journal_mysql_watch_start)
from src.event.event_handlers import event_handlers_register
from src.telegram_.telegram_notify import telegram_notify_bot_setup
from src.uvicorn.routers.chat import chat
from src.uvicorn.routers import dashboard
from src.uvicorn.routers.cronicle import cronicle as cronicle_router
from src.uvicorn.routers.e2e import e2e as e2e_router
from src.uvicorn.routers.journal import journal as journal_router
from src.uvicorn.routers.journal import journal_mysql as journal_mysql_router
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
    project_task_metric,
    project_task_migration,
    project_task_question,
    project_phase_source,
    project as project_admin,
)
from src.uvicorn.routers.project.design import design_block, design as design_router, design_browser, \
    design_prototype as design_prototype_router
from src.uvicorn.routers.llm import llm
from src.uvicorn.routers import gx10
from src.uvicorn.routers.node import node
from src.uvicorn.routers.session import session
# Вкладка «Чат» страницы «Сессии»: разговоры пары (`companion_session`).
# Подключается РАНЬШЕ соседа — см. комментарий у `include_router`.
from src.uvicorn.routers.session import session_companion
from src.uvicorn.routers.setting import setting
from src.uvicorn.routers.telegram_app import telegram_app
from src.uvicorn.routers.telegram_app import telegram_app_chat
from src.uvicorn.routers.telegram_app import telegram_app_claude
from src.uvicorn.routers.telegram_app import telegram_app_claude_session
from src.uvicorn.routers.telegram_app import telegram_app_plan
from src.uvicorn.routers.telegram_app import telegram_app_task
from src.uvicorn.routers.tool import tool
from src.uvicorn.routers.translate import translate
from src.uvicorn.routers.workflow import (workflow, workflow_step, workflow_variable,
                                         workflow_trace, workflow_history, workflow_branch)
# Порядок регистрации важен: `/workflow/export` и `/workflow/import` обязаны
# стоять до `workflow.router`, где живёт `GET /workflow/{workflow_id:int}` —
# иначе «export» проглотится параметром пути, ответит 422 и до точки не дойдёт.
from src.uvicorn.routers.workflow import workflow_export
from src.uvicorn.routers.workflow import workflow_import
from src.uvicorn.routers.user import user
from src.uvicorn.routers.companion import companion
from src.uvicorn.routers.role import role
from src.uvicorn.routers.detective import detective
from src.uvicorn.routers.project import project_team as project_team_router
from src.uvicorn.routers.playwright import playwright
from src.uvicorn.routers.stt import stt
from src.uvicorn.routers.blog import blog as blog_router
from src.uvicorn.routers.browser import (browser_author, browser_error, browser_proxy,
                                         browser_proxy_net, browser_record, browser_scenario,
                                         browser_site, browser_site_variable)

# По какой таблице seed решает, что база пуста. `node` — узлы LLM: без них
# установка не работает вовсе, и заполняет их как раз seed. Имя живёт здесь,
# потому что общий слой (`mysql_seed`) схемы этого проекта не знает и знать
# не должен.
MYSQL_SEED_PROBE_TABLE = 'node'

# Сколько живёт сессия админки без единого запроса. Окно скользящее
# (`session_slide_middleware`), поэтому это «четыре часа простоя», а не «четыре
# часа с момента входа»: работающего человека сессия не выбрасывает вовсе.
SESSION_MAX_AGE = 14400


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_init()
    # Журнал ошибок установки: всё, что пишется в логи уровнем ERROR, начиная
    # отсюда попадает и в таблицу `journal` — страница «Журнал»
    # (/admin/journal). Ставится рядом с `logging_init`, потому что
    # подвешивается к тем же логгерам; порядок важен — до него ошибки видны
    # только в `docker logs`.
    journal_handler_install('uvicorn')
    mysql_migration_up()
    mysql_seed_up(MYSQL_SEED_PROBE_TABLE)
    await mysql_pool_get()

    # Журнал запросов к базе — соседняя подвкладка той же страницы. Считает
    # счётчик в памяти процесса, сбрасывает в таблицу фоновая задача ниже.
    #
    # ⚠ Только ПОСЛЕ миграций: выключатель живёт настройкой в таблице `setting`,
    # а на свежей установке её заводят те же миграции. Рядом с
    # `journal_handler_install` вызов стоять не может — там базы ещё нет.
    await journal_mysql_watch_start('uvicorn')

    print("Starting Uvicorn (Fast-Api) mode...")

    ChatCompletion.model_config = ConfigDict(extra='allow')

    event_handlers_register()
    await telegram_notify_bot_setup()

    await ai_workflow_trace_runs_stale_close()

    # Сброс счётчика запросов в таблицу раз в полминуты. Отдельной задачей, а не
    # при показе страницы: страницу открывают редко, а знать надо про то, что
    # происходило, пока на неё никто не смотрел.
    asyncio.create_task(journal_mysql_flush_forever('uvicorn'))

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

        # ⚠ `logger_exception`, а не `logger_info`: уровнем INFO сбой роутера не
        # доходил до журнала ошибок (`journal`) — тот слушает ERROR, — и 500-е
        # были видны только в `docker logs`. Трассировку сюда больше не
        # подклеиваем руками: её кладёт в запись сам логгер (`exc_info`), а
        # журнал забирает оттуда в отдельную колонку.
        logger_exception(
            f"❌ Сбой в роутере: {request.url.path}\n"
            f"Ошибка: {str(e)}\n"
            f"Instance: {instance}"
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


async def session_slide_middleware(request: Request, call_next):
    """Продлевает сессию по активности: срок считается от последнего запроса.

    Вся логика — в `auth_session_slide_touch` (там же, почему метка огрублена и
    чем это отличается по версиям Starlette). Здесь только место вызова: после
    ответа, чтобы свежий `Set-Cookie` попал в уже сформированные заголовки.
    """
    response = await call_next(request)

    try:
        session = request.session
    except AssertionError:
        # `SessionMiddleware` не в цепочке (так бывает у приложения, собранного
        # без него) — продлевать нечего.
        return response

    auth_session_slide_touch(session)

    return response


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

    # Тело маскируется так же, как заголовки выше: пароль из формы логина попадал в
    # лог контейнера открытым текстом, а оттуда logstash разносил его в OpenSearch.
    request_data = f", data: {_body_redact(request_body)}" if len(request_body) > 3 else ''
    response_data = f", data: {_body_redact(response_body)}" if len(response_body) > 0 else ''

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
        # Четыре часа **простоя**: окно скользящее, его двигает
        # `session_slide_middleware` ниже. Был час и от входа — он кончался
        # посреди работы, и выглядело это не как «сессия истекла», а как поломка
        # сервера: страница админки остаётся открытой (её маршрут проверяет вход
        # только при переходе), а запросы к API начинают отвечать 401 — панели
        # молча пустеют. Дважды приняли за отказ базы.
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=False
    ),
    # ⚠ Продление стоит ПОСЛЕ `SessionMiddleware` в списке — то есть **внутри**
    # него в цепочке вызовов. Middleware оборачивают друг друга в порядке
    # объявления: первый снаружи. Окажись продление выше — оно правило бы
    # сессию, которой ещё нет, и падало бы на `request.session`.
    Middleware(BaseHTTPMiddleware, dispatch=session_slide_middleware),
    Middleware(BaseHTTPMiddleware, dispatch=logging_middleware),
    Middleware(BaseHTTPMiddleware, dispatch=catch_exceptions_middleware),
    Middleware(
        BaseMessageMiddleware := None or BaseHTTPMiddleware if False else BaseHTTPMiddleware,
        dispatch=auth_middleware
    ),
]

# `docs_url=None` — встроенную страницу Swagger отключаем и собираем свою ниже
# (`swagger_ui_docs`): готовая тянет скрипт, стили и даже favicon с чужих доменов, а
# зависимости у нас лежат локально (`docs-common/frontend_rules.md`). Схема
# (`/openapi.json`) и `/redoc` остаются штатными — их адреса не переопределяются.
app = FastAPI(lifespan=lifespan, middleware=middleware, docs_url=None)

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


# ⚠ Общая статика — submodule `dashboard` рядом с `py_modules`: раздача ищет
# файл сперва у нас, потом там. Свой файл с тем же именем перекрывает общий.
app.mount("/static",
          panel_static_files(public_static_path,
                             shared=os.path.join(current_dir, "dashboard")),
          name="static")


@app.get('/docs', include_in_schema=False)
async def swagger_ui_docs():
    """
    Swagger UI на локальных файлах, без похода к чужим доменам.

    Встроенная страница FastAPI собирается из трёх внешних адресов: скрипт и стили с
    `cdn.jsdelivr.net`, favicon — с `fastapi.tiangolo.com`. Это внешняя точка отказа
    (нет интернета — нет документации), утечка факта захода к третьей стороне и
    плавающая версия: тег `@5` завтра отдаст другую сборку. Все три лежат теперь в
    статике репозитория, версия зафиксирована — см. «Документация API» в
    `.claude/docs/quickstart.md`.

    Адрес монтируется вручную, потому что `docs_url=None` у приложения: держать
    встроенный роут и свой одновременно нельзя — они спорят за один путь.
    """
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f'{app.title} — API',
        swagger_js_url='/static/js/vendor/swagger-ui-bundle.js',
        swagger_css_url='/static/css/vendor/swagger-ui.css',
        swagger_favicon_url='/static/assets/swagger-favicon.png',
    )

# PWA-подпроекты (apps/<name>/) - публичные игровые фронтенды, отдаются
# статикой по /play/<name>/. html=True - индекс отдается на корне папки
# (нужно для start_url/scope PWA-манифеста и открытия без явного /index.html)
apps_static_path = os.path.join(current_dir, "apps")
if os.path.isdir(apps_static_path):
    app.mount("/play", panel_static_files(apps_static_path, html=True), name="play")

app.include_router(detective.router)
app.include_router(dashboard.router, include_in_schema=False)
app.include_router(chat.router)
# Расшифровка речи для соседних проектов (BlogAi / Блокнот): см. stt.py
app.include_router(stt.router)
# Агенты «Блокнота» под нодой Blog: разметка черновиков для BlogAi
app.include_router(blog_router.router)
app.include_router(agent.router)
app.include_router(auth_router.router, include_in_schema=False)
app.include_router(user.router, include_in_schema=False)
app.include_router(panel_user_api_router(
    view=AuthPermission.USER_VIEW, manage=AuthPermission.USER_UPDATE,
    extra_fields=AUTH_STORE_EXTRA), include_in_schema=False)
app.include_router(cronjob.router, include_in_schema=False)
app.include_router(fact.router, include_in_schema=False)
app.include_router(setting.router, include_in_schema=False)
app.include_router(panel_setting_api_router(
    view=AuthPermission.SETTING_VIEW, manage=AuthPermission.SETTING_UPDATE),
    include_in_schema=False)
app.include_router(translate.router, include_in_schema=False)
app.include_router(llm.router, include_in_schema=False)
app.include_router(gx10.router, include_in_schema=False)
# ⚠ Разговоры пары — раньше журнала вызовов. У соседа объявлен
# `DELETE /session/{session_uuid}`, и путь `/session/companion/...` под этим
# шаблоном читается как uuid сессии: подключись сосед первым, добавленная позже
# ручка под `/session/companion/` с методом DELETE попала бы не туда. Тот же
# порядок и по той же причине, что у подвкладок журнала.
app.include_router(session_companion.router, include_in_schema=False)
app.include_router(session.router, include_in_schema=False)
app.include_router(node.router, include_in_schema=False)
app.include_router(role.router, include_in_schema=False)
# Экспорт/импорт — до остального workflow-роутера: см. комментарий на импорте.
app.include_router(workflow_export.router, include_in_schema=False)
app.include_router(workflow_import.router, include_in_schema=False)
app.include_router(workflow.router, include_in_schema=False)
app.include_router(workflow_step.router, include_in_schema=False)
app.include_router(workflow_variable.router, include_in_schema=False)
app.include_router(workflow_trace.router, include_in_schema=False)
app.include_router(workflow_history.router, include_in_schema=False)
app.include_router(workflow_branch.router, include_in_schema=False)
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
app.include_router(project_task_metric.router, include_in_schema=False)
app.include_router(project_task_migration.router, include_in_schema=False)
app.include_router(project_task_question.router, include_in_schema=False)
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
app.include_router(telegram_app_task.router, include_in_schema=False)
app.include_router(event_router.router, include_in_schema=False)
# ⚠⚠ Журнал запросов подключается РАНЬШЕ журнала ошибок, и порядок здесь не
# косметика: у соседа объявлено `DELETE /api/journal/{record_id}` с номером
# записи числом, и подключись он первым — на `DELETE /api/journal/mysql` FastAPI
# попытался бы прочитать «mysql» номером и ответил бы 422 вместо чистки.
app.include_router(journal_mysql_router.router, include_in_schema=False)
app.include_router(journal_router.router, include_in_schema=False)
app.include_router(e2e_router.router, include_in_schema=False)
app.include_router(cronicle_router.router, include_in_schema=False)
app.include_router(panel_seed_api_router(
    runtime_tables=MAIN_UVICORN_SEED_RUNTIME, title='RhapsodyAi',
    view=AuthPermission.SETTING_VIEW, manage=AuthPermission.SETTING_UPDATE),
    include_in_schema=False)
app.include_router(panel_backup_api_router(
    view=AuthPermission.SETTING_VIEW, manage=AuthPermission.SETTING_UPDATE),
    include_in_schema=False)
app.include_router(project_team_router.router, include_in_schema=False)
app.include_router(playwright.router, include_in_schema=False)
# Браузер наружу: этими точками работает DatingAi — заводит сессию, гоняет по ней
# сценарии, снимает `storage_state`. Скрытыми они были по недосмотру: документация
# показывала картину, обратную настоящей.
app.include_router(browser_proxy.router)
# ⚠ Реестр выходов — **до** `browser_proxy`, чей префикс `/api/browser`: пути
# разбираются по порядку, и `/api/browser/proxy/claim` при обратном порядке
# однажды прочитался бы как сессия с именем «proxy».
app.include_router(browser_proxy_net.router)
app.include_router(browser_scenario.router)
app.include_router(browser_site.router)
app.include_router(browser_site_variable.router)
app.include_router(browser_error.router)
# Запись сценария и его переписывание агентом — работа со страницы `/admin/browser`,
# руками человека. Наружу их никто не зовёт, в документации они были бы шумом.
app.include_router(browser_author.router, include_in_schema=False)
app.include_router(browser_record.router, include_in_schema=False)


# Ключи, значение которых в лог не попадает никогда. Сверять с телом запроса дословно
# нельзя: имена приходят и в camelCase, и с префиксом (`new_password`, `apiKey`), поэтому
# совпадение ищется по вхождению подстроки в имя, приведённое к нижнему регистру.
UVICORN_LOG_SECRET_KEYS = (
    'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
    'authorization', 'cookie', 'private_key', 'access_key',
)


def _body_redact(body: bytes, limit: int = 20000) -> str:
    """Тело запроса или ответа для лога: значения секретных ключей заменены на `***`.

    JSON разбирается и собирается заново — так маскировка не зависит от форматирования
    и переживает вложенность (`{"user": {"password": ...}}`). Не-JSON (форма, бинарь,
    HTML страницы) остаётся как есть: разобрать его нельзя, а вырезать вслепую значит
    испортить лог. Единственное исключение — тело формы с `password=`, оно вырезается
    целиком, потому что это ровно тот случай, ради которого функция написана.
    """
    text = body.decode('utf-8', errors='ignore')

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # form-urlencoded с паролем: разбирать незачем, достаточно не печатать
        if 'password=' in text.lower():
            return '<скрыто: тело формы с паролем>'
        return text[:limit]

    redacted = _secrets_mask(parsed)
    return json.dumps(redacted, ensure_ascii=False)[:limit]


def _secrets_mask(value):
    """Рекурсивно заменяет значения секретных ключей на `***`, сохраняя структуру."""
    if isinstance(value, dict):
        masked = {}
        for key, inner in value.items():
            key_lower = str(key).lower()
            if any(secret in key_lower for secret in UVICORN_LOG_SECRET_KEYS):
                masked[key] = '***'
            else:
                masked[key] = _secrets_mask(inner)
        return masked
    if isinstance(value, list):
        return [_secrets_mask(item) for item in value]
    return value