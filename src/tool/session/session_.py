import uuid

from ai.ai_session import ai_session_message_add
from mysql_.mysql_ import mysql_get_db_async


async def session_messages(session_uuid: str, limit: int = 10) -> str:
    """
    Возвращает список сообщений в ввиде текстовой строки.
    Сообщения фильтруются по типу ('user-prompt', 'response-final') и сортируются по дате создания в порядке убывания.
    Если количество сообщений нечетное, последнее сообщение будет удалено из списка.
    """
    async with mysql_get_db_async() as db:
        sql = '''
            SELECT s.role, s.content, s.kind_type, s.created_at, s.id, a.title as agent_title
            FROM agent_session s
            LEFT JOIN agent a ON a.id = s.agent_id
            JOIN (
                -- Находим максимальный ID для каждой комбинации request_uuid и kind_type.
                -- Для user-prompt это будет его единственный ID, 
                -- а для response-final — ID самого последнего ответа.
                SELECT MAX(id) as max_id
                FROM agent_session
                WHERE session_uuid = %s 
                  AND kind_type IN ('user-prompt', 'response-final')
                GROUP BY request_uuid, kind_type
            ) t ON s.id = t.max_id
            -- Сортируем полученные уникальные сообщения по убыванию времени и ID
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT %s
        '''
        await db.execute(sql, (session_uuid, limit))
        rows = await db.fetchall()

        if len(rows) % 2 != 0:
            rows = rows[:-1]

        if not rows:
            return ''

        rows = reversed(rows)

        rendered_messages = []
        for message in rows:
            role = message.get('role', '')

            if 'response-final' == message.get('kind_type', ''):
                role = message.get('agent_title', '')

            content = message.get('content', '')
            rendered_messages.append(f"[{role}]: {content}")

        return "\n".join(rendered_messages)


async def session_uuid_create() -> str:
    return str(uuid.uuid4())


async def session_message_add(session_uuid: str, user_message: str, agent_response: str,
                             agent_id: int = 0, user_id: int = 0) -> str:
    """
    Записывает в сессию пару сообщений диалога: user-prompt (сообщение собеседника)
    и response-final (ответ агента) под одним request_uuid. Нужен workflow-оберткам,
    которые ведут диалог с целевым workflow: его session_messages видит эту переписку
    как обычную историю. agent_id задает, чьим именем подписывается ответ.
    """
    request_uuid = str(uuid.uuid4())
    agent_id = int(agent_id) or None
    user_id = int(user_id) or None

    for role, kind_type, content in (
            ('user', 'user-prompt', user_message),
            ('llm', 'response-final', agent_response),
    ):
        await ai_session_message_add(
            session_uuid=session_uuid,
            request_uuid=request_uuid,
            llm_id=None,
            user_id=user_id,
            companion_id=None,
            role=role,
            agent_id=agent_id,
            kind_type=kind_type,
            content=content,
            token=0,
        )

    return request_uuid
