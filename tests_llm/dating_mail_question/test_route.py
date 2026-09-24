"""Маршрут вопроса получателю: карточки, ворота «это вопрос?» и цикл.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.
"""

import pytest

from tests_llm.datingai import (CARD_MAN_NONE, MARK_GIRL, MARK_MAN)
from tests_llm.dating_mail_question.conftest import (HEAD_GIRL, HEAD_HINT,
                                                     HEAD_MAN, STEP_ASK,
                                                     STEP_CHECK, STEP_OUT,
                                                     STEP_WHY, TRIES_MAX)

pytestmark = pytest.mark.llm_live


class TestTheRunGoesThrough:
    """Первое: вопрос вообще сочиняется и проходит проверку."""

    async def test_the_run_ends_with_success(self, question):
        got = await question()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_question_is_checked(self, question):
        """⚠⚠ Ворота обязательны, и стоят они не для красоты.

        Пустая переменная означает «письма не будет» — а это несравнимо лучше,
        чем письмо, в котором живой человек читает мысли робота о себе. Отключи
        проверку, и рассуждение уедет внутрь абзаца.
        """
        got = await question()

        assert got.went_through(STEP_ASK), f'вопрос не сочинялся.{got}'
        assert got.went_through(STEP_CHECK), \
            f'вопрос уходит в письмо, минуя проверку.{got}'


class TestTheCardsReachThePrompt:
    """⚠⚠ Ради карточек вкладка «Собеседники» и заведена.

    Вопрос должен спрашивать про интересы человека, а интересы лежат в его
    описании. Без карточки агент напишет вежливое ничто — «чем вы увлекаетесь?»
    он читал сотню раз и не ответит.
    """

    async def test_the_man_card_is_shown(self, question):
        got = await question()
        prompt = got.prompt_of(STEP_ASK)

        assert HEAD_MAN in prompt, f'заголовка карточки получателя нет.{got}'
        assert MARK_MAN in prompt, \
            f'карточка получателя не подставилась.{got}'

    async def test_the_girl_card_is_shown(self, question):
        """⚠ Анкета девушки нужна затем, чтобы вопрос звучал **от неё**, а не от
        безличной панели."""
        got = await question()
        prompt = got.prompt_of(STEP_ASK)

        assert HEAD_GIRL in prompt, f'заголовка анкеты девушки нет.{got}'
        assert MARK_GIRL in prompt, f'анкета девушки не подставилась.{got}'

    async def test_an_unknown_man_is_said_plainly(self, question):
        """⚠ Карточки нет — так и говорим, а не оставляем пусто.

        Пустой блок промпта хуже честного «ничего не известно»: во втором случае
        агент задаст общий вопрос, в первом — выдумает увлечения.
        """
        got = await question(companion_card=CARD_MAN_NONE)
        prompt = got.prompt_of(STEP_ASK)

        assert CARD_MAN_NONE in prompt, \
            f'«о собеседнике ничего не известно» не доехало до промпта.{got}'

    async def test_the_language_is_demanded(self, question):
        got = await question(user_language='en')

        assert 'ЯЗЫК ВОПРОСА — en' in got.prompt_of(STEP_ASK), \
            f'требование языка не доехало до промпта.{got}'


class TestTheRewriteLoop:
    """⚠ Не прошли ворота — сочиняем заново, но не больше трёх раз.

    Проверяется **связь**, а не то, забракуют ли вопрос: это решает формальный
    признак в ответе модели.
    """

    async def test_a_second_pass_means_a_reason_was_collected(self, question):
        got = await question()

        if got.times(STEP_ASK) < 2:
            pytest.skip('вопрос прошёл с первого раза — цикла не было')

        assert got.went_through(STEP_WHY), \
            f'вопрос переписывался, а замечания никто не собирал.{got}'

    async def test_the_second_pass_is_told_what_was_wrong(self, question):
        got = await question()
        passes = got.prompt_each(STEP_ASK)

        if len(passes) < 2:
            pytest.skip('вопрос прошёл с первого раза — цикла не было')

        assert HEAD_HINT in passes[1], \
            f'второй заход сочинял, не зная, чем плох первый.{got}'

    async def test_the_first_pass_has_no_reproach(self, question):
        """⚠ Первому заходу замечания взяться неоткуда — блок под `%if%`.

        Пустое «НЕ ГОДИТСЯ:» в начале промпта модель читает как претензию
        неизвестно к чему и начинает оправдываться прямо в ответе.
        """
        got = await question()
        first = got.prompt_each(STEP_ASK)[:1]

        assert first, f'шага сочинения на маршруте нет.{got}'
        assert HEAD_HINT not in first[0], \
            f'первому заходу показали замечание, которого ещё нет.{got}'

    async def test_the_loop_has_a_ceiling(self, question):
        got = await question()

        assert got.times(STEP_ASK) <= TRIES_MAX, \
            (f'вопрос сочинялся {got.times(STEP_ASK)} раз при пределе'
             f' {TRIES_MAX}.{got}')


class TestTheAnswerIsTheQuestionAlone:
    """⚠ Наружу уходит одна переменная и ничего больше.

    Всё, что вернёт этот workflow, встанет **внутрь абзаца письма** как есть.
    Припиши шаг ответа хоть слово от себя — оно уедет живому человеку.
    """

    async def test_the_answer_step_carries_only_the_variable(self, question):
        got = await question()
        out = got.prompt_of(STEP_OUT)

        assert out, f'шага ответа на маршруте нет.{got}'
        assert '===' not in out and 'TITLE' not in out, \
            f'шаг ответа приписывает к вопросу что-то своё: {out[:120]!r}.{got}'
