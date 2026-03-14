import traceback
from abc import abstractmethod

from source.ai.framework.ai_framework import AbstractAiFrameworkManager
from source.ai.framework.ai_framework_agent_model import AbstractAiFrameworkAgentModel
from source.logging_ import logger_info


class AbstractAiFrameworkAgentManager(AbstractAiFrameworkManager):
    @abstractmethod
    def create(self, name: str) -> AbstractAiFrameworkAgentModel:
        pass

    def load(self, name: str) -> AbstractAiFrameworkAgentModel:
        try:
            return self.create(name)

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Агент {name} ошибка: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise
