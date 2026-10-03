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

from tests_llm.conftest import talk_forget
from tests_llm.datingai import TALK_MAIL_ASK, TALK_MAIL_WRITE
from tests_llm.mark import mark_key
from tests_llm.dating_talk.conftest import (FACTS_MAN,
                                            FACTS_TALK,
                                            MARKS, STEP_ANALYSE, STEP_ANSWER,
                                            STEP_BRANCH, STEP_BRANCHES,
                                            STEP_CHAT, STEP_DICE,
                                            STEP_FACT_INVENT,
                                            STEP_FACT_INVENT_ADD,
                                            STEP_FACT_SAVE, STEP_FACT_SAVE_MAN,
                                            STEP_FACT_SAVE_TALK, STEP_INITIATIVE,
                                            STEP_JUDGE, STEP_MAIL_WRITE,
                                            STEP_REPEAT, STEP_SILENCE,
                                            STEP_FACTS_MAN,
                                            STEP_FACTS_PLAIN,
                                            STEP_FACTS_TAGS,
                                            STEP_TOPIC, facts_girl_for,
                                            photo_answer, talk_plan)

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
                          default=photo_answer())

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
    """⚠⚠ Всё, что промпту полагается знать о паре, доезжает до него.

    Разрыв этого договора тихий с обеих сторон: сосед снял объявление — панель
    получает `400` и молчит в чужом журнале; панель перестала слать — промпт
    собирается с пустой меткой, и модель отвечает складно, просто не зная того,
    что ей полагалось знать.

    ⚠ Проверка одна на всех (`marks_missing`): ветки письма и инициативы читают
    те же переменные, и своя проверка в каждом тесте разошлась бы с соседями.

    ## ⚠⚠ Источников два, и это видно по способу подготовки

    Анкету собеседника и его имя **присылает панель** — они уходят в
    `variables`. А ленты разговора панель больше не шлёт: их собирает сам
    workflow из `companion_session`, и посеять их можно только настоящим
    обменом (`said` / `mailed`).

    То есть эти тесты сторожат обе дороги разом: пришедшее снаружи и добытое
    самим прогоном. Метка, посеянная репликой, обязана вернуться лентой — если
    не вернулась, разорвано звено между записью и чтением.
    """

    async def test_the_chat_branch_gets_them(self, talk, llm_answers):
        """Ветка чата: анкета собеседника, обе истории, имя собеседника."""
        await llm_answers(talk_plan())

        got = await talk('Hi!', said=MARKS['talk_history_chat'],
                         mailed=MARKS['talk_history_mail'],
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

        got = await talk(TALK_MAIL_ASK, said=MARKS['talk_history_chat'],
                         mailed=MARKS['talk_history_mail'],
                         variables=MARKS.vars(mail_mode='1',
                                              mail_kind=TALK_MAIL_WRITE,
                                              answer_anyway='1'))
        # ⚠ Длины здесь нет: её бросает «Жребий» внутри workflow, и своего
        # значения у теста не бывает. Что метка раскрылась — `test_branches.py`.
        missing = MARKS.missing(got, STEP_MAIL_WRITE, (
            'companion_bio', 'talk_history_chat', 'talk_history_mail'))

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
        на круг перегенерации из-за расхождения двух промптов.

        ⚠ Длину бросает «Жребий» внутри workflow (`dice_mail_length`), поэтому
        своего значения у теста нет: проверяем, что метка **раскрылась**.
        """
        await llm_answers(talk_plan())

        got = await talk(TALK_MAIL_ASK,
                         variables=MARKS.vars(mail_mode='1',
                                              mail_kind=TALK_MAIL_WRITE,
                                              answer_anyway='1'))

        assert '%dice_mail_length%' not in got.prompt_of(STEP_JUDGE), \
            f'судья не знает, какой длины просили письмо.{got}'


class TestTheInitiativeHasItsOwnBranch:
    """⚠⚠ «Собеседник молчит — пишем первыми» идёт **своей** веткой.

    Ветка нужна не для порядка: у неё своё задание («заговори», а не «ответь») и
    свой жребий приёма. Уйди заход веткой чата — он получил бы «ответь на
    сказанное», а сказанного нет.

    ⚠ Прежде это проверял только живой прогон (`test_branches.py`), то есть не
    проверял никто: живые тесты не идут вместе с сюитой.
    """

    async def test_it_goes_to_the_initiative_branch(self, talk, llm_answers):
        await llm_answers(talk_plan())

        got = await talk('', variables={'make_initiative': '1',
                                        'answer_anyway': '1'})

        assert got.ran(STEP_INITIATIVE), f'ветка инициативы не отработала.{got}'
        assert not got.ran(STEP_CHAT), \
            f'инициатива ушла веткой чата — там задание «ответь».{got}'

    async def test_it_returns_through_the_common_judge(self, talk, llm_answers):
        """⚠ Инициатива обязана пройти судью, как и прочие ветки: текст уходит
        живому человеку, и своего пути в обход проверки у неё быть не должно."""
        await llm_answers(talk_plan())

        got = await talk('', variables={'make_initiative': '1',
                                        'answer_anyway': '1'})

        assert got.ran(STEP_JUDGE), \
            f'инициатива миновала судью.{got}'
        assert got.went_through(STEP_ANSWER), \
            f'инициатива не дошла до общего выхода.{got}'


class TestTheAnalysisCanStopTheRun:
    """⚠⚠ Разбор вправе решить «отвечать не нужно» — и это должно работать.

    Развилка `prompt_user_ignore` уводит на «Тишину» **мимо всех веток**: ни
    сочинения, ни судьи, ни платного вызова модели. На неё приходятся реплики
    вроде «ок» и наборы букв.

    ⚠ Довод `ignore` был в `talk_plan` с самого начала, но **ни один тест его не
    задавал** — путь не проверялся ничем, и трасса это подтвердила: переход
    #27 → «Тишина» не сработал ни разу за прогон.
    """

    async def test_an_ignored_message_goes_silent(self, talk, llm_answers):
        await llm_answers(talk_plan(ignore='1'))

        got = await talk('ок')

        assert got.ran(STEP_SILENCE), \
            f'разбор велел молчать, а поток пошёл дальше.{got}'

    async def test_it_costs_no_composing(self, talk, llm_answers):
        """⚠⚠ Смысл развилки — **не платить** за ответ, которого не будет.

        Пройди поток дальше, он позвал бы модель ещё дважды (ветка и судья), и
        каждая реплика «ок» стоила бы как полноценный ответ.
        """
        await llm_answers(talk_plan(ignore='1'))

        got = await talk('ок')

        for step in STEP_BRANCHES:
            assert not got.ran(step), \
                f'после «отвечать не нужно» отработала ветка {step}.{got}'
        assert not got.ran(STEP_JUDGE), \
            f'после «отвечать не нужно» звали судью.{got}'


class TestWhatHeSaidIsKept:
    """⚠⚠ Факты из реплики **вправду записываются**, а не «шаг был на маршруте».

    Подпрогон `companion_fact_extract` обходит запись, когда фактов нет
    (`prompt_user_facts_companion == 0`). В обычном заходе так и есть — значит
    сама запись не выполнялась **ни разу**: 16 обходов из 16 по трассе.

    То есть дорога, ради которой заведена вся память агента, была не проверена.

    ⚠ Факты кладутся врозь: о человеке и о переписке пары. «Он инженер» верно для
    любой нашей анкеты, «договорились созвониться» — только для этой пары.
    """

    async def test_the_subflow_runs(self, talk, llm_answers):
        await llm_answers(talk_plan(facts_man=FACTS_MAN, facts_talk=FACTS_TALK))

        got = await talk('I am an architect living in Porto.')

        assert got.went_through(STEP_FACT_SAVE), \
            f'подпрогон сохранения фактов не позван.{got}'

    async def test_both_stores_are_written(self, talk, llm_answers):
        await llm_answers(talk_plan(facts_man=FACTS_MAN, facts_talk=FACTS_TALK))

        got = await talk('I am an architect living in Porto.')

        assert got.ran(STEP_FACT_SAVE_MAN), \
            f'факты о собеседнике не записались.{got}'
        assert got.ran(STEP_FACT_SAVE_TALK), \
            f'факты о переписке не записались.{got}'

    async def test_no_facts_means_no_writing(self, talk, llm_answers):
        """⚠ Обратная сторона: фактов нет — запись обязана быть обойдена.

        Иначе подпрогон писал бы в Qdrant пустоту на каждой реплике «ок».
        """
        await llm_answers(talk_plan())

        got = await talk('ок')

        assert got.went_through(STEP_FACT_SAVE), \
            f'подпрогон не позван вовсе — проверять нечего.{got}'
        assert not got.ran(STEP_FACT_SAVE_MAN), \
            f'фактов не было, а запись всё равно шла.{got}'


class TestHerOwnFactsAreInvented:
    """⚠⚠ Спросил о ней — значит ей есть что ответить, и это запоминается.

    Собеседник спрашивает «а ты чем занимаешься?», фактов о девушке нет, и агент
    выдумал бы новое при каждом вопросе — завтра сказав другое. Подпрогон
    `girl_fact_invent` придумывает **один раз** и кладёт в память.

    ⚠ Вход в него — развилка `prompt_user_question == 1` у поиска фактов. По
    трассе она не срабатывала ни разу: подпрогон не запускался вовсе.
    """

    async def test_a_question_runs_the_subflow(self, talk, llm_answers):
        await llm_answers(talk_plan(question='1', facts_girl=facts_girl_for('test_key')))

        got = await talk('And what do you do for a living?')

        assert got.went_through(STEP_FACT_INVENT), \
            f'подпрогон выдумывания фактов не позван.{got}'

    async def test_the_invented_facts_are_stored(self, talk, llm_answers):
        """⚠ Придумать мало — надо записать: иначе на тот же вопрос завтра
        придумается другое, и девушка начнёт себе противоречить."""
        await llm_answers(talk_plan(question='1', facts_girl=facts_girl_for('test_key')))

        got = await talk('And what do you do for a living?')

        assert got.ran(STEP_FACT_INVENT_ADD), \
            f'придуманные факты никуда не записались.{got}'

    async def test_nothing_invented_writes_nothing(self, talk, llm_answers):
        """⚠⚠ Подпрогон позвали, а придумать он ничего не смог — записи быть не
        должно.

        Вопрос бывает такой, что выдумывать нечего («а сколько времени?»), и
        подпрогон честно отвечает нулём. Уйди этот ноль в запись — в память
        девушки лёг бы факт-пустышка, и поиск стал бы возвращать его вместо
        настоящих.
        """
        await llm_answers(talk_plan(question='1', facts_girl='0'))

        got = await talk('And what time is it there?')

        assert got.went_through(STEP_FACT_INVENT), \
            f'подпрогон не позван вовсе — проверять нечего.{got}'
        assert not got.ran(STEP_FACT_INVENT_ADD), \
            f'придумывать было нечего, а запись всё равно шла.{got}'

    async def test_no_question_means_no_inventing(self, talk, llm_answers):
        """⚠⚠ Обратная сторона, и она про деньги: подпрогон это лишний вызов
        модели. Запускайся он на каждой реплике — платили бы за него всегда."""
        await llm_answers(talk_plan())

        got = await talk('ок')

        assert not got.went_through(STEP_FACT_INVENT), \
            f'о девушке не спрашивали, а факты ей всё равно придумывали.{got}'


class TestHerFactsAreFoundByTags:
    """⚠⚠ Записанное **находится** — и находится поиском по тегам.

    Это последнее звено памяти, и проверить его можно только двумя заходами:
    первый придумывает и записывает, второй ищет. Одним заходом не выйдет — в
    момент поиска записывать ещё нечего.

    ## ⚠⚠ Этот тест — сторож найденной поломки

    Промпт подпрогона велел помечать факты `%girl_name%`, а внутри подпрогона это
    **имя агента** (`dating_girl_universal`): все придуманные факты всех девушек
    ложились в один документ и не читались ничем. На проде их два — вся работа
    занятия за всё время (`…_wf_invent_facts_key`).

    Поломка была совершенно тихой: запись шла, шаг зеленел, поиск честно
    возвращал пусто. Ни один прежний тест её не видел, потому что все они
    проверяли **один** заход.

    ⚠ Ключ девушки тест задаёт сам — обе части. Иначе он не знает, чем помечать
    факт: склейку делает шаг «Ключи» внутри прогона.
    """

    @pytest.fixture
    async def girl(self):
        """Своя девушка и её склеенный ключ: номер, имя, ключ.

        ⚠ Номер уникален на прогон: два теста с общей девушкой делили бы память,
        и второй находил бы факты первого.

        ## ⚠⚠ Номер несёт приставку `pytest_`, и это не украшение

        Прежде здесь стояло `f'9{uuid…}'` — похоже на номер анкеты и **без метки**.
        Такую запись не находит ни уборка после теста, ни `test_cleanup.py`: оба
        ищут по приставке. За каждый прогон оставалось по три собеседника и шесть
        разговоров, а в Qdrant — по документу фактов на тест.

        ⚠ Строка вместо числа безопасна: ключ собирается склейкой
        (`%girl_id%_%girl_name%`), в число его никто не переводит.
        """
        number = mark_key('girl')
        name = 'Zinaida-Test'
        key = f'{number}_{name}'

        yield number, name, key

        # ⚠ Уборка за собой: `talk` чистит **свою** девушку, а этот тест приносит
        # свою — и она осталась бы, сколько ни чисти чужую.
        await talk_forget(number)

    async def test_what_was_invented_is_found_next_time(self, talk, llm_answers,
                                                        girl):
        number, name, key = girl
        who = {'girl_id': number, 'girl_name': name}

        # Первый заход: собеседник спросил о ней, подпрогон придумал и записал.
        await llm_answers(talk_plan(question='1',
                                    facts_girl=facts_girl_for(key)))
        first = await talk('And what do you do for a living?', variables=who)

        assert first.ran(STEP_FACT_INVENT_ADD), \
            f'первый заход ничего не записал — искать будет нечего.{first}'

        # Второй: тот же вопрос, но придумывать больше не нужно — факт уже есть.
        await llm_answers(talk_plan(question='1',
                                    facts_girl=facts_girl_for(key)))
        second = await talk('And what do you do for a living?', variables=who)

        found = second.output_of(STEP_FACTS_TAGS)

        assert found, f'поиск по тегам ничего не вернул.{second}'
        assert 'lighthouse' in found, \
            (f'записанный факт не нашёлся поиском по тегам: {found[:120]!r}.'
             f' Ключ записи и ключ поиска разошлись.{second}')

    async def test_found_facts_reach_the_companion_search(self, talk, llm_answers,
                                                          girl):
        """⚠⚠ Нашлись факты, а вопроса не было — поток идёт к фактам собеседника.

        У шага поиска по тегам **три** выхода, и разводят их два условия:

            ничего не нашлось          → общий поиск фактов девушки
            нашлось и он спросил о ней → подпрогон выдумывания
            нашлось, вопроса не было   → поиск фактов собеседника

        Третий — обычный ход разговора: о девушке уже всё записано, спрашивают о
        нём. Проверить его можно только так: сперва записать факты, потом
        заговорить **без** вопроса о ней.
        """
        number, name, key = girl
        who = {'girl_id': number, 'girl_name': name}

        await llm_answers(talk_plan(question='1',
                                    facts_girl=facts_girl_for(key)))
        await talk('And what do you do for a living?', variables=who)

        # ⚠ Вопроса о ней нет — значит выдумывать нечего, и поток идёт дальше.
        await llm_answers(talk_plan())
        got = await talk('Nice weather today, right?', variables=who)

        assert got.ran(STEP_FACTS_TAGS), f'поиск по тегам не отработал.{got}'
        assert got.ran(STEP_FACTS_MAN), \
            (f'факты нашлись и вопроса не было, а к фактам собеседника поток'
             f' не пошёл.{got}')
        assert not got.went_through(STEP_FACT_INVENT), \
            f'о девушке не спрашивали, а выдумывание всё равно звали.{got}'

    async def test_found_facts_skip_the_plain_search(self, talk, llm_answers,
                                                     girl):
        """⚠ Нашлось по тегам — значит общий поиск не нужен.

        Оба поиска подряд стоили бы лишнего обращения к Qdrant на каждой реплике,
        а теги для этого и заведены: они сужают выборку до «о чём сейчас речь».
        """
        number, name, key = girl
        who = {'girl_id': number, 'girl_name': name}

        await llm_answers(talk_plan(question='1',
                                    facts_girl=facts_girl_for(key)))
        await talk('And what do you do for a living?', variables=who)

        await llm_answers(talk_plan(question='1',
                                    facts_girl=facts_girl_for(key)))
        got = await talk('And what do you do for a living?', variables=who)

        assert got.ran(STEP_FACTS_TAGS), f'поиск по тегам не отработал.{got}'
        assert not got.ran(STEP_FACTS_PLAIN), \
            f'теги нашли факты, а общий поиск всё равно шёл.{got}'
