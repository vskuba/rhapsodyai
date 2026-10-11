"""Тема по меткам: отсев, порог, подпоток и намерение в ответе.

⚠⚠ Фича движка целиком: шаг `topic_action` ищет метки темы в названном тексте,
прошедшая порог тема уходит в подпоток со своими вопросами, а оттуда намерение
попадает в ключ `intentions` ответа ручки.

Раньше это жило на `dating_talk` с его девятью метками и боевыми промптами —
и падало от переименования шага, правки инструкции темы и смены порога.
Здесь тема своя: две метки порога, один вопрос, инструкция-метка.
"""
import json

import pytest

from tests_llm.testing_topic_action.conftest import (AGENT, INTENTION,
                                                     STEP_CHILD_ASK,
                                                     STEP_CHILD_MARK,
                                                     STEP_FINAL, STEP_TOPIC,
                                                     TEXT_WITHOUT_TAGS,
                                                     TEXT_WITH_TAGS)

pytestmark = pytest.mark.llm

# Ответ подпотока: вопрос темы признан выполненным.
RAISED = json.dumps({'topic_yes_qty': 1})
REFUSED = json.dumps({'topic_yes_qty': 0})


class TestTheTagsRaiseTheTopic:
    """Отсев по меткам: что поднимает тему, а что нет."""

    async def test_tags_in_the_text_raise_it(self, ask, llm_answers):
        await llm_answers([], default=RAISED)

        got = await ask(AGENT, 'probe', variables={'topic_text': TEXT_WITH_TAGS})

        assert got.ran(STEP_TOPIC), f'шаг темы не отработал.{got}'
        assert got.ran(STEP_CHILD_ASK), f'подпоток темы не позвали.{got}'

    async def test_a_text_without_tags_raises_nothing(self, ask, llm_answers):
        """⚠⚠ Нет меток — нет повода: подпоток не зовут вовсе.

        Иначе каждая реплика гоняла бы модель по всем темам реестра, и цена
        разговора росла бы вместе с их числом.
        """
        await llm_answers([], default=RAISED)

        got = await ask(AGENT, 'probe', variables={'topic_text': TEXT_WITHOUT_TAGS})

        assert not got.ran(STEP_CHILD_ASK), \
            f'тема поднялась без меток в тексте.{got}'
        assert got.intentions == (), \
            f'намерение взялось там, где темы не было: {got.intentions}.{got}'


class TestTheQuestionDecides:
    """Порог меток — только вход; решают вопросы темы."""

    async def test_a_yes_keeps_the_intention(self, ask, llm_answers):
        """⚠ Ответов «yes» хватило — намерение записано и уехало в ответ."""
        await llm_answers([], default=RAISED)

        got = await ask(AGENT, 'probe', variables={'topic_text': TEXT_WITH_TAGS})

        assert got.ran(STEP_CHILD_MARK), f'шаг записи намерения не отработал.{got}'
        assert INTENTION in got.intentions, \
            f'намерение не доехало до ответа: {got.intentions}.{got}'

    async def test_a_no_skips_the_mark(self, ask, llm_answers):
        """⚠⚠ Метки нашлись, а вопрос ответил «нет» — намерения нет.

        Это и отличает метки от решения: метка лишь повод спросить. Пропади
        проверка — любое слово «photo» в разговоре становилось бы обещанием.
        """
        await llm_answers([], default=REFUSED)

        got = await ask(AGENT, 'probe', variables={'topic_text': TEXT_WITH_TAGS})

        assert got.ran(STEP_CHILD_ASK), f'вопрос темы не задавали вовсе.{got}'
        assert not got.ran(STEP_CHILD_MARK), \
            f'намерение записали при ответе «нет».{got}'
        assert got.intentions == (), \
            f'намерение уехало при ответе «нет»: {got.intentions}.{got}'


class TestTheInstructionComesBack:
    """Выход подпотока темы — инструкция, и она доезжает до родителя."""

    async def test_the_instruction_reaches_the_answer(self, ask, llm_answers):
        await llm_answers([], default=RAISED)

        got = await ask(AGENT, 'probe', variables={'topic_text': TEXT_WITH_TAGS})

        said = got.prompt_of(STEP_FINAL).strip()

        assert said == f'тема: {INTENTION}', \
            f'инструкция темы не доехала: {said!r}.{got}'

    async def test_without_a_topic_the_default_stands(self, ask, llm_answers):
        """⚠ Тема не поднялась — у родителя остаётся умолчание, а не пустота.

        Пустая переменная уехала бы в промпт меткой без значения и уронила бы
        заход сторожем движка.
        """
        await llm_answers([], default=RAISED)

        got = await ask(AGENT, 'probe', variables={'topic_text': TEXT_WITHOUT_TAGS})

        said = got.prompt_of(STEP_FINAL).strip()

        assert said == 'тема: нет', \
            f'умолчание не удержалось: {said!r}.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
