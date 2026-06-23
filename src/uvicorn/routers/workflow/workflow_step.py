from fastapi import APIRouter, Request

from src.mysql_.repository.agent_workflow_step_type_repository import AgentWorkflowStepTypeRepository

router = APIRouter()


@router.get("/workflow_step/list")
async def workflow_step_type_list(request: Request):
    repo = AgentWorkflowStepTypeRepository()
    return {"result": await repo.find_by({}, 'id ASC')}
