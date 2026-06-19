from mysql_.mysql_ import mysql_pool_get


async def session_messages(session_uuid: str, limit: int = 10) -> list:
    """
    Возвращает список сообщений для указанного пользователя, агента и сессии.
    Сообщения фильтруются по типу ('user-prompt', 'response-final') и сортируются по дате создания в порядке убывания.
    Если количество сообщений нечетное, последнее сообщение будет удалено из списка.
    """
    pool = await mysql_pool_get()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            sql = '''
                SELECT session_uuid, role, kind_type, content FROM agent_session 
                WHERE session_uuid = %s AND kind_type in ('user-prompt', 'response-final') 
                ORDER BY created_at DESC, id DESC
                LIMIT %s
            '''
            await cursor.execute(sql, (session_uuid, limit))
            rows = await cursor.fetchall()

            if len(rows) % 2 != 0:
                rows = rows[:-1]

            return list(reversed(rows))


async def session_messages_render(messages: list[dict]) -> str:
    """
    Форматирует список сообщений в строку для отображения.
    Каждое сообщение будет отображаться в формате: "[role]: content".
    """
    if not messages:
        return ''

    rendered_messages = []
    for message in messages:
        role = message.get('role', 'unknown')
        content = message.get('content', '')
        rendered_messages.append(f"[{role}]: {content}")
    return "=== HISTORY LAST MESSAGES ===\n" + "\n".join(rendered_messages)
