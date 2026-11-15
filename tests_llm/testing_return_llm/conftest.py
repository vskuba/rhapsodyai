"""Приметы шагов `testing_return_llm` — ответ LLM в переменную и мастер без финала.

Мастер: «Вопрос» (`return_response_llm`: ответ кладётся в переменную
`answer_stored`, `continue_workflow`) → «Эхо» (тот же тип, но без переменной,
тоже с продолжением) → «Финал» (`return_response_text` без продолжения: им
мастер и заканчивается). Агент носит имя workflow; нода `Testing`, модель —
подмена `fake/echo`.
"""

import pytest

AGENT = 'testing_return_llm'

STEP_ASK = 'Вопрос'
STEP_ECHO = 'Эхо'
STEP_FINAL = 'Финал'

# Ключ `output_variable` на «Вопросе»; на «Эхе» его нет — и писать он не должен.
VAR_ANSWER = 'answer_stored'

# Что отдаёт подмена: «Вопросу» — ANSWER, «Эху» — ECHO_ANSWER. Слово шаблона
# здесь — не проверяемая фраза, а plumbing сценария: по куску промпта подмена
# узнаёт, какой шаг спрашивает.
ANSWER = 'ответ из-под подмены'
ECHO_ANSWER = 'эхо ответа'

# Из `WORKFLOW_CANCEL_WORDS` движка; доходить обязано дословно.
CANCEL = 'отмена'


@pytest.fixture
def say(client, agent_of):
    """Реплика без `_unique` хвоста: слово отмены сравнивается целиком.

    `ask` приписывает к вопросу случайный хвост — так трасса находит прогон.
    Для «отмены» хвост губителен: сравнение в движке — равенство множеству
    `WORKFLOW_CANCEL_WORDS`, с хвостом оно не сработает вовсе.
    """

    async def _say(agent: str, text: str, session: str):
        return await client.post('/api/chat/ask', json={
            'question': text, 'agent_id': await agent_of(agent),
            'session_uuid': session, 'variables': {}})

    return _say
