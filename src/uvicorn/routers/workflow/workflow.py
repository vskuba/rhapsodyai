from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflowl import ai_workflow_variables_default_get
from src.mysql_.repository.agent_workflow_repository import AgentWorkflowRepository
from src.mysql_.repository.agent_workflow_step_repository import AgentWorkflowStepRepository
from src.mysql_.repository.agent_workflow_step_type_repository import AgentWorkflowStepTypeRepository
from src.mysql_.repository.agent_workflow_variable_repository import AgentWorkflowVariableRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/workflow/list")
async def workflow_list(request: Request, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find_by({}, 'title ASC')}


@router.post("/workflow")
async def workflow_create(request: Request, data: dict, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))):
    async with db:
        sql = """
            INSERT INTO agent_workflow (name, title, node_id, description, position)
            VALUES (%s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('title'),
            data.get('node_id') or None,
            data.get('description', ''),
            int(data.get('position', 0))
        )
        await db.execute(sql, values)
        await db.connection.commit()

        # Получаем ID только что созданной строки в MySQL
        new_id = db.lastrowid

        return {"status": "success", "result": {"id": new_id}}


@router.get("/workflow/{node_id}/list")
async def workflow_list(request: Request, node_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find_by({"node_id": node_id}, 'title ASC')}


@router.get("/workflow/{workflow_id}")
async def workflow(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find(workflow_id)}


@router.put("/workflow/{workflow_id}")
async def workflow(request: Request, workflow_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.update(workflow_id, data)}


@router.get("/workflow/{workflow_id}/steps")
async def workflow_steps(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    """
    Получает все шаги задачи вместе с их иконками и описаниями типов.
    """
    sql = f"""
            SELECT
                ts.*,
                tst.icon,
                tst.description as description
            FROM `agent_workflow_step` ts
            LEFT JOIN `agent_workflow_step_type` tst ON ts.type_id = tst.id
            WHERE ts.workflow_id = %s
            ORDER BY ts.position ASC
        """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return {"result": await db.fetchall()}


@router.get("/workflow/{workflow_id}/variables")
async def workflow_variables(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    sql = f"""
            SELECT *
            FROM `agent_workflow_variable`
            WHERE workflow_id = %s
            ORDER BY name ASC
        """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        db_variables = await db.fetchall()

        return {"result": [{"id": 0, "name": i} for i in await ai_workflow_variables_default_get()] + list(db_variables)}


@router.post("/workflow/{workflow_id}/step")
async def workflow_step_add(request: Request, workflow_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    repo_workflow_step = AgentWorkflowStepRepository()
    repo_workflow_step_type = AgentWorkflowStepTypeRepository()

    # 1. Получаем текущие шаги, чтобы вычислить следующую позицию
    current_steps = await repo_workflow_step.find_by({"workflow_id": workflow_id})
    next_position = len(current_steps)

    type_id = data.get("type_id", 0)
    workflow_step_type = await repo_workflow_step_type.find(type_id)

    # 2. Подготавливаем данные для вставки
    # Извлекаем title из данных или ставим дефолт, если в схеме NOT NULL
    new_step_data = {
        "workflow_id": workflow_id,
        "type_id": type_id,
        "title": workflow_step_type.get('description', f"Шаг {next_position}"),
        "position": next_position,
        "metadata": data.get("metadata", "{}")  # Инициализируем пустым JSON
    }

    new_id = await repo_workflow_step.add(new_step_data)

    return {"result": new_id}


@router.post("/workflow/{workflow_id}/variable")
async def workflow_variable_add(request: Request, workflow_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    repo_workflow_variable = AgentWorkflowVariableRepository()

    variable = await repo_workflow_variable.find_one_by({"workflow_id": workflow_id, "name": data.get("name")})
    if variable:
        return {"result": variable.get("id")}

    new_variable_data = {
        "workflow_id": workflow_id,
        "name": data.get("name"),
        "default": data.get("default"),
    }

    new_id = await repo_workflow_variable.add(new_variable_data)

    return {"result": new_id}


@router.put("/workflow/{workflow_id}/steps/reorder")
async def workflow_steps_reorder(request: Request, workflow_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    repo = AgentWorkflowStepRepository()
    positions = data.get("positions", [])

    for item in positions:
        step_id = item.get("id")
        new_position = item.get("position")

        if step_id is not None:
            await repo.update(int(step_id), {"position": int(new_position)})

    return {"result": "success"}


@router.put("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_update(request: Request, workflow_step_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    repo = AgentWorkflowStepRepository()
    return {"result": await repo.update(workflow_step_id, data)}


@router.delete("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_delete(request: Request, workflow_step_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))):
    repo = AgentWorkflowStepRepository()
    return {"result": await repo.delete(workflow_step_id)}


@router.delete("/workflow/{workflow_id}/variable/{workflow_variable_id}")
async def workflow_variable_delete(request: Request, workflow_variable_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))):
    repo = AgentWorkflowVariableRepository()
    return {"result": await repo.delete(workflow_variable_id)}