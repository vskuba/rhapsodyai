"""Четыре ветки сочинения: каждая идёт своим шагом и ни одна не течёт в соседнюю.

## ⚠⚠ Что здесь стережётся

`dating_talk` сочиняет четырьмя разными заданиями: реплика в чат, письмо первым,
ответ на письмо, инициатива после паузы. Раньше все четыре жили в одном шаге под
вложенными условными блоками — шесть килобайт, в которых видно только своё, — и это
уже однажды сломалось молча: ветка инициативы получала **два** блока «Important
information» и три JSON-примера, потому что закрывающее `[<endif>]` стояло посреди
пункта ветки чата.

Теперь у каждой свой шаг, а развилка — `transitions_before` у шага чата: он стоит
первым, и условия уводят с него **до** вызова модели. Значит «какой веткой пошло»
видно по трассе, и проверять это можно, ничего не зная о тексте ответа.

## ⚠ Проверяется только маршрут

Ответ модели не предсказуем и здесь не утверждается **никогда** — ни его слова,
ни длина, ни тон. Утверждается устройство: какой шаг отработал, какая переменная
доехала, не сработала ли соседняя ветка. Это правило всей папки
(`testing_llm.md`), и оно не исключение для новых тестов.

## ⚠⚠ Спрашиваем `ran`, а не `went_through`

Шаг, с которого поток ушёл `transitions_before`, **пишется в трассу** наравне с
выполненными. Значит `went_through('Ответ в чат')` истинно при любой ветке — он
отвечает «поток сюда добирался», а не «отсюда писали». Ветку различает `ran`.

## ⚠⚠ Почему важно «соседняя не сработала»

Ветки стоят подряд по номерам, и движок идёт по позициям: шаг, чей переход не
сработал, утекает в следующий — то есть в соседнюю ветку. От этого защищает
снятая галочка «to next step», и без проверки её снятие некому заметить: письмо,
сочинённое дважды, выглядит как обычное письмо.
"""
import pytest

from tests_llm.datingai import (TALK_MAIL_ASK, TALK_MAIL_REPLY,
                               TALK_MAIL_REPLY_ASK, TALK_MAIL_WRITE)
from tests_llm.dating_talk.conftest import (STEP_ANSWER,
                                            STEP_BRANCH,
                                            STEP_BRANCHES, STEP_CHAT,
                                            STEP_DICE, STEP_INITIATIVE,
                                            STEP_JUDGE, STEP_MAIL_REPLY,
                                            STEP_MAIL_WRITE, photo_answer,
                                            talk_plan)

pytestmark = pytest.mark.llm

# Переписка письмами для почтовых веток: без неё «ответ на письмо» проверялся бы
# в условиях, которых в жизни не бывает — отвечать было бы не на что.
MAIL_HISTORY = ('[22.09 10:15] она: Рассказывала тебе про поездку в Карпаты.\n'
                '[23.09 19:40] он: Звучит здорово. Сам давно никуда не выбирался.')


class TestEachBranchGoesItsOwnWay:
    """⚠⚠ Главное: вид работы выбирает ветку, и ровно одну."""

    async def test_a_chat_message_stays_in_chat(self, talk):
        """Ничего не просили — идём веткой чата, как шли всегда."""
        got = await talk('Hi! Tell me about your weekend')

        assert got.ran(STEP_CHAT), f'реплика пошла не веткой чата.{got}'
        assert not _others(got, STEP_CHAT), \
            f'отработала и соседняя ветка: {_others(got, STEP_CHAT)}.{got}'

    async def test_a_letter_goes_to_the_letter_branch(self, talk):
        """⚠ `mail_mode` уводит на «Письмо первым» — то, что пишут молчащему."""
        got = await talk(TALK_MAIL_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))

        assert got.ran(STEP_MAIL_WRITE), f'письмо пошло не своей веткой.{got}'
        assert not _others(got, STEP_MAIL_WRITE), \
            f'отработала и соседняя ветка: {_others(got, STEP_MAIL_WRITE)}.{got}'

    async def test_a_reply_goes_to_the_reply_branch(self, talk):
        """⚠⚠ `mail_kind = reply` сильнее `mail_mode`: правило развилки стоит
        первым, иначе оба вида письма ушли бы в «Письмо первым»."""
        got = await talk(TALK_MAIL_REPLY_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_REPLY))

        assert got.ran(STEP_MAIL_REPLY), f'ответ пошёл не своей веткой.{got}'
        assert not _others(got, STEP_MAIL_REPLY), \
            f'отработала и соседняя ветка: {_others(got, STEP_MAIL_REPLY)}.{got}'

    async def test_an_initiative_goes_to_its_branch(self, talk):
        """⚠ Инициатива — реплика в чат после паузы, а не письмо."""
        got = await talk('Собеседник молчит. Напиши ему сама.',
                         variables={'make_initiative': '1', 'answer_anyway': '1'})

        assert got.ran(STEP_INITIATIVE), f'инициатива пошла не своей веткой.{got}'
        assert not _others(got, STEP_INITIATIVE), \
            f'отработала и соседняя ветка: {_others(got, STEP_INITIATIVE)}.{got}'


class TestTheChannelIsMarkedBeforeTheAnswerIsStored:
    """⚠⚠⚠ Канал разговора: чат или письмо — и записывается он по этой метке.

    `talk_session_kind` читают шаги записи (`Разговор: записать ответ` и
    `… тишину`) доводом `kind`. Умолчание `chat` ставит шаг «Переменные» в самом
    начале; почтовые ветки перебивают его на `mail` отдельными шагами «Канал:
    …», которые стоят **после** ветки и ведут на общую «Валидацию».

    ## ⚠⚠ Почему это надо стеречь отдельно

    Поломка здесь **тихая вдвойне**. Сорвись переход на «Канал: …» — письмо
    всё равно сочинится, пройдёт судью и уедет человеку: текст будет верный.
    Разойдётся только журнал разговора: ответ на письмо ляжет каналом `chat`,
    и в ленте он окажется не там, где его ищут. Ни один маршрутный тест этого
    не заметит — ветка-то отработала.

    ⚠ Метка проверяется по трассе (`variables_changed`), а не по базе: предмет
    здесь — решение workflow, а не работа инструмента записи.
    """

    async def test_a_chat_message_is_marked_as_chat(self, talk):
        """Умолчание из шага «Переменные» доезжает нетронутым."""
        got = await talk('Hi! Tell me about your weekend')

        assert got.vars.get('talk_session_kind') == 'chat', \
            f'чат помечен каналом {got.vars.get("talk_session_kind")!r}.{got}'

    async def test_a_letter_is_marked_as_mail(self, talk):
        """⚠ Ветка «Письмо первым» уводит на «Канал: письмо первым»."""
        got = await talk(TALK_MAIL_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))

        assert got.ran(STEP_MAIL_WRITE), f'письмо пошло не своей веткой.{got}'
        assert got.vars.get('talk_session_kind') == 'mail', \
            f'письмо помечено каналом {got.vars.get("talk_session_kind")!r}.{got}'

    async def test_a_reply_is_marked_as_mail_too(self, talk):
        """⚠⚠ У ответа на письмо свой шаг канала (`#799`), и он отдельный.

        Два шага вместо одного — потому что ветки разные и `to_next_step` у них
        снят: общий шаг пришлось бы ставить после обеих, а туда они не идут.
        Значит и проверять надо обе: сорвись переход у одной, вторая промолчит.
        """
        got = await talk(TALK_MAIL_REPLY_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_REPLY))

        assert got.ran(STEP_MAIL_REPLY), f'ответ пошёл не своей веткой.{got}'
        assert got.vars.get('talk_session_kind') == 'mail', \
            f'ответ на письмо помечен каналом {got.vars.get("talk_session_kind")!r}.{got}'

    async def test_an_initiative_stays_a_chat(self, talk):
        """⚠ Инициатива — реплика в чат, и каналом остаётся `chat`.

        Проверка от обратного: шаги «Канал: …» не должны ловить всех подряд —
        инициатива идёт своей веткой и мимо них.
        """
        got = await talk('Собеседник молчит. Напиши ему сама.',
                         variables={'make_initiative': '1', 'answer_anyway': '1'})

        assert got.ran(STEP_INITIATIVE), f'инициатива пошла не своей веткой.{got}'
        assert got.vars.get('talk_session_kind') == 'chat', \
            f'инициатива помечена каналом {got.vars.get("talk_session_kind")!r}.{got}'


