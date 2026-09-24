"""Маршрут заполнения переменных: заготовка, проверка полноты и цикл.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.

## ⚠ Одна оговорка, и она здесь важна

Ответ этого workflow — вывод **инструмента** `dict_fields_check`, а не модели.
Инструмент берёт её словарь и оставляет в нём **только запрошенные ключи**
(`src/tool/dict/dict_.py`): что бы модель ни придумала, лишнее не пройдёт.

Поэтому утверждения о **составе ключей** законны: они верны при любом ответе
модели и проверяют код. Утверждения о **значениях** — нет, и их здесь не будет.
"""

import json

import pytest

from tests_llm.datingai import CARD_GIRL
from tests_llm.dating_mail_vars.conftest import (HEAD_HINT, STEP_CHECK,
                                                 STEP_FILL, STEP_OUT, STEP_WHY,
                                                 TRIES_MAX, VARS_JSON,
                                                 VARS_NAMES, VARS_TEXT)

pytestmark = pytest.mark.llm_live

WANTED = tuple(VARS_NAMES.split(','))


class TestTheRunGoesThrough:
    """Первое: переменные вообще заполняются и проходят проверку."""

    async def test_the_run_ends_with_success(self, fill):
        got = await fill()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_filling_goes_through_the_check(self, fill):
        """⚠⚠ Проверку полноты делает **код**, а не модель.

        Спрашивать у неё «все ли поля заполнены?» — значит просить проверить саму
        себя: на такой вопрос она отвечает утвердительно почти всегда.
        """
        got = await fill()

        assert got.went_through(STEP_FILL), f'переменные не заполнялись.{got}'
        assert got.went_through(STEP_CHECK), \
            f'заполненное уходит в базу, минуя проверку полноты.{got}'


class TestTheBlankReachesThePrompt:
    """⚠⚠ Заготовка ответа уходит агенту с **настоящими** ключами.

    Прежде промпт давал пример с выдуманными именами и надеялся, что модель
    переложит на них имена из списка. Это лишняя работа для неё и лишний повод
    ошибиться: ключи известны нам точно, и собрать их — одна строка
    (`mail_agent._blank_json`).
    """

    async def test_the_blank_json_is_shown(self, fill):
        got = await fill()

        assert VARS_JSON in got.prompt_of(STEP_FILL), \
            f'заготовка ответа не доехала до промпта.{got}'

    async def test_the_registry_is_shown_with_labels(self, fill):
        """⚠ Подписи модель читает: `girl_job` без пояснения «чем она занимается»
        она заполнит чем угодно."""
        got = await fill()

        assert VARS_TEXT in got.prompt_of(STEP_FILL), \
            f'реестр переменных не доехал до промпта.{got}'

    async def test_the_card_is_shown(self, fill):
        got = await fill()

        assert CARD_GIRL in got.prompt_of(STEP_FILL), \
            f'сведения об анкете не доехали до промпта.{got}'

    async def test_the_language_is_demanded(self, fill):
        got = await fill(user_language='en')

        assert 'значения на языке en' in got.prompt_of(STEP_FILL), \
            f'требование языка не доехало до промпта.{got}'

    async def test_the_prompt_forbids_inventing(self, fill):
        """⚠⚠ «Чего в анкете нет — оставь пустым» — правило, а не вежливость.

        Письмо с незаполненной переменной не уйдёт, и это правильный исход.
        Письмо с выдуманным городом уйдёт живому человеку.
        """
        got = await fill()
        prompt = got.prompt_of(STEP_FILL)

        assert 'не выдумывай' in prompt, \
            f'запрет на выдумывание пропал из промпта.{got}'
        assert 'оставь пустым' in prompt, \
            f'правило «нет в анкете — оставь пустым» пропало из промпта.{got}'


class TestTheAnswerKeepsOnlyWhatWasAsked:
    """⚠⚠ Состав ключей держит инструмент, а не модель — и это проверяемо.

    `dict_fields_check` обходит **запрошенный** список и складывает в ответ
    только его ключи. Что бы модель ни придумала сверх реестра, до подстановки в
    письмо это не доедет.

    ⚠ Проверка не праздная: на другой стороне, в DatingAi, стоит второй такой же
    отсев (`mail_agent._values`). Два отсева — не перестраховка: этот бережёт
    цикл повторов от ложной полноты, тот бережёт базу от чужих имён.
    """

    async def test_the_answer_is_json(self, fill):
        got = await fill()

        try:
            json.loads(got.prompt_of(STEP_OUT))
        except (TypeError, ValueError) as e:
            pytest.fail(f'ответ не разбирается как JSON: {e}.{got}')

    async def test_no_invented_keys_get_through(self, fill):
        got = await fill()
        values = json.loads(got.prompt_of(STEP_OUT) or '{}')

        extra = sorted(set(values) - set(WANTED))

        assert not extra, f'в ответ просочились незапрошенные ключи: {extra}.{got}'

    async def test_empty_values_are_dropped(self, fill):
        """⚠ Пустые значения в ответ не идут: подставленная пустота дала бы
        письмо с дырой на месте имени, а такое письмо уходить не должно."""
        got = await fill()
        values = json.loads(got.prompt_of(STEP_OUT) or '{}')

        blank = sorted(name for name, value in values.items()
                       if not str(value).strip())

        assert not blank, f'в ответ попали пустые значения: {blank}.{got}'


class TestTheRewriteLoop:
    """⚠ Чего не хватило — просим заново, но не больше трёх раз."""

    async def test_a_second_pass_means_a_reason_was_collected(self, fill):
        got = await fill()

        if got.times(STEP_FILL) < 2:
            pytest.skip('переменные заполнились с первого раза — цикла не было')

        assert got.went_through(STEP_WHY), \
            f'заход повторялся, а нехватку никто не собирал.{got}'

    async def test_the_second_pass_is_told_what_is_missing(self, fill):
        """⚠⚠ Второму заходу называют **имена** незаполненных, а не «заполни всё».

        Список собирает тот же инструмент, и он же решает, был ли повтор нужен:
        два источника этого знания разошлись бы, и цикл крутился бы из-за поля,
        которое уже заполнено.
        """
        got = await fill()
        passes = got.prompt_each(STEP_FILL)

        if len(passes) < 2:
            pytest.skip('переменные заполнились с первого раза — цикла не было')

        assert HEAD_HINT in passes[1], \
            f'второй заход не знает, чего не хватило.{got}'

    async def test_the_first_pass_has_no_reproach(self, fill):
        got = await fill()
        first = got.prompt_each(STEP_FILL)[:1]

        assert first, f'шага заполнения на маршруте нет.{got}'
        assert HEAD_HINT not in first[0], \
            f'первому заходу показали нехватку, которой ещё нет.{got}'

    async def test_the_loop_has_a_ceiling(self, fill):
        got = await fill()

        assert got.times(STEP_FILL) <= TRIES_MAX, \
            (f'переменные заполнялись {got.times(STEP_FILL)} раз при пределе'
             f' {TRIES_MAX}.{got}')
