from pydantic import BaseModel

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
            response_model: BaseModel | str,
            interaction: str,
            specialization: str

    ):
        super().__init__(name, title, description, prompt, system_prompt, interaction, specialization)
        self.tools = tools if tools is not None else []
        self.mcp_servers = mcp_servers
        self.response_model = response_model