class TestBranchesDoNotLeak:
    """⚠⚠ Ветки стоят подряд, и провал по номеру ведёт в соседнюю.

    Защищает снятая галочка «to next step». Проверка нужна именно потому, что
    поломка тихая: письмо, сочинённое дважды, выглядит как обычное письмо.
    """

    async def test_the_letter_is_composed_once(self, talk):
        """Ветка письма отработала ровно раз, а не перетекла дальше по номеру."""
        got = await talk(TALK_MAIL_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))
        made = got.times_ran(STEP_MAIL_WRITE)

        assert made == 1, f'ветка письма отработала {made} раз(а).{got}'

    async def test_the_letter_branch_reaches_the_judge(self, talk):
        """⚠ Ветки сходятся на «Валидации» — это их общий выход.

        Оборвись он, текст ушёл бы человеку мимо судьи.
        """
        got = await talk(TALK_MAIL_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))

        assert got.ran(STEP_JUDGE), f'ветка письма не дошла до судьи.{got}'


class TestTheLengthReachesTheLetter:
    """⚠⚠ Длину письма выбирает жребий, а не модель, и доехать она обязана.

    Разнообразие рассылки держится на жребии: «будь разной» модель не понимает.
    Пока длину задавала вилка в промпте («от одного абзаца до трёх»), из
    двенадцати писем прода девять вышли ровно в три абзаца — у вилки верх
    читается как цель.

    ## ⚠⚠⚠ Бросает жребий ВНУТРИ workflow, а не панель снаружи

    Было: панель бросала и присылала `mail_length`. Стало: шаг «Жребий»
    (позиция 6) отдаёт `dice_mail_length`, и ветки читают его сами. Поэтому
    тест больше не может сверить промпт со **своим** значением — он его не
    выбирает.

    Проверяется то, что проверяемо: метка в промпте **раскрылась**. Останься
    она неподставленной (`%dice_mail_length%`), письма вышли бы одной длины, а
    по одному письму этого не видно.
    """

    async def test_the_mark_is_filled_in(self, talk):
        """⚠ Смотрим **вход**, а не ответ: по числу абзацев судить нельзя —
        модель вольна написать два там, где просили «до трёх»."""
        got = await talk(TALK_MAIL_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))

        assert '%dice_mail_length%' not in got.prompt_of(STEP_MAIL_WRITE), \
            f'метка длины осталась в промпте ветки нераскрытой.{got}'

    async def test_the_judge_sees_it_too(self, talk):
        """⚠⚠ Судья тоже читает длину: он решает, годится ли черновик.

        Не увидь он её — мерил бы письмо не тем, чего просили у сочинителя.
        """
        got = await talk(TALK_MAIL_ASK,
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))

        assert '%dice_mail_length%' not in got.prompt_of(STEP_JUDGE), \
            f'метка длины осталась в промпте судьи нераскрытой.{got}'


class TestBothHistoriesTravel:
    """⚠⚠ У пары два разговора — чат и письма, — и агент видит оба.

    Прежде история была одна (`talk_history`), и отвечающий на письмо не помнил
    вчерашней болтовни в чате: человек один, а знание о нём — половинное.
    """

    async def test_the_mail_history_reaches_the_reply(self, talk):
        """⚠ Проверка двойная: незаявленную переменную ручка отвергает `400`
        (тогда тест падает отказом), а заявленную, но не подставленную — никто,
        и её ловит только взгляд в промпт."""
        got = await talk(TALK_MAIL_REPLY_ASK,
                         said='[23.09 12:00] он: Как твои дела?',
                         mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_REPLY))

        assert got.ran(STEP_MAIL_REPLY), \
            f'вызов с двумя историями не дошёл до ветки ответа.{got}'
        assert 'Карпаты' in got.prompt_of(STEP_MAIL_REPLY), \
            f'переписка письмами не доехала до промпта ветки.{got}'

    async def test_the_chat_history_reaches_the_chat(self, talk):
        got = await talk('А ты как думаешь?',
                         said='[23.09 12:00] она: Я вчера пекла шарлотку.')

        assert 'шарлотку' in got.prompt_of(STEP_CHAT), \
            f'история чата не доехала до промпта ветки.{got}'


