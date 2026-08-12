from mysql_.mysql_ import mysql_get_db_async

# Фазы строки очереди ai_claude_session. Нужны потому, что по handled/responded_at
# фазу не отличить: оболочка ставит их уже на подтверждении приёма, задолго до
# настоящего ответа. Инструмент claude_shell ждёт сначала 'delivered' (текст ушёл
# в дочерний процесс Claude Code), потом 'answered'.
CLAUDE_MESSAGE_STATUS_QUEUED = 'queued'
CLAUDE_MESSAGE_STATUS_DELIVERED = 'delivered'
CLAUDE_MESSAGE_STATUS_ANSWERED = 'answered'
CLAUDE_MESSAGE_STATUS_FAILED = 'failed'
CLAUDE_MESSAGE_STATUS_ALLOWED = (
    CLAUDE_MESSAGE_STATUS_QUEUED,
    CLAUDE_MESSAGE_STATUS_DELIVERED,
    CLAUDE_MESSAGE_STATUS_ANSWERED,
    CLAUDE_MESSAGE_STATUS_FAILED,
)


async def claude_message_user(prompt_user: str, session_uuid: str, dynamic: int = 0) -> dict:
    """
    Кладет сообщение пользователя в очередь ai_claude_session для внешней
    обработки Claude Code - отдельный процесс опрашивает эту таблицу и
    отвечает асинхронно (ответ приходит позже отдельным сообщением, не в
    рамках этого запроса).
    dynamic=1 — внутренняя системная запись (не показывается в истории чата).
    Returns:
        dict:
            id (int): идентификатор созданной записи очереди.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO ai_claude_session (session_uuid, content, dynamic) VALUES (%s, %s, %s)",
            (session_uuid, prompt_user, dynamic)
        )
        inbox_id = db.lastrowid

    return {"id": inbox_id}


async def claude_message_cloud(session_uuid: str, response: str, inbox_id: int | None = None,
                               status: str | None = None) -> dict:
    """
    Записывает ответ Claude Code в ai_claude_session.
    Если inbox_id задан - обновляет существующую запись (ответ на запрос пользователя).
    Если inbox_id не задан - вставляет новую запись (спонтанное сообщение от Claude Code,
    например промежуточный статус; content='', handled=1).
    status - фаза строки очереди: 'delivered' (оболочка передала текст агенту),
    'answered' (пришёл ответ, значение по умолчанию), 'failed' (оболочка сдалась).
    Отметка 'delivered' только проставляет фазу и не трогает ответ и handled.
    Returns:
        dict: {"ok": True}
    """
    status = _status_normalize(status)

    async with mysql_get_db_async() as db:
        if inbox_id is not None and status == CLAUDE_MESSAGE_STATUS_DELIVERED:
            await db.execute(
                "UPDATE ai_claude_session SET status = %s WHERE id = %s AND status = %s",
                (CLAUDE_MESSAGE_STATUS_DELIVERED, inbox_id, CLAUDE_MESSAGE_STATUS_QUEUED)
            )
        elif inbox_id is not None:
            await db.execute(
                "UPDATE ai_claude_session SET handled = 1, response = %s, responded_at = NOW(), status = %s "
                "WHERE id = %s",
                (response, status, inbox_id)
            )
        else:
            await db.execute(
                "DELETE FROM ai_claude_session WHERE session_uuid = %s AND content = '' AND handled = 1",
                (session_uuid,)
            )
            await db.execute(
                "INSERT INTO ai_claude_session (session_uuid, content, handled, response, responded_at, status) "
                "VALUES (%s, '', 1, %s, NOW(), %s)",
                (session_uuid, response, status)
            )

    return {"ok": True}


def _status_normalize(status) -> str:
    """Фаза строки очереди; неизвестное значение считаем ответом.

    Оболочки старых версий про колонку не знают и статус не шлют — для них
    вызов claude_message_cloud всегда означает готовый ответ.
    """
    status = str(status or '').strip().lower()

    return status if status in CLAUDE_MESSAGE_STATUS_ALLOWED else CLAUDE_MESSAGE_STATUS_ANSWERED
