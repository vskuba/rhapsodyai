import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse

from ai.ai_llm import ai_llm_node_get
from config.config import config_get
from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.faster_whisper.faster_whisper_model import faster_whisper_transcribe
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.ai_claude_session_registry_repository import AiClaudeSessionRegistryRepository
from src.mysql_.repository.event_log_repository import EventLogRepository
from src.telegram_.telegram_notify import telegram_send_owner
from src.tool.claude_.claude_ import claude_message_cloud, claude_message_user

router = APIRouter()

agent_manager = AiFrameworkAgentManager()

# Владелец бота (тот же user_id, что и в telegram_bot.py) - его LLM-очередь
# используется для ответов ассистента в Mini App
TELEGRAM_CHAT_USER_ID = 1
TELEGRAM_CHAT_AGENT_NAME = 'telegram_assistant'

# Отдельный чат Mini App для общения с Claude Code (не LLM-ассистент) - свой
# агент/workflow/история, не смешивается с TELEGRAM_CHAT_AGENT_NAME
TELEGRAM_CLAUDE_AGENT_NAME = 'telegram_claude'

# Спец-контент сообщения ai_claude_session, которым Mini App будит
# поставленную на паузу сессию (см. wake-request ниже) - терминал должен
# распознать этот маркер и не отвечать на него как на обычный промпт
SESSION_WAKE_MARKER = '__SESSION_WAKE__'

# companion обязателен для записи истории (agent_session.companion_id FK) -
# переиспользуем существующего 'user_admin' (id=3), другой companion не нужен
TELEGRAM_CHAT_COMPANION_ID = 3
TELEGRAM_CHAT_COMPANION_NAME = 'user_admin'
TELEGRAM_CHAT_COMPANION_TITLE = 'admin'

# initData считается валидным не дольше суток - защита от повторного
# использования старой открытой сессии Mini App (replay)
INIT_DATA_MAX_AGE_SECONDS = 24 * 3600


@router.get("/telegram-app", response_class=HTMLResponse)
async def telegram_app_page(request: Request):
    # Telegram WebView кэширует эту страницу агрессивнее обычного браузера и
    # игнорирует стандартные заголовки без явного no-store - после каждого
    # деплоя фронтенда пользователь иначе видит старую версию до принудительного
    # сброса кэша
    response = request.app.state.jinja2_template.TemplateResponse(request, "telegram_app.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@router.post("/telegram-app/auth")
async def telegram_app_auth(request: Request, data: dict):
    access_token = str(data.get("access_token") or "").strip()

    if access_token:
        # Открытие вне Telegram (обычный браузер, для тестирования) - нет
        # initData для проверки; переиспользуем существующие user_access_token
        # (та же таблица, что и X-API-KEY для остального admin API), но только
        # для владельца (user_id=1) - Mini App не для чужих токенов
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT user_id FROM `user_access_token` WHERE token = %s AND user_id = 1",
                (access_token,)
            )
            row = await db.fetchone()
        if not row:
            raise HTTPException(status_code=403, detail="Invalid access_token")
        telegram_user_id = row["user_id"]
    else:
        telegram_user_id = _telegram_init_data_verify(data.get("init_data", ""))

    request.session["telegram_owner_id"] = telegram_user_id

    return {"result": {"ok": True}}


@router.get("/telegram-app/events")
async def telegram_app_events(request: Request):
    _require_telegram_owner(request)

    repo = EventLogRepository()
    rows = await repo.find_by({}, order_by="created_at DESC")

    return {"result": rows[:50]}


@router.get("/telegram-app/agents")
async def telegram_app_agents(request: Request):
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, name, title, node_id FROM `agent` WHERE dynamic = 0 ORDER BY title")
        rows = await db.fetchall()

    return {"result": rows}


@router.post("/telegram-app/chat/ask")
async def telegram_app_chat_ask(request: Request, data: dict):
    _require_telegram_owner(request)
    return await _telegram_agent_chat_ask(data, TELEGRAM_CHAT_AGENT_NAME)


@router.post("/telegram-app/claude/ask")
async def telegram_app_claude_ask(request: Request, data: dict):
    _require_telegram_owner(request)
    return await _telegram_agent_chat_ask(data, TELEGRAM_CLAUDE_AGENT_NAME)