class TestTheDiceIsThrownFirst:
    """⚠⚠ Разнообразие держится на шаге «Жребий», и держится молча.

    Пропади он — промпты веток получат пустые метки вместо заказа: «Зачин:»,
    «Концовка:», и модель допишет их сама, каждый раз одинаково. Ошибки в журнале
    при этом не будет ни одной: заход удачен, письмо складно, просто все письма
    на одно лицо. Заметить это можно только по десятку писем подряд — то есть
    через сутки работы прода.

    ⚠ Проверяем **вход** веток, а не ответ модели. По тексту судить нельзя:
    выпади «начни с наблюдения о нём», и модель исполнит это десятью способами,
    ни в одном не повторив формулировку.
    """

    async def test_it_runs_before_the_composing(self, talk):
        """⚠ Жребий обязан лечь **раньше сочинения**: его значения уходят метками
        в промпты веток, а выпавшие позже пришли бы в уже собранный промпт.

        ⚠⚠ Проверяется «раньше ветки», а не «первым на маршруте». Первым он не
        стоит и не должен: до него идут заведение собеседника, ленты разговора и
        сборка переменных — жребию они не нужны, а промптам нужны. Прежняя версия
        утверждала `route[0] == STEP_DICE`, и это была **неправда**: шаг стоит
        седьмым и локально, и на проде. Тест был бы красным на любом прогоне —
        под `llm_live` он просто не шёл ни разу.
        """
        got = await talk('Hi! How was your day?')

        assert got.ran(STEP_DICE), f'жребий не отработал.{got}'

        route = list(got.route or ())
        made = [one for one in (STEP_CHAT, STEP_MAIL_WRITE, STEP_MAIL_REPLY,
                                STEP_INITIATIVE) if one in route]

        assert made, f'ни одна ветка сочинения не отработала.{got}'
        assert route.index(STEP_DICE) < min(route.index(one) for one in made), \
            f'жребий выпал позже сочинения — метки пришли в собранный промпт.{got}'

    async def test_the_letter_gets_its_opening(self, talk):
        """Зачин доехал до промпта ветки письма — иначе метка осталась пустой."""
        got = await talk(TALK_MAIL_ASK, mailed=MAIL_HISTORY,
                         variables=_mail_vars(TALK_MAIL_WRITE))
        prompt = got.prompt_of(STEP_MAIL_WRITE)

        assert 'Зачин:' in prompt, f'блока жребия нет в промпте письма.{got}'
        # ⚠ Пустая метка выглядит как «Зачин:» и пустота до конца строки — это и
        # есть тихая поломка, ради которой тест написан.
        assert _after(prompt, 'Зачин:'), \
            f'зачин выпал пустым — жребий до промпта не доехал.{got}'
        assert _after(prompt, 'Концовка:'), \
            f'концовка выпала пустой.{got}'

    async def test_the_initiative_gets_its_way(self, talk):
        """⚠⚠ Приём инициативы переехал из панели в жребий.

        Двенадцать приёмов с весами жили константой в DatingAi, панель слала
        готовое переменной `initiative_kind`. Теперь их бросает жребий, а панель
        шлёт только повод — и если метка в промпте разойдётся с именем выхода,
        модель получит задание без приёма и заговорит одинаково со всеми.
        """
        got = await talk('Собеседник молчит. Напиши ему сама.',
                         variables={'make_initiative': '1', 'answer_anyway': '1'})
        prompt = got.prompt_of(STEP_INITIATIVE)

        assert 'Приём на этот раз:' in prompt, \
            f'в промпте инициативы нет строки приёма.{got}'
        assert _after(prompt, 'Приём на этот раз:'), \
            f'приём выпал пустым — жребий до промпта не доехал.{got}'

    async def test_a_site_setting_reaches_the_dice(self, talk):
        """⚠⚠ Доли трёх осей крутит человек на странице сайта.

        Они уже однажды перестали работать молча: переезд писем на `dating_talk`
        унёс код, который их читал, а ручки остались и крутились впустую.

        Здесь проверяется крайнее значение: `0` значит «никогда», и ни одно
        письмо не должно звать по имени. Утверждать долю в середине нельзя —
        жребий на то и жребий.
        """
        got = await talk(TALK_MAIL_ASK, mailed=MAIL_HISTORY,
                         variables={**_mail_vars(TALK_MAIL_WRITE),
                                    'dice_mail_name_percent': '0'})
        prompt = got.prompt_of(STEP_MAIL_WRITE)

        assert 'Обращение:' in prompt, f'блока жребия нет в промпте.{got}'
        assert 'по имени не обращайся' in prompt, \
            f'при доле 0% выпало обращение по имени — настройка не доехала.{got}'


