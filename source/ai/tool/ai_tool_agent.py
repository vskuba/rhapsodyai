from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic

ai_agent_manager = AiFrameworkAgentManagerPydantic()

async def agent_list() -> str:
    """
    Returns a list of all available AI agents in the system.
    Use this to discover which specialized agents can be called or assigned to tasks.
    Each agent in the list includes its name, title, and a description of its capabilities.
    """
    result = ['Available agents:']
    for agent_name in ai_agent_manager.list():
        agent_model = ai_agent_manager.load(agent_name)
        result.append(f'Agent "{agent_model.name}", title: {agent_model.title}, description: {agent_model.description}')

    return '\n'.join(result)