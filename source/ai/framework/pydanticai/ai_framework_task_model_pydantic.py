from pydantic import BaseModel
from source.ai.framework.ai_framework_task_model import AbstractAiFrameworkTaskModel


class AiFrameworkTaskModelPydantic(AbstractAiFrameworkTaskModel):
    def __init__(
            self,
            name: str,
            title: str,
            prompt: str,
            system_prompt: str,
            sub_task_current_index: int,
            input_fields: list[str],
            tools: list[str],
            mcp_servers: list[str],
            response_model: BaseModel | str,

    ):
        super().__init__(name, title, prompt, system_prompt, sub_task_current_index, input_fields, mcp_servers)
        self.name = name
        self.tools = tools
        self.response_model = response_model

    def input_values_get(self):
        return super().input_values_get()
