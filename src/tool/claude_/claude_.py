from mysql_.mysql_ import mysql_get_db_async


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


async def claude_message_cloud(session_uuid: str, response: str, inbox_id: int | None = None) -> dict:
    """
    Записывает ответ Claude Code в ai_claude_session.
    Если inbox_id задан - обновляет существующую запись (ответ на запрос пользователя).
    Если inbox_id не задан - вставляет новую запись (спонтанное сообщение от Claude Code,
    например промежуточный статус; content='', handled=1).
    Returns:
        dict: {"ok": True}
    """
    async with mysql_get_db_async() as db:
        if inbox_id is not None:
            await db.execute(
                "UPDATE ai_claude_session SET handled = 1, response = %s, responded_at = NOW() WHERE id = %s",
                (response, inbox_id)
            )
        else:
            await db.execute(
                "DELETE FROM ai_claude_session WHERE session_uuid = %s AND content = '' AND handled = 1",
                (session_uuid,)
            )
            await db.execute(
                "INSERT INTO ai_claude_session (session_uuid, content, handled, response, responded_at) "
                "VALUES (%s, '', 1, %s, NOW())",
                (session_uuid, response)
            )

    return {"ok": True}
