from src.mysql_.repository.agent_workflow_repository import AgentWorkflowRepository


async def agent_workflow_id(name: str) -> int:
    repo = AgentWorkflowRepository()
    entity_agent_workflow = await repo.find_one_by({"name": name})

    return entity_agent_workflow.get("id")
