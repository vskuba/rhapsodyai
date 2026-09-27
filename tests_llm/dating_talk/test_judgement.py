"""Суждения модели: то, чего подмена проверить не может по существу.

## ⚠⚠⚠ ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ — И ПОЧЕМУ ЭТИ ДЕСЯТЬ ЖИВЫЕ

Остальные тесты папки идут на подмене (`ai.ai_llm_fake`): они утверждают
**устройство** — какой шаг отработал, что доехало до промпта, куда свернул
маршрут. Подмена отвечает заданным, и устройство при этом работает по-настоящему.

Здесь утверждается другое: **что модель решила сама**. Опознала ли просьбу о фото,
сочла ли вопрос вопросом, в какую сторону договорилась о снимках, поняла ли
короткое «so can i?» из предыдущей реплики.

На подмене такая проверка становится **кругом**: `talk_plan(topic='photo_mail')`
кладёт `talk_topic`, а тест его же и читает. Зелёный означал бы, что фикстура
сработала, — и ничего больше. Поэтому здесь и только здесь остаётся `llm_live`.

⚠ Разница видна на паре: подменный `test_a_photo_topic_takes_the_branch`
(`test_route.py`) утверждает, что **решение уводит в ветку**; живой
`test_a_photo_request_turns_into_the_branch` ниже — что **решение принято верно**.
Это два разных вопроса, и снять один другим нельзя.

## ⚠⚠ Что это значит для красного

Красное здесь — не обязательно поломка кода. Это может быть и «модель сегодня
решила иначе»: она отвечает не одинаково, и доля удач у каждого теста своя
(замеры — в докстрингах). Смотреть надо трассу (`/admin/workflow_trace`), а
чинить — промпт шага, миграцией.

⚠⚠ Именно поэтому таких тестов должно быть **мало**. Каждый — заявка «модель
обязана понимать вот это», и каждая заявка стоит очереди общей ноды.

## Запуск — руками, по решению человека

    LLM_LIVE=1 .venv/bin/python3 -m pytest tests_llm/dating_talk/test_judgement.py -q

⚠ Сами они не идут: `llm_live` исключён из `addopts`. Модель одна на тесты и на
прод — пока идут тесты, девушка молчит.
"""

import pytest

from tests_llm.dating_talk.conftest import ANYWAY, STEP_BRANCH
from tests_llm.mark import mark_key

pytestmark = pytest.mark.llm_live


@pytest.fixture
def stranger():
    """Собеседник, о котором фактов нет и быть не может: ключ свой на прогон."""
    return mark_key('judge')


class TestTheTopicIsRecognised:
    """⚠⚠ Развилка: шаг «Тема разговора» решает, куда свернуть.

    Эти тесты стерегут то, из-за чего ветка однажды уже сломалась: движок идёт к
    следующему шагу по порядку, и ветка, стоящая не на своём месте, ловит поток
    обычного разговора.
    """

    async def test_small_talk_stays_on_the_usual_path(self, talk):
        """⚠ Обратная сторона развилки, и она важнее прямой: ветка, куда уходит
        всё подряд, хуже отсутствующей."""
        got = await talk('Hi! How was your day?')

        assert got.vars.get('talk_topic') == 'usual', f'обычная болтовня ушла в ветку.{got}'
        assert not got.went_through(STEP_BRANCH), f'сработала ветка письма-фото.{got}'

    async def test_a_photo_request_turns_into_the_branch(self, talk):
        got = await talk("Can you send me your photos? I'd love to see more of you")

        assert got.vars.get('talk_topic') == 'photo_mail', f'тема не распознана.{got}'
        assert got.went_through(STEP_BRANCH), f'ветка не сработала.{got}'

    async def test_his_photos_offer_turns_into_the_branch(self, talk):
        got = await talk('I want to send you my photos, can I?')

        assert got.vars.get('talk_topic') == 'photo_mail', f'тема не распознана.{got}'
        assert got.went_through(STEP_BRANCH), f'ветка не сработала.{got}'

    async def test_a_photo_word_in_passing_is_not_the_topic(self, talk):
        """⚠ «Тема поднята» ≠ «слово прозвучало». Рассказ о поездке с упоминанием
        снимков — обычный разговор, и промпт говорит про это прямо."""
        got = await talk('I went hiking last weekend and took some photos of the lake')

        assert got.vars.get('talk_topic') == 'usual', \
            f'упоминание снимков в рассказе приняли за тему.{got}'


