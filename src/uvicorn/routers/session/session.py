from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


class SessionJsonRequest(BaseModel):
    agent_id: int | None = None
    user_id: int | None = None


class SessionMessagesJsonRequest(BaseModel):
    session_uuid: str


@router.post("/session/list")
async def session_list(request: Request, json_request: SessionJsonRequest, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        sql = """
            SELECT 
                session_uuid, 
                role,               
                kind_type,          
                MAX(created_at) as last_message_at,
                COUNT(*) as msg_count
            FROM agent_session 
            WHERE 1=1
        """
        params = []
        if json_request.agent_id:
            sql += " AND agent_id = %s"
            params.append(json_request.agent_id)
        if json_request.user_id:
            sql += " AND user_id = %s"
            params.append(json_request.user_id)

        sql += " GROUP BY session_uuid ORDER BY last_message_at DESC"

        await cursor.execute(sql, tuple(params))
        return {"result": await cursor.fetchall()}


@router.post("/session/messages")
async def session_messages(request: Request, json_request: SessionMessagesJsonRequest, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        # Выбираем ВСЕ поля и ВСЕ типы сообщений для инспекции
        sql = """
            SELECT s.role, s.kind_type, s.content, s.token, s.created_at, l.name as llm_name
            FROM agent_session s
            LEFT JOIN llm l ON s.llm_id = l.id
            WHERE s.session_uuid = %s 
            ORDER BY s.id ASC 
            LIMIT %s
        """
        await cursor.execute(sql, (json_request.session_uuid, 500))
        rows = await cursor.fetchall()

        return {"result": rows}