@router.get("/telegram-app/claude/messages")
async def telegram_app_claude_messages(request: Request, session_uuid: str):
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT role, kind_type, content, created_at
            FROM agent_session
            WHERE session_uuid = %s AND kind_type IN ('user-prompt', 'response-final')
            ORDER BY id ASC
            """,
            (session_uuid,)
        )
        rows = await db.fetchall()

    return {"result": rows}


@router.post("/telegram-app/claude/respond")
async def telegram_app_claude_respond(request: Request, data: dict):
    """
    Вызывается извне (процесс Claude Code, опрашивающий ai_claude_session) -
    не Mini App, поэтому авторизация через общий секрет (заголовок), а не
    сессию владельца.
    """
    _require_claude_secret(request)

    inbox_id = data.get("inbox_id")
    session_uuid = str(data.get("session_uuid") or "").strip()
    response = str(data.get("response") or "").strip()
    if not session_uuid or not response:
        raise HTTPException(status_code=400, detail="session_uuid, response required")

    result = await claude_message_cloud(
        session_uuid=session_uuid,
        response=response,
        inbox_id=int(inbox_id) if inbox_id else None,
    )

    if data.get("notify", True):
        await telegram_send_owner(response)

    return {"result": result}


@router.get("/telegram-app/claude/session/inbox")
async def telegram_app_claude_session_inbox(request: Request, session_uuid: str):
    """
    Непрочитанные сообщения из ai_claude_session для данного session_uuid -
    опрашивается /loop на каждой итерации вместе с heartbeat, чтобы подхватить
    сообщения, отправленные пользователем через чат Claude в Mini App.
    """
    _require_claude_secret(request)

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT id, content, created_at
            FROM ai_claude_session
            WHERE session_uuid = %s AND handled = 0
            ORDER BY id ASC
            """,
            (session_uuid,)
        )
        rows = await db.fetchall()

    return {"result": rows}


@router.get("/telegram-app/claude/sessions")
async def telegram_app_claude_sessions(request: Request, project_label: str):
    """
    Список зарегистрированных сессий (любой статус) для проекта - вызывается
    хуком SessionStart при старте терминала, чтобы показать пользователю
    выбор существующих сессий для резюме. См. .claude/docs/claude_session_registry.md §3.
    """
    _require_claude_secret(request)

    repo = AiClaudeSessionRegistryRepository()
    rows = await repo.find_by({"project_label": project_label}, order_by="last_seen_at DESC, created_at DESC")

    return {"result": rows}


@router.post("/telegram-app/claude/session/register")
async def telegram_app_claude_session_register(request: Request, data: dict):
    """
    Регистрирует новую терминальную сессию - вызывается хуком SessionStart,
    если пользователь не выбрал резюме существующей сессии.
    """
    _require_claude_secret(request)

    role = str(data.get("role") or "developer").strip()
    project_label = str(data.get("project_label") or "").strip()
    if not project_label:
        raise HTTPException(status_code=400, detail="project_label required")

    session_uuid = str(uuid.uuid4())
    repo = AiClaudeSessionRegistryRepository()
    await repo.add({
        "session_uuid": session_uuid,
        "role": role,
        "project_label": project_label,
        "status": "active",
        "last_seen_at": datetime.now(),
    })

    return {"result": {"session_uuid": session_uuid}}


@router.post("/telegram-app/claude/session/resume")
async def telegram_app_claude_session_resume(request: Request, data: dict):
    """
    Резюмирует существующую сессию - помечает active, обновляет heartbeat,
    возвращает историю переписки (тот же источник, что и Mini App чат).
    """
    _require_claude_secret(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update(row["id"], {"status": "active", "last_seen_at": datetime.now()})

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT role, kind_type, content, created_at
            FROM agent_session
            WHERE session_uuid = %s AND kind_type IN ('user-prompt', 'response-final')
            ORDER BY id ASC
            """,
            (session_uuid,)
        )
        messages = await db.fetchall()

    return {"result": {"session": row, "messages": messages}}


@router.post("/telegram-app/claude/session/heartbeat")
async def telegram_app_claude_session_heartbeat(request: Request, data: dict):
    """
    Вызывается /loop на каждой итерации - обновляет last_seen_at и сообщает
    терминалу текущий статус (в частности 'closing', если отключение уже
    запрошено через Telegram).
    """
    _require_claude_secret(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update(row["id"], {"last_seen_at": datetime.now()})

    return {"result": {"status": row["status"]}}


@router.post("/telegram-app/claude/session/finalize")
async def telegram_app_claude_session_finalize(request: Request, data: dict):
    """
    Финальная уборка сессии - вызывается /loop, увидевшим status='closing' на
    heartbeat, после того как сам сгенерировал краткое summary переписки.
    """
    _require_claude_secret(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    summary = data.get("summary")
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    update_data = {"status": "inactive", "closed_at": datetime.now()}
    if summary:
        update_data["summary"] = str(summary)[:500]
    await repo.update(row["id"], update_data)

    return {"result": {"ok": True}}


@router.get("/telegram-app/claude/sessions/active")
async def telegram_app_claude_sessions_active(request: Request):
    """
    Сессии для иконок во вкладке Cloud Mini App - видимость решает только
    staleness heartbeat (см. .claude/docs/claude_session_registry.md §4),
    не поле status: фоновый процесс `session_client.py watch` пингует
    heartbeat каждые ~30с всё время, пока жив терминал, вне зависимости от
    того, активна сессия или на паузе - поэтому 60с (2x интервал) без пинга
    надёжно значит "терминал реально закрылся". Поле `status` в каждой
    строке фронт использует только чтобы выбрать иконку (активна/пауза).
    """
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT * FROM `ai_claude_session_registry`
            WHERE last_seen_at >= (NOW() - INTERVAL 60 SECOND)
            ORDER BY last_seen_at DESC
            """
        )
        rows = await db.fetchall()

    return {"result": rows}


