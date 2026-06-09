from fastapi import APIRouter, Request

from src.mysql_.repository.workflow_step_type_repository import WorkflowStepTypeRepository

router = APIRouter()


@router.get("/workflow_step/list")
async def workflow_step_type_list(request: Request):
    repo = WorkflowStepTypeRepository()
    return {"result": await repo.find_by({}, 'id ASC')}
