"""Что доезжает до промпта письма избранному: доли панели, язык, время.

## ⚠⚠ Что здесь предмет проверки

Разнообразие пула задаёт **панель**: приём, длина, рассказ о себе (40%), вопрос
(25%) и показ времени приходят жребием из `favorite_mail.py`. «Иногда расскажи о
себе» модель понимает как «всегда» — ровно так же, как понимала «вставляй имя
изредка».

Значит договор: панель кладёт переменную — промпт её показывает либо прячет
целиком. Рвётся он в обе стороны и молча:

* переменная не доехала → модель сочиняет, чего не просили, прогон зелёный;
* `%if%` не сработал → пустой заголовок, и модель читает его как факт.

⚠ Ни один тест не утверждает, **послушалась ли** модель: это её свойство, и
проверка на него плавала бы. Утверждается только подстановка.
"""

import pytest

from tests_llm.datingai import SLOTS_MAN
from tests_llm.dating_favorite_mail_write.conftest import (HEAD_AVOID,
                                                           HEAD_COUNTRY,
                                                           HEAD_QUESTION,
                                                           HEAD_STORY,
                                                           HEAD_TIME,
                                                           STEP_DRAFT,
                                                           STEP_JUDGE,
                                                           STEP_TIME)

pytestmark = pytest.mark.llm

ANGLE = 'тёплое воспоминание о мелочи, которая рассмешила'
LENGTH = 'три абзаца'
STORY = 'как весь вечер искала ключи и нашла их в холодильнике'
AVOID = 'так уже было: «случайно наткнулась на нашу переписку»'


class TestTheDiceReachThePrompt:
    """Приём и длина — жребий панели, и он обязан быть виден модели."""

    async def test_the_angle_is_shown(self, favorite):
        got = await favorite(fav_angle=ANGLE)

        assert ANGLE in got.prompt_of(STEP_DRAFT), \
            f'приём не доехал до промпта — модель выберет свой.{got}'

    async def test_the_length_is_shown(self, favorite):
        got = await favorite(fav_length=LENGTH)

        assert LENGTH in got.prompt_of(STEP_DRAFT), \
            f'длина не доехала до промпта.{got}'

    async def test_the_judge_knows_the_asked_length(self, favorite):
        """⚠ Судье длина нужна затем, чтобы завернуть мимо просимой — это
        седьмой пункт его списка отказов. Не показали — пункт мёртв."""
        got = await favorite(fav_length=LENGTH)

        assert LENGTH in got.prompt_of(STEP_JUDGE), \
            f'судья не знает, какой длины ждать.{got}'


class TestTheStoryIsADice:
    """⚠⚠ Рассказ о себе — доля, а не постоянная часть письма.

    Он и есть то, чем письмо отличается от короткой реплики: в письме есть место
    для жизни. Но каждое второе письмо с рассказом читается как анкета, поэтому
    панель бросает жребий — и обе стороны обязаны работать.
    """

    async def test_a_story_opens_its_section(self, favorite):
        got = await favorite(fav_story=STORY)
        prompt = got.prompt_of(STEP_DRAFT)

        assert HEAD_STORY in prompt, f'заголовка рассказа нет.{got}'
        assert STORY in prompt, f'тема рассказа не подставилась.{got}'

    async def test_no_story_hides_the_section(self, favorite):
        """⚠ Пусто — заголовка нет вовсе. «Расскажи о себе ===» без темы модель
        прочтёт как «тему не дали, придумай» — и придумает."""
        got = await favorite(fav_story='')

        assert HEAD_STORY not in got.prompt_of(STEP_DRAFT), \
            f'рассказа не просили, а заголовок в промпте есть.{got}'

    async def test_no_story_switches_the_rule(self, favorite):
        """⚠⚠ Пустая ветка не просто прячет секцию — она ставит **другое
        правило**: «не пересказывай анкету и не перечисляй увлечений».

        Без него письмо без заданной темы сваливается в перечисление — это и
        есть то самое «читается как объявление».
        """
        got = await favorite(fav_story='')

        assert 'не перечисляй увлечений списком' in got.prompt_of(STEP_DRAFT), \
            f'без рассказа не встало правило про перечисление.{got}'


class TestTheQuestionIsADice:
    """⚠ Вопрос в конце — тоже доля, и у неё тоже две стороны.

    «Вопроса не нужно» промптом не говорят — его просто не просят; но здесь
    обратная ветка есть, и она объясняет модели, почему допрос молчание не лечит.
    """

    async def test_the_question_is_asked(self, favorite):
        got = await favorite(fav_question='1')

        assert HEAD_QUESTION in got.prompt_of(STEP_DRAFT), \
            f'вопрос просили, а секции в промпте нет.{got}'

    async def test_no_question_says_so_plainly(self, favorite):
        got = await favorite(fav_question='')
        prompt = got.prompt_of(STEP_DRAFT)

        assert HEAD_QUESTION not in prompt, \
            f'вопроса не просили, а секция в промпте есть.{got}'
        assert 'Вопроса НЕ НУЖНО' in prompt, \
            f'без вопроса не встало обратное правило.{got}'


