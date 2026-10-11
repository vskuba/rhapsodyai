"""Намерение доезжает от темы до ответа `/chat/ask` — весь путь целиком.

## ⚠⚠ Что здесь стережётся

Путь длинный и собран из частей, у каждой свой владелец:

    реплика с метками  →  шаг «Ветка намерений» (группа тем «Намерения»)
                       →  подпоток `dating_talk_intention`
                       →  вопросы темы, модель отвечает «yes»
                       →  шаг `chat_intention_add` c `topic_action_instructions`
                       →  накопитель `model.chat_intentions`
                       →  ключ `intentions` в ответе ручки

Любое звено рвётся **молча**: пустой список намерений — законный исход (их
могло не быть), и поломка выглядит как штатная тишина. Отдельные звенья
проверены своими тестами (`tests/test_chat_intentions.py` — инструмент,
движок, ключ ответа), а здесь — что они соединены.

⚠ Тема поднимается **кодом**, по меткам в тексте: порог `photo_send` — две
разные метки, и «send … photos» их даёт. Модель решает только вопрос темы
(«обещала ли она фото»), и ответ на него задан сценарием.

⚠⚠ Красное здесь — повод смотреть **трассу** (`/admin/workflow_trace`), а не
перезапускать: подмена отвечает одинаково, и от прогона к прогону маршрут не
меняется.
"""
import pytest

from tests_llm.dating_talk.conftest import (STEP_INTENTION, photo_answer,
                                            talk_plan)

pytestmark = pytest.mark.llm

# Что кладёт тема «Отправка фото» в инструкцию — она же намерение, которое
# обязано доехать. ⚠ Значение лежит в базе (`agent_workflow_topic.instructions`),
# и здесь повторено намеренно: тест проверяет, что доехало **именно оно**, а не
# «хоть что-нибудь».
INTENTION_PHOTO = 'she_promised_send_photo'

# Ответы подпотока намерений: тема признана поднятой. ⚠ Имена ключей — те, что
# просят его шаги («Вопросы намерений», «Намерения найдены?»).
INTENTION_FOUND = {'intentions_answer': 'yes',
                   'intentions_answer_yes_qty': '1',
                   'intentions_found': 'yes'}


class TestTheIntentionReachesTheAnswer:
    """Сквозной путь: реплика с метками → ключ `intentions` в ответе."""

    async def test_a_photo_promise_arrives_as_an_intention(self, talk, llm_answers):
        """⚠⚠ Главный случай, ради которого всё и делалось."""
        await llm_answers(talk_plan(), default=photo_answer(**INTENTION_FOUND))

        got = await talk('Can you send me your photos? I would love to see them')

        assert got.ran(STEP_INTENTION), \
            f'реплика с метками не дошла до шага намерений.{got}'
        assert INTENTION_PHOTO in got.intentions, \
            f'намерение не доехало до ответа ручки: {got.intentions}.{got}'

    async def test_a_quiet_talk_brings_no_intentions(self, talk, llm_answers):
        """⚠ Пустой список — законный исход, и он обязан быть **списком**.

        Реплика без меток темы не поднимает, намерений нет. Отсутствие ключа в
        ответе принимающая сторона свернула бы в то же пустое значение, и
        пропажа стала бы неотличима от этой штатной тишины.
        """
        await llm_answers(talk_plan())

        got = await talk('Tell me about your weekend')

        assert got.intentions == (), \
            f'намерения взялись там, где темы не было: {got.intentions}.{got}'

    async def test_the_same_intention_arrives_once(self, talk, llm_answers):
        """⚠⚠ Повтор метки в реплике не задваивает намерение.

        Шаг инструмента стоит в подпотоке, который зовут **по разу на
        поднятую тему**. Отсев повторов делает накопитель движка; пропади он —
        одно намерение приехало бы столько раз, сколько тем сработало.
        """
        await llm_answers(talk_plan(), default=photo_answer(**INTENTION_FOUND))

        got = await talk('Send me a photo, please send photos, show me a pic')

        assert list(got.intentions).count(INTENTION_PHOTO) <= 1, \
            f'намерение приехало дважды: {got.intentions}.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
