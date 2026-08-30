"""
Очистка orphaned сессий команды: удаляет inactive сессии старше 7 дней
и связанные записи в agent_session и ai_claude_session.

Вызывается автоматически при регистрации новой сессии и по ручному запросу.
"""
from datetime import datetime, timedelta

from datetime_.datetime_ import datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async


TEAM_SESSION_CLEANUP_INACTIVE_DAYS = 7


async def cleanup_inactive_sessions() -> dict:
    """
    Удалить inactive сессии старше 7 дней и связанные записи.

    Returns:
        dict: {
            registry_deleted: int,  # удалено из реестра
            agent_session_deleted: int,  # удалено из agent_session
            ai_claude_session_deleted: int,  # удалено из ai_claude_session
        }
    """
    now = datetime_utc_now()
    cutoff = now - timedelta(days=TEAM_SESSION_CLEANUP_INACTIVE_DAYS)

    async with mysql_get_db_async() as db:
        # Сначала находим inactive сессии старше порога
        await db.execute(
            """
            SELECT session_uuid FROM ai_claude_session_registry
            WHERE status = 'inactive' AND closed_at < %s
            """,
            (cutoff,)
        )
        orphaned = await db.fetchall()

        if not orphaned:
            return {
                "registry_deleted": 0,
                "agent_session_deleted": 0,
                "ai_claude_session_deleted": 0,
            }

        session_uuids = [row["session_uuid"] for row in orphaned]
        placeholders = ", ".join(["%s"] * len(session_uuids))

        # Удаляем из agent_session по session_uuid
        await db.execute(
            f"DELETE FROM agent_session WHERE session_uuid IN ({placeholders})",
            tuple(session_uuids)
        )
        agent_session_deleted = db.rowcount

        # Удаляем из ai_claude_session по session_uuid
        await db.execute(
            f"DELETE FROM ai_claude_session WHERE session_uuid IN ({placeholders})",
            tuple(session_uuids)
        )
        ai_claude_session_deleted = db.rowcount

        # Удаляем из реестра
        await db.execute(
            f"DELETE FROM ai_claude_session_registry WHERE session_uuid IN ({placeholders})",
            tuple(session_uuids)
        )
        registry_deleted = db.rowcount

    return {
        "registry_deleted": registry_deleted,
        "agent_session_deleted": agent_session_deleted,
        "ai_claude_session_deleted": ai_claude_session_deleted,
    }
