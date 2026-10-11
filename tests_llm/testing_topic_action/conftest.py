"""Приметы шагов `testing_topic_action` — темы по меткам и её подпотока."""

AGENT = 'testing_topic_action'

STEP_TOPIC = 'Ветка темы'
STEP_FINAL = 'Финал'
STEP_CHILD_ASK = 'Вопросы темы'
STEP_CHILD_RAISED = 'Тема поднята?'
STEP_CHILD_MARK = 'Записать намерение'

# Что лежит в `instructions` темы сюиты — оно же намерение, которое обязано
# доехать до ответа.
INTENTION = 'probe_intention_mark'

# Текст с метками темы: `send` и `photo` — две разные, ровно порог.
TEXT_WITH_TAGS = 'can you send me a photo'
TEXT_WITHOUT_TAGS = 'how is the weather'
