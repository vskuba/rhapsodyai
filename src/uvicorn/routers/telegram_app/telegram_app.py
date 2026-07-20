import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.event_log_repository import EventLogRepository

router = APIRouter()

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
