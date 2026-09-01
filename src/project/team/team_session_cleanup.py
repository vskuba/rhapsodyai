"""
Очистка orphaned сессий команды: удаляет inactive сессии старше 5 минут
и связанные записи в agent_session, ai_claude_session, project_team.

Вызывается автоматически при регистрации новой сессии и по ручному запросу.

**Замолчавшие гасим сами.** Оболочка, закрытая по-человечески, отмечается `inactive`
на выходе — её и убирает уборка. Но убитый терминал (закрыли окно, `kill -9`,
перезагрузили машину) выхода не проходит и остаётся `active` навсегда: heartbeat не
приходит, а строка живёт. На `/admin/team` такие копятся мёртвыми карточками, и
команда выглядит так, будто роли отваливаются пачками, — живьём их набралось
шестнадцать при семи работающих.
"""
from datetime import datetime, timedelta

from datetime_.datetime_ import datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async


TEAM_SESSION_CLEANUP_INACTIVE_MINUTES = 5

# Через сколько молчащая `active`-сессия считается мёртвой. Час — с большим запасом
# от порога свежести карточки (`timeout_ping_stale`, 45 секунд): тот решает, как
# рисовать живую строку при заминке сети, а этот — когда строку списать совсем.
# Ошибка здесь дороже: погасив живую оболочку, мы отняли бы её у конвейера, и
# вернуть её мог бы только человек перезапуском.
TEAM_SESSION_CLEANUP_SILENT_MINUTES = 60


async def cleanup_inactive_sessions() -> dict:
    """
    Удалить inactive сессии старше 5 минут и связанные записи.

    Перед этим гасим замолчавшие `active` — см. `team_session_cleanup_silent`: без
    этого шага убитый терминал остаётся живой карточкой навсегда, и до удаления
    дело не доходит вовсе.

    Returns:
        dict: {
            registry_deleted: int,  # удалено из реестра
            agent_session_deleted: int,  # удалено из agent_session
            ai_claude_session_deleted: int,  # удалено из ai_claude_session
            team_reset: int,  # сброшено project_team
            silent_closed: int,  # переведено active -> inactive по молчанию
        }
    """
    now = datetime_utc_now()
    cutoff = now - timedelta(minutes=TEAM_SESSION_CLEANUP_INACTIVE_MINUTES)
    silent_closed = await team_session_cleanup_silent()

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
                "silent_closed": silent_closed,
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
        "silent_closed": silent_closed,
    }


async def team_session_cleanup_silent() -> int:
    """
    Погасить `active`-сессии, от которых давно нет heartbeat. Returns: сколько.

    Оболочка, закрытая по-человечески, отмечается `inactive` сама. Убитая — нет:
    закрыли окно терминала, `kill -9`, перезагрузили машину — строка остаётся живой
    навсегда, и на `/admin/team` копятся мёртвые карточки. Выглядит это так, будто
    роли отваливаются пачками; на деле отвалились они однажды, а списать их некому.

    Гасим, а не удаляем: дальше строку подберёт обычная уборка через свои пять минут,
    и второго пути удаления в модуле не появится.

    `last_seen_at IS NULL` тоже гасим, но только по `created_at`: строка,
    зарегистрированная час назад и ни разу не отметившаяся, — это оболочка, умершая
    на старте. Не проверь мы дату, погасили бы и ту, что регистрируется прямо сейчас.
    """
    cutoff = datetime_utc_now() - timedelta(minutes=TEAM_SESSION_CLEANUP_SILENT_MINUTES)

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            UPDATE ai_claude_session_registry
               SET status = 'inactive', closed_at = %s
             WHERE status = 'active'
               AND COALESCE(last_seen_at, created_at) < %s
            """,
            (datetime_utc_now(), cutoff),
        )
        closed = db.rowcount
        await db.connection.commit()

    return closed
