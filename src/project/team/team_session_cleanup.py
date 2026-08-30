"""
Очистка orphaned сессий команды: удаляет inactive сессии старше 5 минут
и связанные записи в agent_session, ai_claude_session, project_team.

Вызывается автоматически при регистрации новой сессии и по ручному запросу.
"""
from datetime import datetime, timedelta

from datetime_.datetime_ import datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async


TEAM_SESSION_CLEANUP_INACTIVE_MINUTES = 5


async def cleanup_inactive_sessions() -> dict:
    """
    Удалить inactive сессии старше 5 минут и связанные записи.

    Returns:
        dict: {
            registry_deleted: int,  # удалено из реестра
            agent_session_deleted: int,  # удалено из agent_session
            ai_claude_session_deleted: int,  # удалено из ai_claude_session
            team_reset: int,  # сброшено project_team
        }
    """
    now = datetime_utc_now()
    cutoff = now - timedelta(minutes=TEAM_SESSION_CLEANUP_INACTIVE_MINUTES)

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
                "team_reset": 0,
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

        # Сбрасываем project_team строки с теми же session_uuid — освобождаем role_index
        await db.execute(
            """
            UPDATE project_team
            SET pid = NULL, session_uuid = NULL, status = 'inactive'
            WHERE session_uuid IN ({})
              AND session_uuid IS NOT NULL
            """.format(placeholders),
            tuple(session_uuids)
        )
        team_reset = db.rowcount

    return {
        "registry_deleted": registry_deleted,
        "agent_session_deleted": agent_session_deleted,
        "ai_claude_session_deleted": ai_claude_session_deleted,
        "team_reset": team_reset,
    }
