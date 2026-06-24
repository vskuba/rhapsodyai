from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
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


@router.get("/agent/{agent_id}/prompt_system/{collection_name}")
async def agent_get_prompt_system(request: Request, agent_id: int, collection_name: str):
    repo = AgentRepository()
    entity = await repo.find(agent_id)

    manager = AiFrameworkAgentManager()
    prompt_system = await manager.prompt_system_create({
        "entity_agent": entity,
        "collection_name": collection_name
    })

    return {"result": prompt_system}


@router.post("/agent")
async def agent_create(request: Request, data: dict):
    repo = AgentRepository()
    entity_agent = await repo.add({
        "name": data.get('name'),
        "title": data.get('title'),
        "greeting": data.get('greeting', ''),
        "node_id": data.get('node_id', None),
        "prompt_system": data.get('prompt_system', ''),
        "llm_id": data.get('llm_id', None),
        "workflow_id": data.get('workflow_id', None),
        "description": data.get('description', ''),
    })

    return {"result": entity_agent}


@router.put("/agent/{agent_id}")
async def agent_update(request: Request, agent_id: int, data: dict, db=Depends(mysql_get_db_async)):
    async with db:
        sql = """
            UPDATE agent 
            SET 
                name = %s,
                node_id = %s,
                title = %s,
                llm_id = %s,
                workflow_id = %s,
                workflow_variable = %s,
                prompt_system = %s
            WHERE id = %s
        """

        values = (
            data.get('name'),
            data.get('node_id'),
            data.get('title'),
            data.get('llm_id'),
            data.get('workflow_id'),
            data.get('workflow_variable'),
            data.get('prompt_system'),
            agent_id
        )

        await db.execute(sql, values)
        await db.connection.commit()

        if db.rowcount == 0:
            return {"status": "error", "message": "Агент не найден"}

        return {"status": "success", "result": "Данные обновлены"}


@router.get("/agent/{agent_id}/user/{user_id}/session_last_entry")
async def agent_session_active_get(request: Request, agent_id: int, user_id: int, db=Depends(mysql_get_db_async)):
    async with db:
        await db.execute(
            "SELECT session_uuid "
            "FROM agent_session "
            "WHERE agent_id = %s AND user_id = %s "
            "ORDER BY created_at DESC LIMIT 1", (agent_id, user_id)
        )
        return {"result": await db.fetchone()}