@router.post("/telegram-app/claude/session/wake-request")
async def telegram_app_claude_session_wake_request(request: Request, data: dict):
    """
    Кнопка "Возобновить" в Mini App для сессии на паузе - не может напрямую
    разбудить процесс терминала, поэтому кладёт спец-сообщение в ту же
    очередь ai_claude_session, которую слушает фоновый поллер/Monitor
    терминала (см. .claude/docs/claude_session_registry.md §5). Терминал,
    увидев маркер SESSION_WAKE_MARKER, сам вызывает session/resume и
    продолжает обычный цикл - здесь статус не трогаем.
    """
    _require_telegram_owner(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    await claude_message_user(SESSION_WAKE_MARKER, session_uuid)

    return {"result": {"ok": True}}


@router.post("/telegram-app/claude/session/close-request")
async def telegram_app_claude_session_close_request(request: Request, data: dict):
    """
    Кнопка "Отключить" в Mini App - мягкий стоп, не убивает терминал (см.
    .claude/docs/claude_session_registry.md §5).
    """
    _require_telegram_owner(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update(row["id"], {"status": "closing"})

    return {"result": {"ok": True}}


def _require_claude_secret(request: Request):
    expected = config_get("TELEGRAM_TOKEN_RHAPSODY")
    provided = request.headers.get("X-Claude-Secret")
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Not authorized")


async def _telegram_agent_chat_ask(data: dict, agent_name: str) -> dict:
    message = str(data.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    session_uuid = data.get("session_uuid") or str(uuid.uuid4())

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({"name": agent_name})
    if not entity_agent:
        raise HTTPException(status_code=500, detail=f"Agent '{agent_name}' not found")

    workflow_id = entity_agent["workflow_id"]
    workflow_data = await ai_workflow_load(workflow_id)

    workflow_variables_all = {
        **ai_workflow_variables_base(
            prompt_user=message,
            user_id=TELEGRAM_CHAT_USER_ID,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
            companion_id=TELEGRAM_CHAT_COMPANION_ID,
            companion_name=TELEGRAM_CHAT_COMPANION_NAME,
            companion_title=TELEGRAM_CHAT_COMPANION_TITLE,
        ),
        **json_from_string(entity_agent.get("workflow_variable") or "{}"),
    }
    ai_workflow_variables_defaults_apply(workflow_variables_all, workflow_data["variables"])

    entities_llm = await ai_llm_node_get(entity_agent.get("node_id"))

    async with mysql_get_db_async() as db:
        await db.execute("SELECT name, path FROM tool WHERE id > 0")
        raw_tools = await db.fetchall()
    tools = {t['name'].strip(): t['path'].strip() for t in raw_tools if t.get('name') and t.get('path')}

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": entities_llm,
        "workflow_steps": workflow_data["steps"],
        "workflow_variables": workflow_variables_all,
        "prompt_user": message,
        "user_id": TELEGRAM_CHAT_USER_ID,
        "companion_id": TELEGRAM_CHAT_COMPANION_ID,
        "session_uuid": session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=60.0)
        return {"result": result_text, "session_uuid": framework_model.session_uuid}
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail="Превышено время ожидания ответа от ИИ")


@router.post("/telegram-app/chat/voice")
async def telegram_app_chat_voice(request: Request, file: UploadFile = File(...)):
    _require_telegram_owner(request)

    temp_file = f"temp_{file.filename}.wav"
    content = await file.read()
    with open(temp_file, "wb") as buffer:
        buffer.write(content)

    try:
        text = await faster_whisper_transcribe(temp_file)
    finally:
        os.remove(temp_file)

    return {"result": text}


def _require_telegram_owner(request: Request):
    if not request.session.get("telegram_owner_id"):
        raise HTTPException(status_code=403, detail="Not authorized")


def _telegram_init_data_verify(init_data: str) -> int:
    """
    Проверяет подпись Telegram WebApp initData (см. https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
    и сверяет user.id с TELEGRAM_OWNER_CHAT_ID. Без этого любой, кто откроет
    ссылку на Mini App, получил бы доступ к данным - initData подписан
    Telegram по bot token и подделать его без токена нельзя.
    """
    if not init_data:
        raise HTTPException(status_code=403, detail="Missing initData")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=403, detail="Missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    bot_token = config_get("TELEGRAM_TOKEN_RHAPSODY")
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(status_code=403, detail="Invalid initData signature")

    auth_date = int(parsed.get("auth_date", 0))
    if time.time() - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        raise HTTPException(status_code=403, detail="initData expired")

    telegram_user = json.loads(parsed.get("user", "{}"))
    telegram_user_id = telegram_user.get("id")

    owner_chat_id = config_get("TELEGRAM_OWNER_CHAT_ID")
    if not owner_chat_id or telegram_user_id != int(owner_chat_id):
        raise HTTPException(status_code=403, detail="Not the bot owner")

    return telegram_user_id
