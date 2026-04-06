from source.ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel

class AiFrameworkAgentModelPydantic(AbstractAiFrameworkAgentModel):
    def __init__(
            self,
            name: str,
            title: str,
            description: str,
            prompt: str,
            system_prompt: str,
            tools: list[str],
            mcp_servers: list[str],
            specialization: str,
            memory_short_enabled: bool
    ):
        super().__init__(name, title, description, prompt, system_prompt, specialization)
        self.tools = tools if tools is not None else []
        self.mcp_servers = mcp_servers
        self.response_model = str
        self.memory_short_enabled = memory_short_enabled