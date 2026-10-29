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

        # Номер строки журнала прогона (`agent_workflow_trace.id`). Кладёт движок
        # сразу после её заведения; читает ручка, чтобы дописать туда ответ
        # контракта — что ушло зовущему.
        #
        # ⚠ Поле на модели, а не в ответе движка: ручке номер нужен и на отказе
        # (таймаут, исключение), когда отвечать движку уже нечем.
        self.trace_run_id: int | None = None

        # Тело запроса, которым позвали, — как его объявила ручка. Движок
        # переносит это в журнал прогона не разбирая (`request_json`).
        #
        # ⚠⚠ Кладётся ДО запуска: прогон читают и пока он идёт, а у зависшего
        # вопрос «чем его позвали» первый по порядку. Пиши ручка контракт после
        # ответа — у зависших его не было бы никогда, то есть ровно там, где он
        # нужнее всего.
        self.contract_request: dict | None = None

        # Намерения, накопленные за прогон инструментом `chat_intention_add`:
        # их забирает ручка `/chat/ask` ключом `intentions`.
        #
        # ⚠ Словарь, а не строка: за один прогон законны несколько намерений, и
        # побеждать последнему тут нельзя — в отличие от номера обмена выше.
        #
        # ⚠⚠ **Ключ — намерение, значение — его контекст.** Метка словом
        # отвечает «что решили», но не «с чем это делать»: намерению «послать
        # письмо» нужен текст письма, «позвонить» — время, «купить» — список.
        # Контекст собирается **в том же прогоне**, пока разговор под рукой;
        # собирать его потом значило бы заново добывать то, что уже было в
        # руках.
        #
        # ⚠ Пустой словарь — законное значение: намерение помечено, а контекст
        # к нему ещё не собран (или не нужен вовсе).
        #
        # ⚠ Заводится пустым словарём, а не `None`: поле уезжает наружу как
        # JSON-объект, и `None` уехал бы вместо `{}`.
        self.chat_intentions: dict[str, dict] = {}


