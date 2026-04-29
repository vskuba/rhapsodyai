from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


class SessionJsonRequest(BaseModel):
    agent_name: str | None = None
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
            FROM agent_memory_short 
            WHERE 1=1
        """
        params = []
        if json_request.agent_name:
            sql += " AND agent = %s"
            params.append(json_request.agent_name)
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
            SELECT role, kind_type, content, created_at 
            FROM agent_memory_short 
            WHERE session_uuid = %s 
            ORDER BY id ASC 
            LIMIT %s
        """
        await cursor.execute(sql, (json_request.session_uuid, 500))
        rows = await cursor.fetchall()

        return {"result": rows}
