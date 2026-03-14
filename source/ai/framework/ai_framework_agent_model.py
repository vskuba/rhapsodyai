import uuid

from source.ai.framework.ai_framework import AiFrameworkModel


class AbstractAiFrameworkAgentModel(AiFrameworkModel):
    def __init__(
            self,
            name: str,
            title: str,
            prompt: str,
            system_prompt: str,
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.title = title
        self.prompt: str = prompt
        self.system_prompt = system_prompt
