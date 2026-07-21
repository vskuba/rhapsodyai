import uuid

from ai.ai_session import ai_session_message_add
from mysql_.mysql_ import mysql_get_db_async


async def claude_message_user(prompt_user: str, session_uuid: str) -> dict:
    """
    Кладет сообщение пользователя в очередь ai_claude_session для внешней
    обработки Claude Code - отдельный процесс опрашивает эту таблицу и
    отвечает асинхронно (ответ приходит позже отдельным сообщением, не в
    рамках этого запроса).
    Returns:
        dict:
            id (int): идентификатор созданной записи очереди.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO ai_claude_session (session_uuid, content) VALUES (%s, %s)",
            (session_uuid, prompt_user)
        )
        inbox_id = db.lastrowid

    return {"id": inbox_id}


async def claude_message_cloud(inbox_id: int, session_uuid: str, response: str) -> dict:
    """
    Записывает ответ Claude Code на сообщение из очереди ai_claude_session:
    помечает запись обработанной и добавляет ответ в agent_session, откуда
    его подхватывает чат Mini App. Не вызывается workflow-шагом - дергается
    напрямую внешним процессом Claude Code после обработки запроса.
    Returns:
        dict:
            request_uuid (str): request_uuid созданной записи в agent_session.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE ai_claude_session SET handled = 1, response = %s, responded_at = NOW() WHERE id = %s",
            (response, inbox_id)
        )

    request_uuid = str(uuid.uuid4())
    await ai_session_message_add(
        session_uuid=session_uuid,
        request_uuid=request_uuid,
        llm_id=None,
        user_id=None,
        companion_id=None,
        role='claude_code',
        agent_id=None,
        kind_type='response-final',
        content=response,
        token=0,
    )

    return {"request_uuid": request_uuid}
