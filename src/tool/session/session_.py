import re
import uuid
from difflib import SequenceMatcher

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


async def session_response_repeat_check(session_uuid: str, response: str, prompt_user: str = '', limit: int = 5) -> dict:
    """
    Проверяет, является ли сгенерированный ответ зацикливанием (анти-луп: "сплю уже"
    на каждое "ок"). Зацикливание — это когда ОБА условия выполнены: ответ повторяет
    один из последних ответов агента И входящее сообщение повторяет одно из последних
    сообщений собеседника (не несет новизны). Легитимные повторы ("да"/"нет" на серию
    РАЗНЫХ вопросов) не гасятся: новое входящее сообщение -> repeat всегда 0.
    Сравнение по нормализованному тексту: точное совпадение или сходство выше порога 0.85.
     - session_uuid: сессия переписки
     - response: сгенерированный ответ до отправки
     - prompt_user: входящее сообщение собеседника (без него проверяется только ответ)
     - limit: сколько последних сообщений каждой стороны сравнивать
    Returns:
        A dictionary with the check result.
        repeat (int): 1 — зацикливание (и ответ, и входящее сообщение — повторы), 0 — отвечать можно.
    """
    normalized = _response_normalize(response)
    if not normalized:
        return {"repeat": 0}

    async def _history_get(db_session, kind_type: str) -> list:
        await db_session.execute(
            """
            SELECT content FROM agent_session
            WHERE session_uuid = %s AND kind_type = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (session_uuid, kind_type, int(limit))
        )
        return await db.fetchall()

    def _is_repeat(text: str, rows: list) -> bool:
        for row in rows:
            previous = _response_normalize(row.get('content', ''))
            if not previous:
                continue
            if previous == text or SequenceMatcher(None, text, previous).ratio() >= 0.85:
                return True
        return False

    async with mysql_get_db_async() as db:
        response_rows = await _history_get(db, 'response-final')

        if not _is_repeat(normalized, response_rows):
            return {"repeat": 0}

        # Ответ повторяется, но входящее сообщение новое (другой вопрос) —
        # повтор легитимен ("да"/"нет" на разные вопросы), отвечаем
        normalized_prompt = _response_normalize(prompt_user)
        if normalized_prompt:
            prompt_rows = await _history_get(db, 'user-prompt')
            # Свежее сообщение уже записано в историю первым — сравниваем с предыдущими
            previous_prompts = [
                r for r in prompt_rows
                if _response_normalize(r.get('content', '')) != ''
            ][1:] if prompt_rows else []
            if not _is_repeat(normalized_prompt, previous_prompts):
                return {"repeat": 0}

    return {"repeat": 1}


async def session_uuid_create() -> str:
    return str(uuid.uuid4())


async def session_message_add(
        session_uuid: str,
        user_message: str,
        agent_response: str,
        agent_id: int = 0,
        user_id: int = 0,
        companion_id: int = 0
) -> str:
    """
    Записывает в сессию пару сообщений диалога: user-prompt (сообщение собеседника)
    и response-final (ответ агента) под одним request_uuid. Нужен workflow-оберткам,
    которые ведут диалог с целевым workflow: его session_messages видит эту переписку
    как обычную историю. agent_id задает, чьим именем подписывается ответ.
    """
    request_uuid = str(uuid.uuid4())
    agent_id = int(agent_id) or None
    user_id = int(user_id) or None
    companion_id = int(companion_id) or None

    for role, kind_type, content in (
            ('user', 'user-prompt', user_message),
            ('llm', 'response-final', agent_response),
    ):
        await ai_session_message_add(
            session_uuid=session_uuid,
            request_uuid=request_uuid,
            llm_id=None,
            user_id=user_id,
            companion_id=companion_id,
            role=role,
            agent_id=agent_id,
            kind_type=kind_type,
            content=content,
            token=0,
        )

    return request_uuid


def _response_normalize(text: str) -> str:
    """Нормализация ответа для сравнения на повтор: нижний регистр,
    только буквы/цифры, схлопнутые пробелы (скобки, эмодзи, пунктуация не влияют)."""
    text = re.sub(r'[^\w\s]+', '', str(text or '').lower(), flags=re.UNICODE)
    return re.sub(r'\s+', ' ', text).strip()
