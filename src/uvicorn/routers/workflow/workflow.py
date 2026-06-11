from fastapi import APIRouter, Request

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.workflow_repository import WorkflowRepository
from src.mysql_.repository.workflow_step_repository import WorkflowStepRepository
from src.mysql_.repository.workflow_step_type_repository import WorkflowStepTypeRepository
from src.mysql_.repository.workflow_variable_repository import WorkflowVariableRepository

router = APIRouter()


@router.get("/workflow/list")
async def workflow_list(request: Request):
    repo = WorkflowRepository()
    return {"result": await repo.find_by({}, 'title ASC')}


@router.get("/workflow/{workflow_id}")
async def workflow(request: Request, workflow_id: int):
    repo = WorkflowRepository()
    return {"result": await repo.find(workflow_id)}


@router.put("/workflow/{workflow_id}")
async def workflow(request: Request, workflow_id: int, data: dict):
    repo = WorkflowRepository()
    return {"result": await repo.update(workflow_id, data)}


@router.get("/workflow/{workflow_id}/steps")
async def workflow_steps(request: Request, workflow_id: int):
    """
    Получает все шаги задачи вместе с их иконками и описаниями типов.
    """
    sql = f"""
            SELECT 
                ts.*, 
                tst.icon, 
                tst.description as description
            FROM `workflow_step` ts
            LEFT JOIN `workflow_step_type` tst ON ts.type_id = tst.id
            WHERE ts.workflow_id = %s
            ORDER BY ts.position ASC
        """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return {"result": await db.fetchall()}


@router.get("/workflow/{workflow_id}/variables")
async def workflow_variables(request: Request, workflow_id: int):
    sql = f"""
            SELECT *
            FROM `workflow_variable` 
            WHERE workflow_id = %s
        """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        db_variables = await db.fetchall()

        combined_result = [{"id": 0, "name": "user-prompt"}] + list(db_variables)

        return {"result": combined_result}


@router.post("/workflow/{workflow_id}/step")
async def workflow_step_add(request: Request, workflow_id: int, data: dict):
    repo_workflow_step = WorkflowStepRepository()
    repo_workflow_step_type = WorkflowStepTypeRepository()

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
async def workflow_variable_add(request: Request, workflow_id: int, data: dict):
    repo_workflow_variable = WorkflowVariableRepository()

    variable = await repo_workflow_variable.find_one_by({"workflow_id": workflow_id, "name": data.get("name")})
    if variable:
        return {"result": variable.get("id")}

    new_variable_data = {
        "workflow_id": workflow_id,
        "name": data.get("name"),
    }

    new_id = await repo_workflow_variable.add(new_variable_data)

    return {"result": new_id}


@router.put("/workflow/{workflow_id}/steps/reorder")
async def workflow_steps_reorder(request: Request, workflow_id: int, data: dict):
    repo = WorkflowStepRepository()
    positions = data.get("positions", [])

    for item in positions:
        step_id = item.get("id")
        new_position = item.get("position")

        if step_id is not None:
            await repo.update(int(step_id), {"position": int(new_position)})

    return {"result": "success"}


@router.put("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_update(request: Request, workflow_step_id: int, data: dict):
    repo = WorkflowStepRepository()
    return {"result": await repo.update(workflow_step_id, data)}


@router.delete("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_delete(request: Request, workflow_step_id: int):
    repo = WorkflowStepRepository()
    return {"result": await repo.delete(workflow_step_id)}


@router.delete("/workflow/{workflow_id}/variable/{workflow_variable_id}")
async def workflow_variable_delete(request: Request, workflow_variable_id: int):
    repo = WorkflowVariableRepository()
    return {"result": await repo.delete(workflow_variable_id)}
