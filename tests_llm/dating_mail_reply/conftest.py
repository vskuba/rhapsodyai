"""Оснастка workflow `dating_mail_reply` — ответ на письмо мужчины.

## Из чего он состоит

    Ответ      llm_to_json → reply
    Проверка   llm_to_json → reply_lang_ok, reply_clean_ok,
                             reply_topic_ok, reply_safe_ok
    Попытка    counter_increment
    Что не так собирает замечание из непрошедших и возвращает к сочинению
    Готово     %reply%

## ⚠⚠ Чем он отличается от шаблона письма

Здесь конкретика **нужна**, в отличие от `dating_mail_write`. Тот нарочно не
получает ни анкеты, ни собеседника: шаблон пишут для всех, и «Diana из Kyiv»
делает его годным одной анкете из сорока. Ответ адресован одному человеку — имена,
город и то, о чём он спросил, здесь не лишнее, а суть.

⚠ Отсюда же запрет на метки в ответе: это **готовый текст**, а не шаблон. Метка
`[[companion_name]]` уехала бы человеку прямо в скобках — за этим следит
`reply_clean_ok`.

## ⚠ История обязана быть непустой

Отвечать не на что — значит и звать агента незачем: он сочинит письмо-знакомство,
а его собеседник уже получал. Это проверяет сам DatingAi (`mail_reply` бросает
отказ), но в промпте история — единственное, от чего ответ отталкивается.
"""

import pytest

from tests_llm.datingai import CARD_GIRL, CARD_MAN
from tests_llm.conftest import LLM_SITE

# ⚠ Имя собирает DatingAi (`MAIL_REPLY_NAME`).
AGENT = f'mail_reply_{LLM_SITE}'

QUESTION = 'Напиши ответ на последнее письмо.'

# ── Приметы маршрута ────────────────────────────────────────────────────────

STEP_REPLY = 'Ответ'
STEP_CHECK = 'Проверка'
STEP_WHY = 'Что не так'
STEP_OUT = 'Готово'

# ── Приметы промпта ─────────────────────────────────────────────────────────

HEAD_HISTORY = '=== Переписка (старые сверху, последнее письмо — внизу) ==='
HEAD_GIRL = '=== Кто отвечает ==='
HEAD_MAN = '=== Кому отвечает ==='
HEAD_HINT = 'НЕ ГОДИТСЯ:'

# Четыре вопроса проверки. ⚠ Имена нужны затем, что от каждого отходит свой
# переход на цикл: пропади один — его брак перестанет ловиться молча.
CHECKS = ('reply_lang_ok', 'reply_clean_ok', 'reply_topic_ok', 'reply_safe_ok')

# Предел повторов — живёт в переходе шага «Что не так» (`reply_try < 3`).
TRIES_MAX = 3

# Переписка в том виде, в каком её собирает DatingAi (`_history_text`): подписи
# «Он» и «Она», старое сверху, абзацы через пустую строку.
#
# ⚠⚠ Подписи, а не имена: имена уже стоят в карточках, и третий раз они сбивают —
# модель начинает обращаться к себе по имени.
HISTORY = ('Она: Hi! Your profile made me smile — you look like someone with'
           ' stories.\n\n'
           'Он: Moto is my life. I restore old bikes and ride the Alps every'
           ' summer. What do you do on weekends?')

# Примета переписки для проверок подстановки.
MARK_HISTORY = 'ride the Alps every summer'


@pytest.fixture
async def reply(ask):
    """Попросить ответ на письмо. Возвращает `Talk` со всей трассой."""

    async def _reply(**over):
        return await ask(AGENT, QUESTION, {
            'mail_history': HISTORY,
            'girl_card': CARD_GIRL,
            'companion_card': CARD_MAN,
            'user_language': 'en',
            **over})

    return _reply
