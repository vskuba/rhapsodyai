"""Что доезжает до промпта черновика: реестр переменных, зачин, рассказ, язык.

## ⚠⚠ Что здесь предмет проверки

Шаблон общий на сорок анкет, и всё, чем он отличается от вчерашнего, приходит
**снаружи**: приём, длина, зачин, рассказ о себе — жребий панели
(`mail_agent.mail_write`). Модель не выбирает, насколько ей быть разной; ей
говорят, чем быть на этот раз.

Значит договор: панель кладёт переменную — промпт её показывает либо прячет
целиком. Ни один тест не утверждает, **послушалась ли** модель.

## ⚠ Почему список меток проверяется отдельно и придирчиво

Имена уезжают агенту **четырьмя** переменными сразу (`mail_vars`,
`mail_var_names`, `mail_var_must`, `mail_var_live`), и собираются они из одного
списка. Разойдись они между собой — шаблон просили бы с именем, а проверяли без
него; ровно так однажды перестала работать доля `mailing_name_percent`.
"""

import pytest

from tests_llm.dating_mail_write.conftest import (HEAD_AVOID, HEAD_GREETING,
                                                  HEAD_STORY, NO_GREETING,
                                                  STEP_SAME, STEP_WRITE,
                                                  VARS_TEXT)

pytestmark = pytest.mark.llm

ANGLE = 'разговор о мелочи, которую замечают только внимательные'
LENGTH = 'три коротких абзаца'
GREETING = 'начни с обращения по имени и сразу с мысли'
STORY = 'как варила кофе и смотрела в окно на чужую собаку'
AVOID = 'так уже было: «I was scrolling through profiles and yours caught my eye»'
HINT = 'письмо для тех, кто любит дорогу'


class TestTheRegistryReachesThePrompt:
    """⚠⚠ Реестр переменных — единственное, чем шаблон знает про подстановку."""

    async def test_the_variables_are_listed_with_their_labels(self, letter):
        """⚠ Подписи модель читает, и по ним она решает, куда метку поставить.

        Голые имена для этого не годятся: `question_to_companion` без пояснения
        «живой вопрос получателю» встанет в середину абзаца.
        """
        got = await letter()

        assert VARS_TEXT in got.prompt_of(STEP_WRITE), \
            f'реестр переменных не доехал до промпта.{got}'

    async def test_the_live_variable_rule_is_stated(self, letter):
        """⚠⚠ Правило про отдельный абзац стоит в промпте **всегда**.

        Без него живая метка встаёт внутрь фразы и даёт «What are What do you
        enjoy??» — вопрос вместо вопроса. Ворота `Вопрос отдельно?` это ловят, но
        ловить дешевле, чем переписывать: каждый заход — вызов модели.
        """
        got = await letter()

        assert 'question_to_companion' in got.prompt_of(STEP_WRITE), \
            f'правило про отдельный абзац пропало из промпта.{got}'

    async def test_the_hint_is_shown(self, letter):
        got = await letter(mail_hint=HINT)

        assert HINT in got.prompt_of(STEP_WRITE), \
            f'пожелание человека не доехало до промпта.{got}'


class TestTheDiceReachThePrompt:
    """Приём и длина — жребий панели."""

    async def test_the_angle_is_shown(self, letter):
        got = await letter(mail_angle=ANGLE)

        assert ANGLE in got.prompt_of(STEP_WRITE), \
            f'приём не доехал до промпта — модель выберет свой.{got}'

    async def test_the_length_is_shown(self, letter):
        got = await letter(mail_length=LENGTH)

        assert LENGTH in got.prompt_of(STEP_WRITE), \
            f'длина не доехала до промпта.{got}'


class TestTheGreetingIsADice:
    """⚠⚠ Зачин — доля, и заведена она по живому пулу.

    Восемь шаблонов подряд начинались словом «Hi» с новой строки: зачин модель не
    выбирает — берёт первый попавшийся и повторяет. «Без приветствия» при этом
    **отдельная доля**, а не седьмой пункт списка: это не приём, а его
    отсутствие.
    """

    async def test_a_greeting_opens_its_section(self, letter):
        got = await letter(mail_greeting=GREETING)
        prompt = got.prompt_of(STEP_WRITE)

        assert HEAD_GREETING in prompt, f'заголовка зачина нет.{got}'
        assert GREETING in prompt, f'сам зачин не подставился.{got}'

    async def test_no_greeting_forbids_it_outright(self, letter):
        """⚠ Пустая ветка не просто прячет секцию — она **запрещает** приветствие
        прямо, перечисляя слова. Молчание модель прочла бы как «на твой выбор»,
        и выбрала бы «Hi»."""
        got = await letter(mail_greeting='')
        prompt = got.prompt_of(STEP_WRITE)

        assert HEAD_GREETING not in prompt, \
            f'зачина не просили, а заголовок в промпте есть.{got}'
        assert NO_GREETING in prompt, \
            f'без зачина не встал прямой запрет приветствия.{got}'