class TestThePhotoBranchAnswersInCommon:
    """⚠⚠ Ветка «письма и фото» отвечает **общим** шагом «Ответ».

    Своего шага возврата у неё больше нет: он делал ровно то же, отличаясь лишь
    именем переменной. Теперь `outputs_map` кладёт выход сабворкфлоу в
    `girl_response`, и общий шаг отдаёт его сам.

    ⚠ Пара `draft_response → girl_response` в карте обязательна: пропусти её, и
    общий шаг отдал бы пустоту либо прошлое значение. По тексту это не видно —
    ответ останется правдоподобным.

    ⚠⚠ Прежде в карте была ещё правка судьи (`photo_fixed →
    girl_response_fixed`). Ветку переписали вместе с судьёй верхнего уровня:
    оба теперь отдают **вердикт** и правят перегенерацией, а не текстом.
    """

    async def test_it_returns_through_the_common_answer(self, talk, llm_answers):
        await llm_answers(talk_plan(topic='photo_mail'), default=photo_answer())

        got = await talk("Can you send me your photos? I'd love to see more of you")

        assert got.ran(STEP_BRANCH), f'ветка фото не сработала.{got}'
        assert got.ran(STEP_ANSWER), \
            f'ветка фото не дошла до общего шага «Ответ».{got}'

    async def test_the_old_exit_is_gone(self, talk, llm_answers):
        """⚠ Свой шаг возврата убран, и маршрут через него значил бы, что
        миграция `…_wf_talk_photo_branch_one_exit` не доехала до этой базы.

        ⚠⚠ Тема задаётся, и **без этого тест был бы пустым**: утверждение
        отрицательное, а не сработавшая ветка не ходит вообще никуда — «своего шага
        нет» выполнялось бы само собой. Зелёный при незапущенной ветке ничего не
        значит, и поймать такое по цвету нельзя.
        """
        await llm_answers(talk_plan(topic='photo_mail'), default=photo_answer())

        got = await talk('Can you send me your photos?')

        assert got.ran(STEP_BRANCH), \
            f'ветка фото не сработала — проверять было нечего.{got}'
        assert not got.went_through('Ответ ветки'), \
            f'ветка отвечает своим шагом, а не общим.{got}'


def _mail_vars(kind: str) -> dict:
    """Переменные, которые панель кладёт для письма, — все до одной.

    ⚠⚠ **`answer_anyway` здесь обязателен, и забыть его дорого.** Шаг «Анализ
    сообщения» стоит раньше веток и вправе решить «отвечать не нужно»
    (`prompt_user_ignore = 1`), уведя поток на «Тишину» мимо всех веток. В бою
    от этого защищает `anyway=True`, который шлют **оба** почтовых пути
    (`answer_mail_write`, `answer_mail_reply`): человек ждёт письма, и молчание
    читается как «его игнорируют».

    Без него тест проверял бы условия, в которых боевой код не работает. Поймано
    живьём: «ответ на письмо» ушёл в «Тишину», а «письмо первым» уцелело — то
    есть падение было **случайным**, и назавтра могло переехать на соседа.

    ## ⚠⚠⚠ `mail_length` здесь больше НЕТ, и возвращать её нельзя

    Длину письма бросает **шаг «Жребий» внутри самого workflow** (позиция 6):
    он отдаёт `dice_mail_length`, и три ветки письма читают его сами. Прежде
    длину бросала панель и присылала переменной `mail_length`.

    Переменная снята с объявления входящей, а сторож ручки
    (`chat.py:_variables_allowed`) считает **имена** присланного, а не
    значения: лишнее имя — `400` на весь заход. Пришли мы её — упали бы все
    почтовые тесты разом, что и случилось: шестнадцать штук.

    ⚠ То же правило уже стоило прода на стороне DatingAi: объявление сняли
    раньше, чем ушёл шлющий код, и `/chat/ask` отвечал `400` на все четыре
    ветки — включая обычный чат, которому длина не нужна вовсе.
    """
    return {'mail_mode': '1', 'mail_kind': kind, 'answer_anyway': '1'}


def _others(got, wanted: str) -> tuple:
    """Какие ветки отработали, кроме нужной. Пусто — всё верно."""
    return tuple(name for name in STEP_BRANCHES
                 if name != wanted and got.ran(name))


def _after(prompt: str, label: str) -> str:
    """Что стоит в промпте после подписи, до конца строки.

    ⚠⚠ Нужно затем, что **пустая метка не оставляет следа**. Не доедь жребий — в
    промпте будет «Зачин:» и пустота, а `'Зачин:' in prompt` при этом истинно.
    Проверка на наличие подписи такую поломку пропускает целиком; проверять надо
    то, что после неё.
    """
    head, _, tail = str(prompt).partition(label)

    return tail.split('\n')[0].strip() if head or tail else ''
