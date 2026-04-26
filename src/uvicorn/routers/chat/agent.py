from fastapi import APIRouter, Request
from src.ai_pydantic.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic

router = APIRouter()
ai_agent_manager = AiFrameworkAgentManagerPydantic()


@router.post("/agent/list")
async def agent_list(request: Request):
    agent_names = ai_agent_manager.list()
    active_name = "my_assistant"

    sorted_agents = [active_name] + [name for name in agent_names if name != active_name]

    return {"result": sorted_agents}
