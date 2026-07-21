import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
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
from src.mysql_.repository.event_log_repository import EventLogRepository
from src.telegram_.telegram_notify import telegram_send_owner
from src.tool.claude_.claude_ import claude_message_cloud

router = APIRouter()

agent_manager = AiFrameworkAgentManager()

# Владелец бота (тот же user_id, что и в telegram_bot.py) - его LLM-очередь
# используется для ответов ассистента в Mini App
TELEGRAM_CHAT_USER_ID = 1
TELEGRAM_CHAT_AGENT_NAME = 'telegram_assistant'

# Отдельный чат Mini App для общения с Claude Code (не LLM-ассистент) - свой
# агент/workflow/история, не смешивается с TELEGRAM_CHAT_AGENT_NAME
TELEGRAM_CLAUDE_AGENT_NAME = 'telegram_claude'

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
    return request.app.state.jinja2_template.TemplateResponse(request, "telegram_app.html")


@router.post("/telegram-app/auth")
async def telegram_app_auth(request: Request, data: dict):
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
    if not inbox_id or not session_uuid or not response:
        raise HTTPException(status_code=400, detail="inbox_id, session_uuid, response required")

    result = await claude_message_cloud(inbox_id=int(inbox_id), session_uuid=session_uuid, response=response)

    if data.get("notify", True):
        await telegram_send_owner(response)

    return {"result": result}


def _require_claude_secret(request: Request):
    expected = config_get("TELEGRAM_NOTIFY_TOKEN")
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

    bot_token = config_get("TELEGRAM_NOTIFY_TOKEN")
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
