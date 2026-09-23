"""Маршрут черновика письма: пять ворот, цикл переписывания и конверт.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.

## ⚠ Почему проверки маршрута здесь важнее, чем у других workflow

Ворот пять, и четверо из них — обычные инструменты, а не модель: они считают
метки и ищут неизвестные имена. Отключись любые — прогон останется зелёным,
письмо придёт, и брак заметит только человек. Или не заметит: шаблон уходит в
рассылку сотням людей.
"""

import pytest

from tests_llm.datingai import TITLE_MARK
from tests_llm.dating_mail_write.conftest import (STEP_INLINE, STEP_LANG,
                                                  STEP_MISSING, STEP_OUT,
                                                  STEP_SAME, STEP_VARS,
                                                  STEP_WHY, STEP_WRITE,
                                                  TRIES_MAX)

pytestmark = pytest.mark.llm


class TestTheRunGoesThrough:
    """Первое: черновик вообще сочиняется."""

    async def test_the_run_ends_with_success(self, letter):
        got = await letter()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_letter_is_written(self, letter):
        got = await letter()

        assert got.went_through(STEP_WRITE), f'письмо не сочинялось.{got}'


class TestEveryGateIsPassed:
    """⚠⚠ Все пять проверок обязаны стоять на пути, а не половина.

    Каждая заведена по живому случаю, и каждая ловит своё:

    | Ворота | Что ловят |
    |---|---|
    | Переменные | выдуманную метку — уедет человеку прямо в скобках |
    | Язык верный? | чужой язык — фильтр сайта письмо отклонит |
    | Вопрос отдельно? | живую метку внутри фразы: «What are What do you enjoy??» |
    | Все ли метки? | имена, написанные словами вместо переменных |
    | Судья: не повтор ли? | четвёртое письмо подряд про плед и дождь |
    """

    async def test_the_unknown_marks_are_checked(self, letter):
        got = await letter()

        assert got.went_through(STEP_VARS), \
            f'выдуманные метки никто не ищет.{got}'

    async def test_the_language_is_checked(self, letter):
        got = await letter()

        assert got.went_through(STEP_LANG), \
            f'язык письма никто не проверяет.{got}'

    async def test_the_inline_marks_are_checked(self, letter):
        got = await letter()

        assert got.went_through(STEP_INLINE), \
            f'встроенные в фразу живые метки никто не ищет.{got}'

    async def test_the_missing_marks_are_checked(self, letter):
        """⚠ Эти ворота заведены последними и отвечают на четвёртый вопрос.

        Шаблон, где половина имён написана словами, проходил все прежние
        проверки: лишнего в нём нет, язык верен, живой метки нет — значит она «не
        встроена». Полноту спросить было некому.
        """
        got = await letter()

        assert got.went_through(STEP_MISSING), \
            f'полноту меток никто не проверяет.{got}'

    async def test_the_repeat_judge_runs(self, letter):
        got = await letter()

        assert got.went_through(STEP_SAME), \
            f'повтор прошлых писем никто не судит.{got}'


class TestTheRewriteLoop:
    """⚠⚠ Цикл переписывания: не прошли ворота — заходим заново.

    Проверяется **связь**, а не то, забракуют ли черновик: забракуют или нет,
    решают модель и инструменты. Зато связь «был второй заход ⇔ шёл шаг
    замечания» держит движок.
    """

    async def test_a_second_pass_means_a_reason_was_collected(self, letter):
        got = await letter()

        if got.times(STEP_WRITE) < 2:
            pytest.skip('черновик прошёл с первого раза — цикла не было')

        assert got.went_through(STEP_WHY), \
            f'письмо переписывалось, а замечания никто не собирал.{got}'
        assert got.times(STEP_WHY) == got.times(STEP_WRITE) - 1, \
            (f'заходов {got.times(STEP_WRITE)}, а замечаний'
             f' {got.times(STEP_WHY)}.{got}')

    async def test_the_second_pass_is_told_what_was_wrong(self, letter):
        """⚠ Второй заход обязан **видеть** замечание: без него он переписывал бы
        наугад и с тем же успехом."""
        got = await letter()
        passes = got.prompt_each(STEP_WRITE)

        if len(passes) < 2:
            pytest.skip('черновик прошёл с первого раза — цикла не было')

        assert 'НЕ ГОДИТСЯ:' in passes[1], \
            f'второй заход сочинял, не зная, чем плох первый.{got}'

    async def test_the_loop_has_a_ceiling(self, letter):
        """⚠⚠ Потолок обязателен, и он не «на всякий случай».

        Без него негодный черновик крутил бы цикл, пока не оборвётся таймаут
        движка, — и человек получил бы `504` вместо письма с изъяном. Три захода
        это уже минута ожидания.
        """
        got = await letter()

        assert got.times(STEP_WRITE) <= TRIES_MAX, \
            (f'письмо сочинялось {got.times(STEP_WRITE)} раз при пределе'
             f' {TRIES_MAX}.{got}')


class TestTheEnvelope:
    """⚠⚠ Название и текст приходят одной строкой — это договор с DatingAi.

    Разбирает его `mail_agent._letter_named`: метка `TITLE:`, перенос, письмо.
    JSON тут не годится — в письме переносы строк, а `%letter%` их не
    экранирует, и первый же порвал бы разбор.
    """

    async def test_the_answer_starts_with_the_title_mark(self, letter):
        got = await letter()
        envelope = got.prompt_of(STEP_OUT)

        assert envelope, f'шага ответа на маршруте нет.{got}'
        assert envelope.lstrip().startswith(TITLE_MARK), \
            f'ответ начинается не с метки названия: {envelope[:120]!r}.{got}'

    async def test_the_title_and_the_letter_are_separated(self, letter):
        """⚠ Разделитель — пустая строка: по первому переносу режет разбор, и
        слипшись, название уехало бы в текст письма."""
        got = await letter()
        envelope = got.prompt_of(STEP_OUT)

        head, _, tail = envelope.partition('\n')

        assert head.strip() != envelope.strip(), \
            f'название и письмо не разделены переносом.{got}'
        assert tail.strip(), f'после названия письма нет вовсе.{got}'
