"""Что доезжает до промпта инвайта: доли панели, язык и время.

## ⚠⚠ Почему это отдельный предмет проверки

Разнообразие пула задаёт **панель**, а не модель: «будь разной» она не понимает —
живой прогон дал три шаблона из трёх, начинавшихся с «you're trouble». Поэтому
приём, длина, метки имён и показ времени приходят снаружи жребием
(`invite.py` в DatingAi), а промпт их подставляет.

Значит есть договор: панель кладёт переменную — промпт её показывает. Рвётся он
молча и в обе стороны:

* переменная не доехала → модель сочиняет, чего не просили, а прогон зелёный;
* `%if%` не сработал → пустой заголовок, и модель читает его как факт.

⚠ Проверки здесь **не про сочинение**, а про подстановку: `%if%` либо развернулся,
либо нет, и удача на это не влияет.
"""

import pytest

from tests_llm.datingai import (SLOTS_MAN, SLOTS_NONE)
from tests_llm.dating_invite_write.conftest import (HEAD_AVOID, HEAD_COUNTRY,
                                                    HEAD_TIME, STEP_DRAFT,
                                                    STEP_JUDGE, STEP_TIME)

pytestmark = pytest.mark.llm_live

ANGLE = 'дерзкий вызов, на который хочется ответить сразу'
LENGTH = 'одна фраза, не длиннее десяти слов'

# Что уже писали этому сайту. ⚠ Строка приметная: по ней видно, что в промпт
# попал именно наш список, а не совпадение.
AVOID = 'так уже было: «спорим, ты сейчас улыбнулся»'


class TestTheDiceReachThePrompt:
    """Приём и длина — жребий панели, и он обязан быть виден модели."""

    async def test_the_angle_is_shown(self, invite):
        got = await invite(invite_angle=ANGLE)

        assert ANGLE in got.prompt_of(STEP_DRAFT), \
            f'приём не доехал до промпта — модель выберет свой.{got}'

    async def test_the_length_is_shown(self, invite):
        got = await invite(invite_length=LENGTH)

        assert LENGTH in got.prompt_of(STEP_DRAFT), \
            f'длина не доехала до промпта.{got}'

    async def test_the_country_is_shown(self, invite):
        got = await invite(invite_country='Ukraine')
        prompt = got.prompt_of(STEP_DRAFT)

        assert HEAD_COUNTRY in prompt and 'Ukraine' in prompt, \
            f'откуда девушка — не показано.{got}'

    async def test_an_empty_country_hides_the_block(self, invite):
        """⚠ Пусто — заголовка нет вовсе. «Откуда ты ===» без ответа модель
        прочтёт как «места нет», и место появится выдуманное."""
        got = await invite(invite_country='')

        assert HEAD_COUNTRY not in got.prompt_of(STEP_DRAFT), \
            f'страны не передавали, а заголовок в промпте есть.{got}'


class TestTheMarksAreOrdered:
    """⚠⚠ Метки имён просит панель, а не решает модель.

    Вероятности заданы снаружи (5% её имя, 30% его), и «вставляй имя иногда»
    модель понимает как «вставляй всегда». В промпт уходит **готовое указание**
    (`mail_agent._slots`), потому что шаблонизатор соседа условий не понимает.
    """

    async def test_no_marks_asked_is_said_plainly(self, invite):
        got = await invite(invite_slots=SLOTS_NONE)

        assert SLOTS_NONE in got.prompt_of(STEP_DRAFT), \
            f'указание «меток не нужно» не доехало.{got}'

    async def test_the_man_mark_is_asked_by_name(self, invite):
        """⚠ Метка названа **дословно**: выдуманная уедет человеку прямо в
        скобках, и панель её не подставит."""
        got = await invite(invite_slots=SLOTS_MAN)
        prompt = got.prompt_of(STEP_DRAFT)

        assert '[[companion_name]]' in prompt, \
            f'метка имени собеседника не названа в промпте.{got}'

    async def test_the_judge_knows_what_was_asked(self, invite):
        """⚠⚠ Судья обязан знать, что просили, — иначе он не отличит пропущенную
        метку от той, которой не просили вовсе."""
        got = await invite(invite_slots=SLOTS_MAN)

        assert '[[companion_name]]' in got.prompt_of(STEP_JUDGE), \
            f'судья не знает, каких меток ждать.{got}'


