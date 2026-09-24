"""Маршрут `dating_talk` при заданных ответах модели.

## ⚠⚠ Чем эти тесты отличаются от соседних

Соседи (`test_branches.py` и прочие) зовут **живую** модель и потому проверяют
устройство в живых условиях — дорого, медленно и с оговоркой «модель сегодня
решила иначе». Здесь ответы задаёт сам тест, и проверяется ровно то, что зависит
от нас: куда движок повёл поток, получив **вот такой** ответ.

Так ловятся вещи, которые живой прогон поймать не может в принципе: у него нет
способа заставить модель ответить «отвечать не нужно» именно на этом шаге.

## ⚠ Подменяются только шаги, которые зовут модель

Инструменты, подстановка переменных, переходы и подпрогоны работают
по-настоящему. Они и есть предмет проверки; подмена закрывает ровно ту часть,
что непредсказуема.

## ⚠⚠ Примета правила — кусок промпта, а не имя шага

Имени шага в запросе к модели нет вовсе — движок его не шлёт. Зато промпт у
каждого шага свой, и куска из него довольно, чтобы шаг назвать. Правило,
переставшее совпадать, видно сразу: тест падает, а `llm_calls` показывает
настоящие промпты.
"""
import pytest

from tests_llm.datingai import TALK_MAIL_ASK, TALK_MAIL_WRITE
from tests_llm.dating_talk.conftest import (MARKS, STEP_ANALYSE, STEP_BRANCH,
                                            STEP_CHAT, STEP_DICE, STEP_JUDGE,
                                            STEP_MAIL_WRITE, STEP_REPEAT,
                                            STEP_SILENCE, STEP_TOPIC,
                                            talk_plan)

pytestmark = pytest.mark.llm

class TestTheChainRunsOnFixtures:
    """⚠⚠ Цепочка проходит целиком на заданных ответах.

    Это основа: не пройди она, остальные проверки нечем было бы ставить.
    """

    async def test_it_reaches_the_answer(self, talk, llm_answers, llm_calls):
        await llm_answers(talk_plan())

        got = await talk('Hi! How was your day?')

        assert got.status == 'success', (
            f'прогон не дошёл до конца.{got}\n'
            f'вызовов модели: {len(await llm_calls())}')
        assert got.ran(STEP_DICE), f'жребий не отработал.{got}'
        assert got.ran(STEP_ANALYSE), f'разбор не отработал.{got}'
        assert got.ran(STEP_CHAT), f'ветка чата не отработала.{got}'

    async def test_the_answer_is_the_one_we_gave(self, talk, llm_answers):
        """⚠ Единственное место, где текст ответа утверждать **можно**: его
        задал тест. У живых тестов это запрещено — там слова выбирает модель."""
        await llm_answers(talk_plan(answer='fixture reply'))

        got = await talk('Hi!')

        assert got.output_of(STEP_CHAT), f'ветка чата ничего не вернула.{got}'
        assert 'fixture reply' in got.output_of(STEP_CHAT), \
            f'до шага доехал не наш ответ: {got.output_of(STEP_CHAT)!r}.{got}'


class TestTheJudgeDecidesTheEnding:
    """⚠⚠ Решение судьи разводит концовки, и проверить это живой моделью нельзя.

    Заставить её ответить «промолчи» именно здесь невозможно — она решает сама.
    С заданным ответом обе дороги проверяются за секунды.
    """

    async def test_a_verdict_to_answer_goes_to_the_answer(self, talk, llm_answers):
        await llm_answers(talk_plan(skip='0'))

        got = await talk('Hi!')

        assert got.ran(STEP_REPEAT), f'проверка повтора не отработала.{got}'
        assert not got.ran(STEP_SILENCE), \
            f'ушли в «Тишину», хотя судья велел отвечать.{got}'

    async def test_a_verdict_to_stay_silent_goes_to_silence(self, talk, llm_answers):
        """⚠ `girl_response_skip = 1` — единственная дорога к «Тишине» из
        «Валидации»; оборвись переход, ответ ушёл бы человеку вопреки судье."""
        await llm_answers(talk_plan(skip='1'))

        got = await talk('ок')

        assert got.ran(STEP_JUDGE), f'судья не отработал.{got}'
        assert got.ran(STEP_SILENCE), \
            f'судья велел молчать, а поток пошёл мимо «Тишины».{got}'


