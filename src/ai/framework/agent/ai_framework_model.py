import uuid

from ai.framework.ai_framework import AiFrameworkModel


class AiFrameworkAgentModel(AiFrameworkModel):
    def __init__(
            self,
            framework_class: str,
            title: str,
            description: str,
            specialization: str
    ):
        self.id = str(uuid.uuid4())
        self.framework_class = framework_class

        self.title = title
        self.description = description
        self.specialization = specialization

        self.workflow_steps: list = []
        self.workflow_step_current_index: int = 0
        self.workflow_variables: dict = {}

        # Переменные, восстановленные из сессии при continue_workflow-resume:
        # переносятся в следующий снапшот, чтобы пережить несколько границ запросов
        self.workflow_variables_restored: dict = {}

        self.companion_session_message_id: int = 0

        # Намерения, накопленные за прогон инструментом `chat_intention_add`:
        # их забирает ручка `/chat/ask` ключом `intentions`.
        #
        # ⚠ Список, а не строка: за один прогон законны несколько намерений, и
        # побеждать последнему тут нельзя — в отличие от номера обмена выше.
        #
        # ⚠ Заводится пустым списком, а не `None`: поле уезжает наружу как
        # JSON-массив, и `None` уехал бы вместо `[]`.
        self.chat_intentions: list[str] = []


