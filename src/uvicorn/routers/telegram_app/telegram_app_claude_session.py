import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.ai_claude_session_registry_repository import AiClaudeSessionRegistryRepository
from src.telegram_.telegram_notify import telegram_send_owner
from src.tool.claude_.claude_ import claude_message_user
from src.uvicorn.routers.telegram_app.telegram_app_common import (
    _require_telegram_owner,
    _require_claude_secret,
    SESSION_CLEANUP_MARKER,
    RESTART_WATCH_MARKER,
    QUOTA_CHECK_MARKER,
)

router = APIRouter()


@router.get("/telegram-app/claude/session/inbox")
async def telegram_app_claude_session_inbox(request: Request, session_uuid: str):
    """
    Непрочитанные сообщения из ai_claude_session для данного session_uuid -
    опрашивается /loop на каждой итерации вместе с heartbeat.
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
    хуком SessionStart при старте терминала.
    """
    _require_claude_secret(request)

    repo = AiClaudeSessionRegistryRepository()
    rows = await repo.find_by({"project_label": project_label}, order_by="last_seen_at DESC, created_at DESC")

    return {"result": rows}


@router.post("/telegram-app/claude/session/register")
async def telegram_app_claude_session_register(request: Request, data: dict):
    """
    Регистрирует новую терминальную сессию - вызывается хуком SessionStart.
    """
    _require_claude_secret(request)

    # Колонки role в ai_claude_session_registry и project_team — NOT NULL
    # DEFAULT 'developer' (migrations/0001.sql), поэтому None вставлять нельзя.
    role_given = str(data.get("role") or "").strip()
    role = role_given or "developer"
    project_label = str(data.get("project_label") or "").strip()
    server_llm = str(data.get("server_llm") or "anthropic").strip()
    if server_llm not in ("anthropic", "gx10"):
        server_llm = "anthropic"
    work_dir = str(data.get("work_dir") or "").strip()
    if not project_label:
        raise HTTPException(status_code=400, detail="project_label required")

    session_uuid = str(uuid.uuid4())
    repo = AiClaudeSessionRegistryRepository()
    await repo.add({
        "session_uuid": session_uuid,
        "role": role,
        "project_label": project_label,
        "status": "active",
        "server_llm": server_llm,
        "last_seen_at": datetime.now(),
    })

    # work_dir пишем в project_team только когда роль и путь пришли непустыми:
    # пустая строка затирала бы уже сохранённый путь на карточке /admin/team.
    if role_given and work_dir:
        try:
            async with mysql_get_db_async() as db:
                await db.execute(
                    "UPDATE project_team SET work_dir = %s WHERE role = %s",
                    (work_dir, role_given)
                )
        except Exception as error:
            logger_info(f"claude_session_register: work_dir update failed: {error}")

    return {"result": {"session_uuid": session_uuid}}


@router.post("/telegram-app/claude/session/resume")
async def telegram_app_claude_session_resume(request: Request, data: dict):
    """
    Резюмирует существующую сессию - помечает active, обновляет heartbeat,
    возвращает историю переписки. Обновляет server_llm если передан.
    """
    _require_claude_secret(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    server_llm = str(data.get("server_llm") or "").strip()
    if server_llm not in ("anthropic", "gx10"):
        server_llm = None

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    now = datetime.now()
    update_data = {"status": "active", "last_seen_at": now}
    if server_llm:
        update_data["server_llm"] = server_llm
    await repo.update(row["id"], update_data)

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
    Вызывается /loop на каждой итерации - обновляет last_seen_at.
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
    Финальная уборка сессии - вызывается /loop после генерации summary.
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


@router.post("/telegram-app/claude/session/clear-messages")
async def telegram_app_claude_session_clear_messages(request: Request, data: dict):
    _require_telegram_owner(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM ai_claude_session WHERE session_uuid = %s", (session_uuid,))

    return {"result": {"ok": True}}


@router.post("/telegram-app/claude/session/delete-request")
async def telegram_app_claude_session_delete_request(request: Request, data: dict):
    """
    Кнопка "Удалить" в чате Mini App - удаляет сессию из реестра насовсем.
    Порядок: маркер очистки в очередь → удаление registry-строки.
    """
    _require_telegram_owner(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    await claude_message_user(SESSION_CLEANUP_MARKER, session_uuid, dynamic=1)
    await repo.delete(row["id"])

    return {"result": {"ok": True}}


@router.post("/telegram-app/claude/session/cleanup-confirm")
async def telegram_app_claude_session_cleanup_confirm(request: Request, data: dict):
    """
    Вызывается терминалом после того, как watch увидел SESSION_CLEANUP_MARKER -
    чистит очередь ai_claude_session.
    """
    _require_claude_secret(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM ai_claude_session WHERE session_uuid = %s", (session_uuid,))

    return {"result": {"ok": True}}


@router.post("/telegram-app/claude/session/inbox-ack")
async def telegram_app_claude_session_inbox_ack(request: Request, data: dict):
    """
    Помечает конкретные inbox-сообщения как обработанные (handled=1).
    Вызывается терминалом после обработки внутренних маркеров (RESTART_WATCH и т.п.),
    которые не нужно показывать агенту.
    """
    _require_claude_secret(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    ids = [int(i) for i in (data.get("ids") or []) if str(i).isdigit()]
    if not session_uuid or not ids:
        raise HTTPException(status_code=400, detail="session_uuid and ids required")

    placeholders = ",".join(["%s"] * len(ids))
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE ai_claude_session SET handled = 1 WHERE session_uuid = %s AND id IN ({placeholders})",
            (session_uuid, *ids),
        )

    return {"result": {"ok": True}}


@router.post("/telegram-app/claude/quota-check")
async def telegram_app_claude_quota_check(request: Request, data: dict):
    """
    Кладёт маркер __QUOTA_CHECK__ (dynamic=1) в очередь ai_claude_session.
    Терминал подхватывает маркер через inbox-поллинг, запрашивает квоту у Anthropic
    и отвечает через /telegram-app/claude/respond. Ответ появляется как сообщение
    в чате (показывается как assistant-bubble, user-content не отображается).
    """
    _require_telegram_owner(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    result = await claude_message_user(QUOTA_CHECK_MARKER, session_uuid, dynamic=1)
    return {"result": {"ok": True, "message_id": result["id"]}}


def _compute_process_status(row: dict) -> dict:
    last_seen_at = row.get("last_seen_at")
    seconds_ago = None
    watch_alive = False
    if last_seen_at:
        delta = (datetime.now() - last_seen_at).total_seconds()
        seconds_ago = int(delta)
        watch_alive = delta <= 15
    return {
        "watch_alive": watch_alive,
        "server_ok": True,
        "seconds_ago": seconds_ago,
        "last_seen_at": str(last_seen_at) if last_seen_at else None,
        "role": row.get("role"),
        "project_label": row.get("project_label"),
        "status": row.get("status"),
    }


@router.get("/telegram-app/claude/session/process-status")
async def telegram_app_claude_session_process_status(request: Request, session_uuid: str):
    """
    Статус процессов сессии - вызывается из Mini App по кнопке «Статус».
    watch_alive = last_seen_at не старше 15с (3× интервал heartbeat).
    """
    _require_telegram_owner(request)

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"result": _compute_process_status(row)}


@router.post("/telegram-app/claude/session/restart-processes")
async def telegram_app_claude_session_restart_processes(request: Request, data: dict):
    """
    Кнопка «Статус» в Mini App - отправляет терминалу сигнал перезапустить watch-процесс
    и возвращает текущий статус (до перезапуска, т.к. новый heartbeat придёт позже).
    """
    _require_telegram_owner(request)

    session_uuid = str(data.get("session_uuid") or "").strip()
    if not session_uuid:
        raise HTTPException(status_code=400, detail="session_uuid required")

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({"session_uuid": session_uuid})
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    await claude_message_user(RESTART_WATCH_MARKER, session_uuid, dynamic=1)

    status = _compute_process_status(row)
    status["restart_sent"] = True

    # Telegram-уведомление как fallback-канал на случай если watch мёртв
    # (inbox не читается) — Telegram MCP в терминале получит это сообщение
    # и разбудит агента, который перезапустит watch/Monitor вручную.
    try:
        await telegram_send_owner(
            f"🔄 Запрос перезапуска процессов сессии из Mini App\n"
            f"Сессия: {row.get('project_label')} / {row.get('role')}\n"
            f"watch alive: {'да' if status['watch_alive'] else 'нет'}"
        )
    except Exception as error:
        logger_info(f"claude_session_restart: telegram notify failed: {error}")

    return {"result": status}
