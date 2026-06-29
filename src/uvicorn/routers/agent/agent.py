from fastapi import APIRouter, Request, Depends, Query
from pydantic import BaseModel
import json

from mysql_.mysql_ import mysql_get_db_async
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.user_repository import UserRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# All agent routes require AGENT_VIEW permission
agent_auth = AuthChecker([AuthPermission.AGENT_VIEW])


class AgentJsonRequest(BaseModel):
    find_by: dict
    user_id: int | None = None


@router.get("/agent/list")
async def agent_list(request: Request, user_id: int = Query(None, description="ID пользователя для фильтрации агентов по роли"), user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    repo = AgentRepository()

    # Если передан user_id, фильтруем агентов по роли пользователя
    if user_id is not None:
        user_repo = UserRepository()
        target_user = await user_repo.find(user_id)

        if target_user and target_user.get('role'):
            user_role = target_user['role']  # 'admin', 'user', etc. (already lowercase in DB)

            # Получаем role_id из таблицы role по имени роли
            async with mysql_get_db_async() as db:
                await db.execute("SELECT id FROM `role` WHERE name = %s", (user_role,))
                role_result = await db.fetchone()

                if role_result:
                    role_id = role_result['id'] if isinstance(role_result, dict) else role_result[0]
                    # Фильтруем агентов по role_id
                    return {"result": await repo.find_by({"role_id": role_id}, order_by='position ASC')}

    # Если пользователь не найден или роль не определена, возвращаем всех агентов
    return {"result": await repo.find_by({}, order_by='position ASC')}


@router.post("/agent/list")
async def agent_list_with_criteria(request: Request, data: AgentJsonRequest, user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    repo = AgentRepository()

    # Если передан user_id, фильтруем агентов по роли пользователя
    if data.user_id is not None:
        user_repo = UserRepository()
        target_user = await user_repo.find(data.user_id)

        if target_user and target_user.get('role'):
            user_role = target_user['role']

            async with mysql_get_db_async() as db:
                await db.execute("SELECT id FROM `role` WHERE name = %s", (user_role,))
                role_result = await db.fetchone()

                if role_result:
                    role_id = role_result['id'] if isinstance(role_result, dict) else role_result[0]
                    criteria = {"role_id": role_id, **(data.find_by or {})}
                    return {"result": await repo.find_by(criteria, order_by='position ASC')}

    return {"result": await repo.find_by(data.find_by or {}, order_by='position ASC')}


@router.get("/agent/{agent_id}")
async def agent_get(request: Request, agent_id: int, user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    repo = AgentRepository()
    return {"result": await repo.find(agent_id)}


@router.get("/agent/{agent_id}/prompt_system/{collection_name}")
async def agent_get_prompt_system(request: Request, agent_id: int, collection_name: str, user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    repo = AgentRepository()
    entity = await repo.find(agent_id)

    manager = AiFrameworkAgentManager()
    prompt_system = await manager.prompt_system_create({
        "entity_agent": entity,
        "collection_name": collection_name
    })

    return {"result": prompt_system}


@router.post("/agent")
async def agent_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.AGENT_CREATE]))):
    repo = AgentRepository()

    # Serialize workflow_variable to JSON if it's a dict
    workflow_variable = data.get('workflow_variable', None)
    if isinstance(workflow_variable, dict):
        workflow_variable = json.dumps(workflow_variable, ensure_ascii=False)

    agent_id = await repo.add({
        "name": data.get('name'),
        "title": data.get('title'),
        "greeting": data.get('greeting', ''),
        "node_id": data.get('node_id', None),
        "prompt_system": data.get('prompt_system', ''),
        "llm_id": data.get('llm_id', None),
        "workflow_id": data.get('workflow_id', None),
        "description": data.get('description', ''),
        "role_id": data.get('role_id', None),
        "workflow_variable": workflow_variable,
    })

    # Return the full created agent object
    entity_agent = await repo.find(agent_id)
    return {"result": entity_agent}


@router.put("/agent/{agent_id}")
async def agent_update(request: Request, agent_id: int, data: dict, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.AGENT_UPDATE]))):
    # First get the current agent to preserve fields not in the request
    repo = AgentRepository()
    current_agent = await repo.find(agent_id)
    if not current_agent:
        return {"status": "error", "message": "Агент не найден"}

    # Merge current data with updates (only update provided fields)
    # For fields not in request, keep current values
    merged_data = {
        "name": data.get('name', current_agent.get('name')),
        "node_id": data.get('node_id', current_agent.get('node_id')),
        "title": data.get('title', current_agent.get('title')),
        "llm_id": data.get('llm_id', current_agent.get('llm_id')),
        "workflow_id": data.get('workflow_id', current_agent.get('workflow_id')),
        "workflow_variable": data.get('workflow_variable', current_agent.get('workflow_variable')),
        "prompt_system": data.get('prompt_system', current_agent.get('prompt_system')),
        "role_id": data.get('role_id', current_agent.get('role_id')),
        "greeting": data.get('greeting', current_agent.get('greeting')),
        "description": data.get('description', current_agent.get('description')),
    }

    # Serialize workflow_variable to JSON if it's a dict
    workflow_variable = merged_data['workflow_variable']
    if isinstance(workflow_variable, dict):
        workflow_variable = json.dumps(workflow_variable, ensure_ascii=False)

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
                prompt_system = %s,
                role_id = %s,
                greeting = %s,
                description = %s
            WHERE id = %s
        """

        values = (
            merged_data['name'],
            merged_data['node_id'],
            merged_data['title'],
            merged_data['llm_id'],
            merged_data['workflow_id'],
            workflow_variable,
            merged_data['prompt_system'],
            merged_data['role_id'],
            merged_data['greeting'],
            merged_data['description'],
            agent_id
        )

        await db.execute(sql, values)
        await db.connection.commit()

        if db.rowcount == 0:
            return {"status": "error", "message": "Агент не найден"}

        return {"status": "success", "result": "Данные обновлены"}


@router.get("/agent/{agent_id}/user/{user_id}/session_last_entry")
async def agent_session_active_get(request: Request, agent_id: int, user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.AGENT_VIEW, AuthPermission.SESSION_VIEW]))):
    async with db:
        await db.execute(
            "SELECT session_uuid "
            "FROM agent_session "
            "WHERE agent_id = %s AND user_id = %s "
            "ORDER BY created_at DESC LIMIT 1", (agent_id, user_id)
        )
        return {"result": await db.fetchone()}


@router.delete("/agent/{agent_id}")
async def agent_delete(request: Request, agent_id: int, user=Depends(AuthChecker([AuthPermission.AGENT_DELETE]))):
    repo = AgentRepository()
    deleted = await repo.delete(agent_id)
    if not deleted:
        return {"status": "error", "message": "Агент не найден"}
    return {"status": "success", "result": "Агент удален"}