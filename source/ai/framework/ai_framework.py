import os
import re
import httpx
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.openai import OpenAIProvider

from source.ai.tool.ai_tool import ai_tools_get, ai_tools_permanent_get
from source.config import config_get
from source.logging_ import log_request_body, log_response_body, logger_info


@dataclass
class AiFrameworkResult:
    text: str


@dataclass
class AiFrameworkModel:
    name: str
    tools: list[Callable] = field(default_factory=list)


@dataclass
class AbstractAiFrameworkManager(ABC):
    @abstractmethod
    def load(self, name: str) -> AiFrameworkModel:
        pass


class AbstractAiFramework(ABC):
    def __init__(self, framework_manager):
        self.framework_manager: AbstractAiFrameworkManager = framework_manager
        self.engine_storage: dict[str, Any] = {}
        self.message_history: list = []

    @abstractmethod
    def engine_prepare(self, framework_model: AiFrameworkModel):
        pass

    @abstractmethod
    async def engine_run(self, framework_model: AiFrameworkModel):
        pass

    @abstractmethod
    def engine_result_handle(self, result, framework_model: AiFrameworkModel) -> AiFrameworkResult | None:
        pass

    @abstractmethod
    async def framework_run(self, framework_model: AiFrameworkModel):
        pass

    def llm_model_get(self, framework_model: AiFrameworkModel) -> Model:
        model_name = config_get('llm')
        model = None

        http_client = httpx.AsyncClient(
            event_hooks={
                'request': [log_request_body],
                'response': [log_response_body]
            }
        )

        if 'claude' in model_name.lower():
            provider = AnthropicProvider(
                api_key=config_get('ANTHROPIC_API_KEY'),
                http_client=http_client
            )
            model = AnthropicModel(model_name, provider=provider)

        if 'llama' in model_name.lower() or 'qwen' in model_name.lower():
            provider = OpenAIProvider(
                base_url='http://localhost:11434/v1',
                api_key='ollama',
                http_client=http_client
            )
            model_name = re.sub(r'^[^/]*/', '', model_name)
            model = OpenAIChatModel(
                model_name=model_name,
                provider=provider
            )

        if 'gemini' in model_name.lower():
            model = GoogleModel(
                model_name=model_name.lower()
            )

        if 'groq' in model_name.lower():
            if 'groq:' in model_name.lower():
                model_name = re.sub(r'^groq:', '', model_name, flags=re.IGNORECASE)

            provider = GroqProvider(
                api_key=os.getenv('GROQ_API_KEY'),
                base_url='https://api.groq.com',
                http_client=http_client
            )
            model = GroqModel(
                model_name=model_name,
                provider=provider,
            )

        if 'grok' in model_name.lower():
            provider = OpenAIProvider(
                base_url='https://api.x.ai/v1',
                api_key=os.getenv('XAI_API_KEY'),
                http_client=http_client  # Твой клиент с хуками теперь БУДЕТ работать
            )
            model = OpenAIChatModel(model_name=model_name, provider=provider)

        if not model:
            model = OpenAIChatModel(model_name)

        return model

    def engine_tools_local_add(self, engine, framework_model: AiFrameworkModel):
        tools_local = ai_tools_get()
        tools_mapping = {func.__name__: func for func in tools_local}
        tools_local_added = []
        for t_name in framework_model.tools:
            if t_name in tools_mapping:
                engine.tool_plain(tools_mapping[t_name])
                tools_local_added.append(t_name)

        for t in ai_tools_permanent_get():
            if t.__name__ not in tools_mapping:
                engine.tool_plain(t)
                tools_local_added.append(t.__name__)

        logger_info('🛠 Local инструменты добавлены: ' + ', '.join(tools_local_added))