class TestTheClock:
    """⚠⚠ Время просят только под рассказ, и это решение панели.

    «Как прошёл день» без часа выходит про несуществующий день; но время,
    показанное всегда, модель поминает почти в каждом тексте — на живом пуле
    инвайтов 94 из 202 за сутки.
    """

    async def test_the_clock_is_read_even_when_hidden(self, favorite):
        """⚠ Шаг часов идёт **всегда**, а в промпт время попадает по жребию:
        ветвить сам шаг значило бы держать развилку там, где хватает `%if%`."""
        got = await favorite(fav_time='')

        assert got.went_through(STEP_TIME), f'часы не спрошены вовсе.{got}'

    async def test_an_empty_flag_hides_the_time(self, favorite):
        got = await favorite(fav_time='')

        assert HEAD_TIME not in got.prompt_of(STEP_DRAFT), \
            f'жребий времени не выпал, а время в промпте есть.{got}'

    async def test_the_flag_shows_the_time(self, favorite):
        got = await favorite(fav_time='1')
        prompt = got.prompt_of(STEP_DRAFT)

        assert HEAD_TIME in prompt, f'жребий выпал, а времени в промпте нет.{got}'
        # ⚠ Мало заголовка: под ним обязан стоять **ответ инструмента**, а не
        # пустая строка. Год — примета, которая в его фразе есть всегда.
        assert '20' in prompt.split(HEAD_TIME, 1)[1][:200], \
            f'заголовок времени есть, а самого времени под ним нет.{got}'


class TestTheLanguageIsDemanded:
    """⚠⚠ Язык — не вкусовщина, а доставка.

    Фильтр сайта отклоняет письма не на том языке, и русское письмо до человека
    не дойдёт вовсе. Проверяем, что код **потребовал** язык, а не что модель
    послушалась: послушание — её свойство, и тест на него плавал бы.
    """

    async def test_the_language_reaches_the_draft(self, favorite):
        got = await favorite(user_language='en')
        prompt = got.prompt_of(STEP_DRAFT)
        head = 'Требуемый язык ответа (код) ==='

        assert head in prompt, f'заголовка языка в промпте нет.{got}'
        assert prompt.split(head, 1)[1].strip().startswith('en'), \
            f'под заголовком языка стоит не тот код.{got}'

    async def test_the_language_reaches_the_judge(self, favorite):
        got = await favorite(user_language='en')

        assert 'Язык (код): en' in got.prompt_of(STEP_JUDGE), \
            f'судья не знает, какого языка ждать.{got}'


class TestTheMarksAndTheRest:
    """Метки, страна и список прошлых писем."""

    async def test_the_man_mark_is_asked_by_name(self, favorite):
        """⚠ Метка названа дословно: выдуманная уедет человеку прямо в скобках."""
        got = await favorite(fav_slots=SLOTS_MAN)

        assert '[[companion_name]]' in got.prompt_of(STEP_DRAFT), \
            f'метка имени собеседника не названа в промпте.{got}'

    async def test_the_country_is_shown_and_hidden(self, favorite):
        shown = await favorite(fav_country='Ukraine')
        hidden = await favorite(fav_country='')

        assert 'Ukraine' in shown.prompt_of(STEP_DRAFT), \
            f'откуда девушка — не показано.{shown}'
        assert HEAD_COUNTRY not in hidden.prompt_of(STEP_DRAFT), \
            f'страны не передавали, а заголовок в промпте есть.{hidden}'

    async def test_the_avoid_list_reaches_both(self, favorite):
        """⚠ Список прошлых писем нужен и судье: «слишком похоже на прежнее» —
        двенадцатый пункт его отказов, и без списка он мёртв."""
        got = await favorite(fav_avoid=AVOID)

        assert AVOID in got.prompt_of(STEP_DRAFT), \
            f'список прошлых писем не доехал до сочинителя.{got}'
        assert AVOID in got.prompt_of(STEP_JUDGE), \
            f'список прошлых писем не доехал до судьи.{got}'

    async def test_an_empty_avoid_list_hides_the_block(self, favorite):
        got = await favorite(fav_avoid='')

        assert HEAD_AVOID not in got.prompt_of(STEP_DRAFT), \
            f'списка не передавали, а заголовок в промпте есть.{got}'


class TestThePastIsForbidden:
    """⚠⚠ Главное правило этого письма стоит в промпте **всегда**.

    Переписки пары агент не видит вовсе — значит любая подробность «мы говорили
    о…» выдумана, и адресат это заметит. Прежняя версия видела переписку и
    отталкивалась от неё; шаблон общий, и запрет обязан быть безусловным.

    ⚠ Проверяется наличие правила в промпте, а не послушание модели.
    """

    async def test_the_draft_is_forbidden_to_invent_a_past(self, favorite):
        got = await favorite()

        assert 'НИКОГДА НЕ ВЫДУМЫВАЙ ОБЩЕЕ ПРОШЛОЕ' in got.prompt_of(STEP_DRAFT), \
            f'запрет на выдуманное прошлое пропал из промпта.{got}'

    async def test_the_judge_checks_it_too(self, favorite):
        got = await favorite()

        assert 'ВЫДУМАННОЕ ОБЩЕЕ ПРОШЛОЕ' in got.prompt_of(STEP_JUDGE), \
            f'судья перестал проверять выдуманное прошлое.{got}'
