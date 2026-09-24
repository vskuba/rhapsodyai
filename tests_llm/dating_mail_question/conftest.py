"""Оснастка workflow `dating_mail_question` — живой вопрос получателю письма.

## Из чего он состоит

    Вопрос       llm_to_json → question
    Это вопрос?  text_regex_extract по `ask_pattern`
    Попытка      counter_increment
    Что не так   собирает замечание и возвращает к сочинению (до трёх раз)
    Готово       %question%

## ⚠⚠ Зачем он отдельно от письма

Вопрос сочиняется **на каждую пару «анкета — получатель»**, а шаблон письма — раз
в сутки на весь сайт. Разная частота, разная цена, разный повод: письмо пишется
не зная никого, вопрос — прочитав профиль конкретного человека.

Отсюда и цена: вызов LLM на письмо. Рассылка зовёт его только там, где живая
переменная в шаблоне вправду есть.

## ⚠ Чем проверка «это вопрос?» держится

Формальным признаком: ответ обязан кончаться знаком вопроса. Поймано живым
кругом — из ста писем одно ушло бы с рассуждением модели вместо вопроса:

    «Given the description of the letter, I need to ask Matthias a question
    about his interests. Since we don't know much about his profile…»

Первым абзацем оно и было, кавычек не имело, длину прошло. Отличает его от
вопроса ровно одно — знак на конце.
"""

import pytest

from tests_llm.datingai import CARD_GIRL, CARD_MAN
from tests_llm.conftest import LLM_SITE
from tests_llm.plan import plan_load
from tests_llm.dating_mail_question.fixtures import PLAN_OK

# ⚠ Имя собирает DatingAi (`MAIL_QUESTION_NAME`) — и оно **не** `mail_question`:
# приставка у агента своя.
AGENT = f'mail_ask_{LLM_SITE}'

QUESTION = 'Придумай вопрос получателю.'

# ── Приметы маршрута ────────────────────────────────────────────────────────

STEP_ASK = 'Вопрос'
STEP_CHECK = 'Это вопрос?'
STEP_WHY = 'Что не так'
STEP_OUT = 'Готово'

# ── Приметы промпта ─────────────────────────────────────────────────────────

HEAD_MAN = '=== Что известно о получателе ==='
HEAD_GIRL = '=== Кто пишет ==='
HEAD_HINT = 'НЕ ГОДИТСЯ:'

# Предел повторов — живёт в переходе шага «Что не так» (`ask_try < 3`).
TRIES_MAX = 3


@pytest.fixture
async def question(ask):
    """Попросить вопрос получателю. Возвращает `Talk` со всей трассой."""

    async def _question(**over):
        return await ask(AGENT, QUESTION, {
            'girl_card': CARD_GIRL,
            'companion_card': CARD_MAN,
            'user_language': 'en',
            **over})

    return _question


# ── Сценарий ответов модели ─────────────────────────────────────────────────
#
# ⚠ Данные — в `fixtures.py`, механика — в `tests_llm/plan.py`. Здесь только
# связь: что берётся по умолчанию.


@pytest.fixture
def llm_plan():
    """Заготовка: вопрос годен с первого раза.

    ⚠ Тесту, которому нужно иное, кладёт своё **перед** заготовкой:
    `await llm_answers(plan_load(PLAN_ЧТО_ТО, PLAN_OK))`.
    """
    return plan_load(PLAN_OK)