class TestTheBranchAgrees:
    """⚠⚠ Ветка заведена ради согласия в **обе** стороны.

    Принять его фотографии и пообещать свои — разные случаи, и промпт разбирает
    их по отдельности. Согласие только в одну сторону обесценивает ветку: ровно
    ради второй её и писали.
    """

    async def test_it_accepts_his_photos(self, talk):
        got = await talk('I want to send you my photos, can I?')

        assert got.vars.get('photo_deal') in ('his', 'both'), \
            f'его фотографии не приняли.{got}'

    async def test_it_promises_her_photos(self, talk):
        """⚠⚠ Этот тест поймал два живых изъяна, и оба были **в ветке**.

        Он падал двое суток, и вина списывалась на персону: там когда-то стояло
        «you don't send them or promise anything specific». ⚠ Фразу сняли
        21 сентября, а тест продолжал падать — значит объяснение было неверным.

        Настоящая причина поднята из трассы прогона (23 сентября):

            шаг «Ответ про письма и фото»
              photo_response: "sure, send yours first! i love seeing new pics"
              photo_deal:     "his"          ← перевернул направление
            шаг «Проверка ответа про фото»
              photo_fixed:    "I don't share photos here…"   ← отказ вместо правки

        Первое: на просьбу «пришли свои» ветка ответила «пришли сначала ты» —
        подмена случая 2 случаем 1. Второе, и оно опаснее: **судья заменил
        согласие отказом**, хотя в его списке стоит «в нём есть согласие, а не
        увёртка». Его правила были написаны про черновик, и про то, что пишет он
        сам, там не говорилось ни слова.

        Чинилось промптами ветки (`20260923130000_wf_photo_branch_fix.sql`):
        различение «просит моё / предлагает своё» поднято в начало пункта, добавлена
        сверка «кто кого просит» перед ответом, судье запрещено отказывать своей
        правкой. Замерено после правки: 4 из 5 против 0 из 5.

        ⚠ Обратная сторона (`test_it_accepts_his_photos`) при этом осталась
        целой — 5 из 5. Ровно на ней сломалась прошлая попытка чинить персоной.
        """
        got = await talk("Can you send me your photos? I'd love to see more of you")

        assert got.vars.get('photo_deal') in ('mine', 'both'), \
            f'свои фотографии не пообещали.{got}'

    async def test_going_to_letters_is_agreed(self, talk):
        """Переход в письма без упоминания фотографий — тоже случай ветки."""
        got = await talk("Let's continue in letters, it's easier to write there")

        assert got.went_through(STEP_BRANCH), f'переход в письма мимо ветки.{got}'
        assert got.vars.get('photo_deal'), f'ветка не назвала, о чём договорились.{got}'


# ⚠⚠ **Здесь стоял класс `TestTheBranchKeepsTheRules` — и он убран.**
#
# Два теста: «в ответе нет `@`» и «ответ не длиннее пятидесяти слов». Оба про
# текст, то есть про красноречие модели, а не про код: правила эти держит промпт
# ветки, и проверить их трассой нечем — структурного поля «утекли ли контакты» у
# шага нет.
#
# Это не значит, что правила неважны: утечка почты — повод для бана на сайте.
# Значит лишь, что стеречь их надо там, где ответ однозначен, — сторожем в самом
# коде отправки, а не гаданием по строке. Тест же, зелёный на удаче, создавал
# ложное чувство, что запрет проверен.

class TestTheHistoryIsHeard:
    """⚠ Тема поднимается репликой, но опирается на разговор.

    Ответ «yes, please do» сам по себе ни о чём не говорит — смысл ему даёт
    предыдущая фраза собеседника.
    """

    async def test_a_short_question_is_read_from_history(self, talk):
        """⚠ История должна быть **про саму тему**, а не про поездку со снимками.

        Первая проба этого теста давала историей «I have some new photos from my
        trip» и ждала `photo_mail`. Модель отвечала `usual` — и была права:
        промпт развилки прямо говорит, что слово «фото» в рассказе о поездке
        темой не является. Тест спорил с правилом, которое сам же проверяет.
        """
        got = await talk('so can i?', said=(
            'Gerard: can i send you a few photos of me?\n'
            'Она: hmm, maybe\n'))

        assert got.vars.get('talk_topic') == 'photo_mail', \
            f'короткий вопрос без истории не прочитался.{got}'


class TestTheMessageIsUnderstood:
    """⚠⚠ Разбор реплики: тут утверждается, что модель **справилась**.

    Оба теста — про её суждение, не про проводку. Что шаг разбора отработал и что
    он завёл свои переменные, проверяет `test_facts.py` на подмене; здесь — что
    внутри переменных оказалось осмысленное.

    ⚠ Первый из них стоит на грани правила «не судить модель». Он и есть суждение:
    «разбор выделил хоть что-то». Ровно такую проверку сняли у соседнего теста
    (`test_the_analysis_hands_facts_over`), когда она упала на фразе «I am 45, I
    live in Porto and I work as an architect» — плотнее фактами не придумать.
    Здесь она оставлена сознательно и живой: пустые теги ломают поиск фактов, и
    знать об этом надо, — но краснеть она будет и от лени модели.
    """

    async def test_it_pulls_tags_out_of_the_message(self, talk, stranger):
        """⚠ Теги — вход поиска фактов. Пустые значат, что искать будут вслепую.

        Проверяем **наличие**, а не состав: какие именно слова выберет модель —
        её дело, а вот пустая строка ломает следующий шаг.
        """
        got = await talk('I work as a carpenter and I love fishing on weekends.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert str(got.vars.get('prompt_user_tags') or '').strip(), \
            f'разбор не дал ни одного тега.{got}'

    async def test_a_question_is_marked_as_a_question(self, talk, stranger):
        """⚠ Признак вопроса — **развилка маршрута**, а не подсказка.

        По нему шаг фактов решает, идти ли за фактами девушки: на прямой вопрос
        о ней они нужны, на рассказ о себе — нет.
        """
        got = await talk('What do you do for work?',
                         variables={'companion_name': stranger, **ANYWAY})

        assert str(got.vars.get('prompt_user_question')) == '1', \
            f'прямой вопрос не опознан вопросом.{got}'
