from fastapi import APIRouter, Request

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.workflow_repository import WorkflowRepository
from src.mysql_.repository.workflow_step_repository import WorkflowStepRepository
from src.mysql_.repository.workflow_step_type_repository import WorkflowStepTypeRepository

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


@router.post("/workflow/{workflow_id}/step")
async def workflow_steps(request: Request, workflow_id: int, data: dict):
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