class TestTheStoryIsADice:
    """Рассказ о себе — доля, и у неё две стороны."""

    async def test_a_story_opens_its_section(self, letter):
        got = await letter(mail_story=STORY)
        prompt = got.prompt_of(STEP_WRITE)

        assert HEAD_STORY in prompt, f'заголовка рассказа нет.{got}'
        assert STORY in prompt, f'тема рассказа не подставилась.{got}'

    async def test_the_story_must_fit_any_girl(self, letter):
        """⚠⚠ Рассказом пишут **все сорок анкет**, и правило об этом стоит рядом
        с темой.

        «После репетиции» и «у нас в Киеве» — брак: годится одной девушке из
        сорока. Без правила модель пишет живо и конкретно, то есть ровно не то.
        """
        got = await letter(mail_story=STORY)

        assert 'подходить ЛЮБОЙ девушке' in got.prompt_of(STEP_WRITE), \
            f'правило «рассказ годится каждой» пропало из промпта.{got}'

    async def test_no_story_hides_the_section(self, letter):
        got = await letter(mail_story='')

        assert HEAD_STORY not in got.prompt_of(STEP_WRITE), \
            f'рассказа не просили, а заголовок в промпте есть.{got}'


class TestTheAvoidList:
    """Что уже писали — показывается и сочинителю, и судье повтора."""

    async def test_the_list_reaches_both(self, letter):
        got = await letter(mail_avoid=AVOID)

        assert AVOID in got.prompt_of(STEP_WRITE), \
            f'список прошлых писем не доехал до сочинителя.{got}'
        assert AVOID in got.prompt_of(STEP_SAME), \
            f'список прошлых писем не доехал до судьи повтора.{got}'

    async def test_an_empty_list_hides_the_block(self, letter):
        got = await letter(mail_avoid='')

        assert HEAD_AVOID not in got.prompt_of(STEP_WRITE), \
            f'списка не передавали, а заголовок в промпте есть.{got}'

    async def test_the_judge_is_told_to_pass_when_there_is_nothing_to_compare(
            self, letter):
        """⚠ Без списка судья обязан отвечать «не повтор».

        Иначе он придирается к первому же письму сайта, сравнивая его не с чем, —
        и цикл крутится три захода впустую.
        """
        got = await letter(mail_avoid='')

        assert 'отвечай no' in got.prompt_of(STEP_SAME), \
            f'судье не сказано, что сравнивать не с чем.{got}'


class TestTheLanguageIsDemanded:
    """⚠ Язык — доставка: фильтр сайта отклоняет письма не на том языке.

    Проверяем, что код **потребовал** язык, а не что модель послушалась.
    """

    async def test_the_language_reaches_the_draft(self, letter):
        got = await letter(user_language='en')

        assert 'язык письма И НАЗВАНИЯ: en' in got.prompt_of(STEP_WRITE), \
            f'требование языка не доехало до промпта.{got}'


class TestTheParticipantsAreHidden:
    """⚠⚠ Ни анкеты девушки, ни карточки адресата в промпте быть не должно.

    Это главное свойство шаблона, и куплено оно опытом: получив карточки, агент
    честно написал «Diana here! I'm a choreographer living in Kyiv». Требовать
    «имена только переменной», отдав при этом сами имена, — борьба с данными, в
    которой данные побеждают.

    ⚠ Проверяется **промпт**, а не ответ: попали данные внутрь или нет, видно на
    входе, и от удачи это не зависит.
    """

    async def test_no_card_headers_in_the_prompt(self, letter):
        got = await letter()
        prompt = got.prompt_of(STEP_WRITE)

        for leak in ('=== Кто пишет ===', '=== Что известно о получателе ==='):
            assert leak not in prompt, \
                f'в промпт шаблона попала карточка участника: {leak}.{got}'

    async def test_the_prompt_forbids_concrete_details(self, letter):
        got = await letter()

        assert 'НИКАКОЙ конкретики' in got.prompt_of(STEP_WRITE), \
            f'запрет на конкретику пропал из промпта.{got}'
