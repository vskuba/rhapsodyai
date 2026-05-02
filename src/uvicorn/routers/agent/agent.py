from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel

from ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter()


class AgentJsonRequest(BaseModel):
    find_by: dict


@router.get("/agent/list")
async def agent_list(request: Request):
    repo = AgentRepository()
    return {"result": await repo.find_by({}, order_by='position ASC')}


@router.post("/agent/list")
async def agent_list_with_criteria(request: Request, data: AgentJsonRequest):
    repo = AgentRepository()
    return {"result": await repo.find_by(data.find_by, order_by='position ASC')}


@router.get("/agent/{agent_id}")
async def agent_get(request: Request, agent_id: int):
    repo = AgentRepository()
    return {"result": await repo.find(agent_id)}


@router.get("/agent/{agent_id}/system_prompt/{collection_name}")
async def agent_get_system_prompt(request: Request, agent_id: int, collection_name: str):
    repo = AgentRepository()
    entity = await repo.find(agent_id)

    manager = AiFrameworkAgentManager()
    system_prompt = await manager.create_system_prompt(entity, {'collection_name': collection_name})

    return {"result": system_prompt}


@router.get("/agent/specialization/list")
async def agent_specialization_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        sql = """
            SELECT * FROM agent_specialization ORDER BY name ASC
        """
        await cursor.execute(sql)
        return {"result": await cursor.fetchall()}


@router.put("/agent/{agent_id}")
async def agent_update(request: Request, agent_id: int, data: dict, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        sql = """
            UPDATE agent 
            SET 
                name = %s,
                node_id = %s,
                title = %s,
                llm_id = %s,
                specialization_id = %s,
                system_prompt = %s,
                memory_short_disabled = %s
            WHERE id = %s
        """

        values = (
            data.get('name'),
            data.get('node_id'),
            data.get('title'),
            data.get('llm_id'),
            data.get('specialization_id'),
            data.get('system_prompt'),
            data.get('memory_short_disabled', 0),
            agent_id
        )

        await cursor.execute(sql, values)
        await db.commit()

        if cursor.rowcount == 0:
            return {"status": "error", "message": "Агент не найден"}

        return {"status": "success", "result": "Данные обновлены"}


@router.get("/agent/{agent_id}/user/{user_id}/session_last_entry")
async def agent_session_active_get(request: Request, agent_id: int, user_id: int, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        await cursor.execute(
            "SELECT session_uuid "
            "FROM agent_session "
            "WHERE agent_id = %s AND user_id = %s "
            "ORDER BY created_at DESC LIMIT 1", (agent_id, user_id)
        )
        return {"result": await cursor.fetchone()}
