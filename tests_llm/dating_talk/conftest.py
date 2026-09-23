"""Оснастка workflow `dating_talk` — чат девушки с собеседником.

Здесь живёт всё, что верно **только для этого workflow**: имена его шагов и
фикстура вызова, подставляющая его агента и его обязательные переменные. Общее —
клиент, чтение трассы, `ask` — в `tests_llm/conftest.py`.

⚠ **Имена шагов — приметы маршрута, и берутся они из трассы как есть.** Переименуй
шаг в админке — тесты покраснеют, и это правильно: маршрут перестал быть тем,
который они стерегли.
"""

import os

import pytest

from tests_llm.conftest import LLM_GIRL_ID

# Агент чата. ⚠ Он **один на все анкеты** (`dating_girl_universal`): имя девушки
# и ключ её фактов уходят переменными вызова, а не своим агентом на каждую.
LLM_AGENT_NAME = os.getenv('LLM_AGENT_NAME', 'dating_girl_universal')

# ── Приметы маршрута ────────────────────────────────────────────────────────

STEP_TOPIC = 'Тема разговора'
STEP_BRANCH = 'Ветка: письма и фото'
STEP_FACTS_TAGS = 'qdrant_fact_search_girl_tags'
STEP_FACTS_PLAIN = 'qdrant_fact_search_girl'
STEP_ANSWER = 'Ответ'
# Шаг, сочиняющий реплику. ⚠ Не путать с `STEP_ANSWER`: тот отдаёт готовое
# наружу, а здесь собирается промпт — то, что вправду видит модель.
STEP_MAKE = 'Генерация ответа'

# ── Шаги фактов ─────────────────────────────────────────────────────────────
#
# Цепочка памяти: разобрать реплику → сохранить, что человек о себе сказал →
# поискать сохранённое к следующему разу. Проверяется она **шагами**, а не
# содержимым Qdrant: чужое хранилище отвечает своим темпом, и тест, ждущий в нём
# записи, мерил бы его задержку, а не нашу работу.
STEP_ANALYSE = 'Анализ сообщения'
# Подпрогон «сохранить факты о собеседнике» (workflow `companion_fact_extract`).
STEP_FACT_SAVE = 'companion_fact_extract'
STEP_FACT_SAVE_MAN = 'fact_collection_add_companion'
STEP_FACT_SAVE_TALK = 'fact_collection_add_talk'
# Подпрогон «придумать факты девушке» (workflow `girl_fact_invent`).
STEP_FACT_INVENT = 'girl_fact_create'
STEP_FACT_INVENT_ADD = 'fact_collection_add_girl'
# Поиск сохранённого.
STEP_FACTS_MAN = 'qdrant_fact_search_companion'
STEP_FACTS_TALK = 'qdrant_fact_search_talk'
# Судья и сторож повтора — последние ворота перед отправкой.
STEP_JUDGE = 'Валидация ответа'
STEP_REPEAT = 'Проверка повтора'
STEP_SILENCE = 'Тишина'


@pytest.fixture
async def talk(ask):
    """Задать агенту реплику и получить ответ вместе с маршрутом.

    Args:
        question: что пишет собеседник.
        history: разговор пары строками, старое сверху (`talk_history`).
        variables: что ещё положить в переменные вызова.

    ⚠⚠ **Таймаут поднимаем переменной, и только здесь это можно.** У движка свои
    60 секунд, а заход, где модель заводит факты девушки с нуля, идёт минуту.
    `chat_timeout` объявлена входящей у `dating_talk` — у почтовых workflow её
    нет, и слать её туда нельзя.
    """
    from tests_llm.conftest import LLM_TIMEOUT

    async def _talk(question: str, history: str = '', variables: dict = None):
        return await ask(LLM_AGENT_NAME, question, {
            'chat_timeout': LLM_TIMEOUT,
            'talk_history': str(history or ''),
            # ⚠ Ключ девушки — **до** переменных вызова: тест вправе задать свой,
            # но по умолчанию получает тестовый, а не рабочий.
            'girl_id': LLM_GIRL_ID,
            **(variables or {})})

    return _talk
