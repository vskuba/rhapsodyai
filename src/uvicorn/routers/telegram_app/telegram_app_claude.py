from fastapi import APIRouter, Request, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.telegram_.telegram_notify import telegram_send_owner
from src.tool.claude_.claude_ import claude_message_cloud
from src.uvicorn.routers.telegram_app.telegram_app_common import (
    _require_telegram_owner,
    _require_claude_secret,
    _telegram_agent_chat_ask,
    TELEGRAM_CLAUDE_AGENT_NAME,
)

router = APIRouter()


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
            SELECT id, role, kind_type, content, created_at
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
    Вызывается извне (процесс Claude Code) - авторизация через секрет,
    не сессию владельца.
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


@router.post("/telegram-app/claude/session/delete-message")
async def telegram_app_claude_session_delete_message(request: Request, data: dict):
    _require_telegram_owner(request)

    message_id = data.get("message_id")
    session_uuid = str(data.get("session_uuid") or "").strip()
    if not message_id or not session_uuid:
        raise HTTPException(status_code=400, detail="message_id and session_uuid required")

    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM agent_session WHERE id = %s AND session_uuid = %s",
            (int(message_id), session_uuid)
        )

    return {"result": {"ok": True}}


@router.get("/telegram-app/claude/sessions/active")
async def telegram_app_claude_sessions_active(request: Request):
    """
    Сессии для иконок во вкладке Cloud Mini App - видимость решает только
    staleness heartbeat: 60с без пинга = терминал закрылся.
    """
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT r.*,
                   (SELECT content FROM agent_session a
                    WHERE a.session_uuid = r.session_uuid
                      AND a.kind_type IN ('user-prompt', 'response-final')
                    ORDER BY a.id DESC LIMIT 1) AS last_message
            FROM `ai_claude_session_registry` r
            WHERE r.last_seen_at >= (NOW() - INTERVAL 60 SECOND)
            ORDER BY r.last_seen_at DESC
            """
        )
        rows = await db.fetchall()

    return {"result": rows}
