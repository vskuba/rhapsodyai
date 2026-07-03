from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


class SessionJsonRequest(BaseModel):
    agent_id: int | None = None
    user_id: int | None = None


class SessionMessagesJsonRequest(BaseModel):
    session_uuid: str


@router.post("/session/list")
async def session_list(request: Request, json_request: SessionJsonRequest, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))):
    async with db:
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

        await db.execute(sql, tuple(params))
        return {"result": await db.fetchall()}


@router.post("/session/last")
async def session_last(request: Request, json_request: SessionJsonRequest, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))):
    async with db:
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

        sql += " GROUP BY session_uuid ORDER BY last_message_at DESC LIMIT 1"

        await db.execute(sql, tuple(params))
        return {"result": await db.fetchone()}


@router.post("/session/last/uuid")
async def session_last_uuid(request: Request, json_request: SessionJsonRequest, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))):
    async with db:
        sql = """
            SELECT session_uuid
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

        sql += " ORDER BY created_at DESC LIMIT 1"

        await db.execute(sql, tuple(params))
        row = await db.fetchone()
        
        session_uuid = row["session_uuid"] if row else None
        return {"result": session_uuid}


@router.post("/session/messages")
async def session_messages(request: Request, json_request: SessionMessagesJsonRequest, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))):
    async with db:
        # Выбираем ВСЕ поля и ВСЕ типы сообщений для инспекции
        sql = """
            SELECT s.*, l.name as llm_name
            FROM agent_session s
            LEFT JOIN llm l ON s.llm_id = l.id
            WHERE s.session_uuid = %s
            ORDER BY s.id ASC
            LIMIT %s
        """
        await db.execute(sql, (json_request.session_uuid, 500))
        rows = await db.fetchall()

        return {"result": rows}