class TestTheTopicSendsToTheBranch:
    """⚠ Тема разговора уводит в ветку «письма и фото» — и это тоже решение
    модели, которое живым прогоном по заказу не воспроизвести."""

    async def test_a_photo_topic_takes_the_branch(self, talk, llm_answers):
        await llm_answers(talk_plan(topic='photo_mail'),
                          # ⚠ Умолчание нужно ветке письма-фото: у её подпрогона
                          # свои шаги, и заготовка обычного захода их не знает.
                          default={'girl_response': 'fake',
                                   'girl_response_skip': '0',
                                   'girl_response_fixed': '', 'photo_deal': 'mail',
                                   'photo_response': 'fake', 'photo_fixed': ''})

        got = await talk('Can you send me your photos?')

        assert got.ran(STEP_TOPIC), f'шаг темы не отработал.{got}'
        assert got.ran(STEP_BRANCH), \
            f'тема photo_mail не увела в ветку письма-фото.{got}'

    async def test_a_usual_topic_stays_in_chat(self, talk, llm_answers):
        await llm_answers(talk_plan())

        got = await talk('Tell me about your weekend')

        assert got.ran(STEP_CHAT), f'ветка чата не отработала.{got}'
        assert not got.ran(STEP_BRANCH), \
            f'обычная тема ушла в ветку письма-фото.{got}'


class TestWhatThePanelAlwaysSendsArrives:
    """⚠⚠ Переменные, которые DatingAi кладёт в **каждый** вызов, доезжают до промпта.

    Разрыв этого договора тихий с обеих сторон: сосед снял объявление — панель
    получает `400` и молчит в чужом журнале; панель перестала слать — промпт
    собирается с пустой меткой, и модель отвечает складно, просто не зная того,
    что ей полагалось знать.

    ⚠ Проверка одна на всех (`marks_missing`): ветки письма и инициативы читают
    те же переменные, и своя проверка в каждом тесте разошлась бы с соседями.
    """

    async def test_the_chat_branch_gets_them(self, talk, llm_answers):
        """Ветка чата: анкета собеседника, обе истории, имя собеседника."""
        await llm_answers(talk_plan())

        got = await talk('Hi!', history=MARKS['talk_history_chat'],
                         mail_history=MARKS['talk_history_mail'],
                         variables=MARKS.vars())
        missing = MARKS.missing(got, STEP_CHAT, (
            'companion_bio', 'talk_history_chat', 'talk_history_mail',
            'companion_title'))

        assert not missing, f'до промпта ветки чата не доехало: {missing}.{got}'

    async def test_the_letter_branch_gets_them_too(self, talk, llm_answers):
        """⚠ Ветка письма читает те же переменные **и** свою длину.

        Длину бросает панель жребием: потеряйся она — все письма выйдут одной
        длины, и по одному письму этого не видно.
        """
        await llm_answers(talk_plan())

        got = await talk(TALK_MAIL_ASK, history=MARKS['talk_history_chat'],
                         mail_history=MARKS['talk_history_mail'],
                         variables=MARKS.vars(mail_mode='1',
                                              mail_kind=TALK_MAIL_WRITE,
                                              answer_anyway='1'))
        missing = MARKS.missing(got, STEP_MAIL_WRITE, (
            'companion_bio', 'talk_history_chat', 'talk_history_mail',
            'mail_length'))

        assert not missing, f'до промпта ветки письма не доехало: {missing}.{got}'

    async def test_the_girl_profile_is_the_fallback_for_facts(self, talk,
                                                             llm_answers):
        """⚠⚠ Анкета девушки — запасной путь, когда фактов о ней ещё нет.

        Ровно то же устройство, что у собеседника: нашлись факты — блок фактов,
        не нашлись — анкета.

        ⚠ Этого не было, и нашёл это соседний тест. `girl_bio` и `girl_name` шли
        в каждом вызове (4444 прогона на проде), обе объявлены входящими — и
        промпты не читали ни ту, ни другую: вместо имени стояло `%agent_name%`,
        то есть имя **агента**:

            === Информация о fav_mail_ladadate в базе данных ===

        Под заголовком лежали факты о девушке, названные системным именем.
        Починено миграцией `…_wf_talk_girl_bio`; этот тест стережёт починку.

        ⚠ Проверяем **вход шага**, а не ответ: по ответу о входе судить нельзя.
        Живой пример — на «Занятие: lighthouse keeper» модель ответила «i bet
        you're good with lights»: данные дошли, а слова в ответе нет.
        """
        await llm_answers(talk_plan())

        got = await talk('Hi!', variables=MARKS.vars())
        prompt = got.prompt_of(STEP_CHAT)

        assert MARKS['girl_bio'] in prompt, \
            f'анкета девушки не доехала до промпта.{got}'
        assert 'Твоя анкета на сайте знакомств' in prompt, \
            f'анкета попала в промпт без своего заголовка.{got}'
        # ⚠ Имя агента в промпте — признак возврата прежней подстановки.
        assert 'dating_girl_universal' not in prompt, \
            f'в промпте имя агента вместо имени девушки.{got}'