class TestTheClock:
    """⚠⚠ Время суток — самая заметная примета робота.

    В пуле прода лежал шаблон «My thoughts have turned sideways **tonight**» —
    модель писала про вечер, не зная, который час. Живой человек в этом не
    ошибается.

    ⚠ Но показывать время **всегда** оказалось хуже: она поминала его почти в
    каждой реплике — 94 из 202 за сутки. Отсюда жребий `invite_time`, и отсюда же
    два теста ниже: на обе стороны.
    """

    async def test_the_clock_is_read_even_when_hidden(self, invite):
        """⚠ Шаг часов идёт **всегда**, а в промпт время попадает по жребию.

        Это не лишняя работа: инструмент дешёвый и местный, а ветвить сам шаг
        значило бы держать развилку там, где хватает `%if%` в тексте.
        """
        got = await invite(invite_time='')

        assert got.went_through(STEP_TIME), \
            f'часы не спрошены вовсе.{got}'

    async def test_an_empty_flag_hides_the_time(self, invite):
        got = await invite(invite_time='')

        assert HEAD_TIME not in got.prompt_of(STEP_DRAFT), \
            f'жребий времени не выпал, а время в промпте есть.{got}'

    async def test_the_flag_shows_the_time(self, invite):
        got = await invite(invite_time='1')
        prompt = got.prompt_of(STEP_DRAFT)

        assert HEAD_TIME in prompt, \
            f'жребий выпал, а времени в промпте нет.{got}'
        # ⚠ Мало заголовка: под ним должен стоять **ответ инструмента**, а не
        # пустая строка. Год — примета, которая точно есть в его фразе.
        assert '20' in prompt.split(HEAD_TIME, 1)[1][:200], \
            f'заголовок времени есть, а самого времени под ним нет.{got}'


class TestTheLanguageIsDemanded:
    """⚠⚠ Язык — не вкусовщина, а доставка.

    Фильтр сайта отклоняет сообщения не на том языке («Message not delivered.
    Unacceptable words»), и русская реплика до собеседника не дойдёт вовсе.
    Первый прогон прежней версии дал **все** реплики по-русски: правило было
    «пиши на языке его профиля», профиля нет, и модель ушла в язык промпта.

    ⚠ Проверяем, что код **потребовал** язык, а не что модель послушалась:
    послушание — её свойство, и тест на него плавал бы. Замечено на живом
    прогоне: `en` в промпте стоял, а реплика вышла русской.
    """

    async def test_the_language_reaches_the_draft(self, invite):
        got = await invite(user_language='en')
        prompt = got.prompt_of(STEP_DRAFT)

        head = 'Требуемый язык ответа (код) ==='

        assert head in prompt, f'заголовка языка в промпте нет.{got}'
        assert prompt.split(head, 1)[1].strip().startswith('en'), \
            f'под заголовком языка стоит не тот код.{got}'

    async def test_the_language_reaches_the_judge(self, invite):
        """⚠ Судье он нужен ровно затем, чтобы завернуть чужой язык: это третий
        пункт его списка отказов."""
        got = await invite(user_language='en')

        assert 'Язык (код): en' in got.prompt_of(STEP_JUDGE), \
            f'судья не знает, какого языка ждать.{got}'


class TestTheAvoidList:
    """Что уже писали — показывается обоим: и сочинителю, и судье."""

    async def test_the_list_reaches_both(self, invite):
        got = await invite(invite_avoid=AVOID)

        assert AVOID in got.prompt_of(STEP_DRAFT), \
            f'список прошлых реплик не доехал до сочинителя.{got}'
        assert AVOID in got.prompt_of(STEP_JUDGE), \
            f'список прошлых реплик не доехал до судьи.{got}'

    async def test_an_empty_list_hides_the_block(self, invite):
        got = await invite(invite_avoid='')

        assert HEAD_AVOID not in got.prompt_of(STEP_DRAFT), \
            f'списка не передавали, а заголовок в промпте есть.{got}'
