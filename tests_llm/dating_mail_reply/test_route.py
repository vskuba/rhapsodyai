"""Маршрут ответа на письмо: история, четыре проверки и цикл.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.
"""

import pytest

from tests_llm.datingai import (MARK_GIRL, MARK_MAN)
from tests_llm.dating_mail_reply.conftest import (CHECKS, HEAD_GIRL,
                                                  HEAD_HINT, HEAD_HISTORY,
                                                  HEAD_MAN, MARK_HISTORY,
                                                  STEP_CHECK, STEP_OUT,
                                                  STEP_REPLY, STEP_WHY,
                                                  TRIES_MAX)

pytestmark = pytest.mark.llm_live


class TestTheRunGoesThrough:
    """Первое: ответ вообще сочиняется и проходит проверку."""

    async def test_the_run_ends_with_success(self, reply):
        got = await reply()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_reply_goes_through_the_check(self, reply):
        got = await reply()

        assert got.went_through(STEP_REPLY), f'ответ не сочинялся.{got}'
        assert got.went_through(STEP_CHECK), \
            f'ответ уходит человеку, минуя проверку.{got}'


class TestTheHistoryReachesThePrompt:
    """⚠⚠ История — единственное, от чего ответ отталкивается.

    Без неё агент сочинит письмо-знакомство, а собеседник его уже получал.
    Поэтому переписка обязана доехать **и до сочинителя, и до проверки**: без неё
    проверка «ответ по существу последнего письма» не может быть сделана вовсе.
    """

    async def test_the_history_reaches_the_writer(self, reply):
        got = await reply()
        prompt = got.prompt_of(STEP_REPLY)

        assert HEAD_HISTORY in prompt, f'заголовка переписки нет.{got}'
        assert MARK_HISTORY in prompt, f'переписка не подставилась.{got}'

    async def test_the_history_reaches_the_check(self, reply):
        """⚠ Иначе `reply_topic_ok` отвечает наугад: судить «подхватил ли тему»
        не по чему."""
        got = await reply()

        assert MARK_HISTORY in got.prompt_of(STEP_CHECK), \
            f'проверка не видит переписки, а судит по ней.{got}'

    async def test_the_speakers_are_labelled_not_named(self, reply):
        """⚠⚠ Подписи «Он» и «Она», а не имена.

        Имена уже стоят в карточках, и третий раз они сбивают: модель начинает
        обращаться к себе по имени. Здесь важно одно — кто из двоих говорит.
        """
        got = await reply()
        history = got.prompt_of(STEP_REPLY).split(HEAD_HISTORY, 1)[1][:600]

        assert 'Он:' in history and 'Она:' in history, \
            f'в переписке нет подписей говорящих.{got}'


class TestTheCardsReachThePrompt:
    """⚠ Здесь карточки нужны, в отличие от шаблона письма."""

    async def test_both_cards_are_shown(self, reply):
        got = await reply()
        prompt = got.prompt_of(STEP_REPLY)

        assert HEAD_GIRL in prompt and MARK_GIRL in prompt, \
            f'анкета девушки не доехала до промпта.{got}'
        assert HEAD_MAN in prompt and MARK_MAN in prompt, \
            f'карточка собеседника не доехала до промпта.{got}'

    async def test_the_language_is_demanded(self, reply):
        got = await reply(user_language='en')

        assert 'Язык ответа: en' in got.prompt_of(STEP_REPLY), \
            f'требование языка не доехало до промпта.{got}'


class TestAllFourChecksAreAsked:
    """⚠⚠ Четыре вопроса, и каждый со своим переходом на цикл.

    Пропади любой из промпта проверки — его брак перестанет ловиться, и **молча**:
    переход останется, переменная будет пустой, условие `== 0` не сработает.
    Прогон при этом зелёный.

    ⚠ Проверяем, что вопрос **задан**, а не какой пришёл ответ: ответ — дело
    модели.
    """

    @pytest.mark.parametrize('name', CHECKS)
    async def test_the_check_is_asked(self, reply, name):
        got = await reply()

        assert name in got.prompt_of(STEP_CHECK), \
            f'проверка «{name}» пропала из промпта.{got}'

    async def test_the_check_is_told_to_doubt_in_favour(self, reply):
        """⚠⚠ «Сомневаешься — ставь 1» стоит в промпте не из мягкости.

        Ложная тревога дороже пропуска: она заставляет переписывать хороший ответ
        (вызов модели и заход цикла), а слабый всё равно прочтёт человек.
        """
        got = await reply()

        assert 'Сомневаешься — ставь 1' in got.prompt_of(STEP_CHECK), \
            f'правило «сомневаешься — пропусти» пропало из промпта.{got}'


class TestTheRewriteLoop:
    """⚠ Не прошла проверка — сочиняем заново, но не больше трёх раз."""

    async def test_a_second_pass_means_a_reason_was_collected(self, reply):
        got = await reply()

        if got.times(STEP_REPLY) < 2:
            pytest.skip('ответ прошёл с первого раза — цикла не было')

        assert got.went_through(STEP_WHY), \
            f'ответ переписывался, а замечания никто не собирал.{got}'

    async def test_the_second_pass_is_told_what_was_wrong(self, reply):
        got = await reply()
        passes = got.prompt_each(STEP_REPLY)

        if len(passes) < 2:
            pytest.skip('ответ прошёл с первого раза — цикла не было')

        assert HEAD_HINT in passes[1], \
            f'второй заход сочинял, не зная, чем плох первый.{got}'

    async def test_the_first_pass_has_no_reproach(self, reply):
        """⚠ Пустое «НЕ ГОДИТСЯ:» в начале промпта модель читает как претензию
        неизвестно к чему — оттого блок под `%if%`."""
        got = await reply()
        first = got.prompt_each(STEP_REPLY)[:1]

        assert first, f'шага сочинения на маршруте нет.{got}'
        assert HEAD_HINT not in first[0], \
            f'первому заходу показали замечание, которого ещё нет.{got}'

    async def test_the_loop_has_a_ceiling(self, reply):
        got = await reply()

        assert got.times(STEP_REPLY) <= TRIES_MAX, \
            (f'ответ сочинялся {got.times(STEP_REPLY)} раз при пределе'
             f' {TRIES_MAX}.{got}')


class TestTheAnswerIsTheReplyAlone:
    """⚠ Наружу уходит одна переменная: ответ отправляется человеку как есть."""

    async def test_the_answer_step_carries_only_the_variable(self, reply):
        got = await reply()
        out = got.prompt_of(STEP_OUT)

        assert out, f'шага ответа на маршруте нет.{got}'
        assert '===' not in out and 'VERDICT' not in out, \
            f'шаг ответа приписывает к письму что-то своё: {out[:120]!r}.{got}'