class TestTheDiceSectionsOpenAndClose:
    """⚠⚠ Выпавший жребий открывает свою секцию промпта, невыпавший — прячет.

    ⚠ Проверки перенесены из `tests_llm/dating_favorite_mail_write/`: письма
    избранным переехали в ветки `dating_talk`, а их workflow осиротел. Поведение
    при этом живо, и без переноса покрытие ушло бы вместе с папкой.

    Пустой заголовок хуже отсутствия блока: «Расскажи о себе. Тема:» и пустота
    модель читает как задание без темы и придумывает её сама — то есть каждый
    раз одну и ту же. Оттого секция и стоит под `%if%`.
    """

    async def test_a_story_opens_its_section(self, talk, llm_answers):
        await llm_answers(talk_plan())

        got = await talk(TALK_MAIL_ASK,
                         variables=MARKS.vars(mail_mode='1',
                                              mail_kind=TALK_MAIL_WRITE,
                                              answer_anyway='1',
                                              dice_mail_story_percent='100'))

        assert 'Расскажи о себе' in got.prompt_of(STEP_MAIL_WRITE), \
            f'жребий выпал, а секции рассказа в промпте нет.{got}'

    async def test_no_story_hides_the_section(self, talk, llm_answers):
        """⚠ Доля `0` — «никогда»: секции быть не должно вовсе."""
        await llm_answers(talk_plan())

        got = await talk(TALK_MAIL_ASK,
                         variables=MARKS.vars(mail_mode='1',
                                              mail_kind=TALK_MAIL_WRITE,
                                              answer_anyway='1',
                                              dice_mail_story_percent='0'))

        assert 'Расскажи о себе' not in got.prompt_of(STEP_MAIL_WRITE), \
            f'жребий не выпал, а секция рассказа осталась.{got}'

    async def test_the_judge_knows_the_asked_length(self, talk, llm_answers):
        """⚠⚠ Судья обязан знать **заказанную** длину, а не судить на глаз.

        Иначе он бракует письмо за то, чего у него не просили, — и заход уходит
        на круг правок из-за расхождения двух промптов.
        """
        await llm_answers(talk_plan())

        got = await talk(TALK_MAIL_ASK,
                         variables=MARKS.vars(mail_mode='1',
                                              mail_kind=TALK_MAIL_WRITE,
                                              answer_anyway='1'))

        assert not MARKS.missing(got, STEP_JUDGE, ('mail_length',)), \
            f'судья не знает, какой длины просили письмо.{got}'
