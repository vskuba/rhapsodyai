from pydantic import BaseModel

from source.ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel

class AiFrameworkAgentModelPydantic(AbstractAiFrameworkAgentModel):
    def __init__(
            self,
            name: str,
            title: str,
            prompt: str,
            system_prompt: str,
            tools: list[str],
            response_model: BaseModel | str,

    ):
        super().__init__(name, title, prompt, system_prompt)
        self.name = name
        self.tools = tools if tools is not None else []
        self.response_model = response_model
