from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AiFrameworkResult:
    text: str


@dataclass
class AiFrameworkModel:
    name: str


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
