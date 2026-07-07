from fastapi import APIRouter, Request, Depends
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.agent_workflow_variable_repository import AgentWorkflowVariableRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

@router.get("/agent_workflow_variable/list")
async def variable_list(request: Request, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    # Возвращаем только переменные с заполненным node_id
    sql = """
        SELECT *
        FROM agent_workflow_variable
        WHERE node_id IS NOT NULL
        ORDER BY name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        return {"result": await db.fetchall()}


@router.post("/agent_workflow_variable")
async def variable_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))):
    repo = AgentWorkflowVariableRepository()
    new_id = await repo.add({
        "name": data.get("name"),
        "description": data.get("description"),
        "default": data.get("default"),
        "workflow_id": data.get("workflow_id"),
        "node_id": data.get("node_id"),
        "is_editable": data.get("is_editable", 0),
        "pattern": data.get("pattern")
    })
    return {"result": {"id": new_id}}


@router.put("/agent_workflow_variable/{variable_id}")
async def variable_update(request: Request, variable_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    repo = AgentWorkflowVariableRepository()
    await repo.update(variable_id, data)
    return {"result": "success"}

@router.delete("/agent_workflow_variable/{variable_id}")
async def variable_delete(request: Request, variable_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))):
    repo = AgentWorkflowVariableRepository()
    await repo.delete(variable_id)
    return {"result": "success"}
