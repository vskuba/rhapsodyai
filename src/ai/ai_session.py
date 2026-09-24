import json

from mysql_.mysql_ import mysql_get_db_async


async def ai_session_message_add(session_uuid, request_uuid, llm_id, user_id, role, agent_id, kind_type, content, token=None):
    """Строка журнала вызова LLM: промпт, ответ, вызов инструмента.

    ⚠ Собеседника здесь нет и быть не должно. `agent_session` отвечает на вопрос
    «что мы спросили у модели и что она ответила»; кто с кем разговаривает —
    вопрос `companion_session`, и там у разговора своя строка на обмен. Пока
    столбец `companion_id` стоял здесь, он же был и единственным местом, куда
    переписка попадала, — но попадала слепком промпта, из которого разговор не
    выбрать ни по паре, ни по времени.
    """
    async with mysql_get_db_async() as db:
        # Используем %s для MySQL
        sql = '''
            INSERT INTO agent_session (session_uuid, request_uuid, llm_id, user_id, role, agent_id, kind_type, content, token)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        await db.execute(sql, (session_uuid, request_uuid, llm_id, user_id, role, agent_id, kind_type, content, token))
        # При autocommit=True в настройках пула, commit() произойдет автоматически


async def ai_session_metadata_get(session_uuid) -> dict:
    async with mysql_get_db_async() as db:
        sql = '''
            SELECT metadata FROM session WHERE uuid = %s
        '''
        await db.execute(sql, (session_uuid,))
        row = await db.fetchone()

        if not row:
            return {}

        raw_metadata = row['metadata']

        if isinstance(raw_metadata, dict):
            return raw_metadata

        if isinstance(raw_metadata, str):
            try:
                return json.loads(raw_metadata)
            except json.JSONDecodeError as e:
                print(f"Ошибка парсинга JSON для сессии {session_uuid}: {e}")
                return {}

        return {}


async def ai_session_metadata_set(session_uuid, metadata: dict):
    async with mysql_get_db_async() as db:
        sql = '''
            SELECT id FROM session WHERE uuid = %s
        '''
        await db.execute(sql, session_uuid)
        entity_session = await db.fetchone()

        metadata_json = json.dumps(metadata, ensure_ascii=False)
        if not entity_session:
            sql = '''
                INSERT INTO session (metadata, uuid) VALUES (%s, %s)
            '''
        else:
            sql = '''
                UPDATE session SET metadata = %s WHERE uuid = %s
            '''
        await db.execute(sql, (metadata_json, session_uuid))
