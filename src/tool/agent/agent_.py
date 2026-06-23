from src.mysql_.repository.agent_repository import AgentRepository


async def agent_create_or_update(name: str, title: str, node_id: int, workflow_id: int, prompt_system:str, description: str, greeting: str) -> int:
    repo = AgentRepository()
    entity_agent = await repo.find_one_by({"name": name})
    if entity_agent:
        await repo.update(entity_agent.get("id"), {
            "title": title,
            "node_id": node_id,
            "workflow_id": workflow_id,
            "prompt_system": prompt_system,
            "description": description,
            "greeting": greeting
        })
    else:
        return await repo.add({
            "name": name,
            "title": title,
            "node_id": node_id,
            "workflow_id": workflow_id,
            "prompt_system": prompt_system,
            "description": description,
            "greeting": greeting
        })
        
    return entity_agent.get("id")
