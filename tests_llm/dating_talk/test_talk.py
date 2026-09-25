"""Чат с девушкой: разговор доходит до ответа и сворачивает куда надо.

## ⚠⚠ Что здесь проверяется

Не «хорошо ли отвечает модель» — этого тестом не измерить. Проверяется **ход
разговора**: прогон дошёл до конца, пошёл по той ветке, по какой должен, и
структурные решения шагов совпали с замыслом.

## ⚠⚠ ПРАВИЛО: утверждения — только по трассе

**Ни один тест не смотрит на текст ответа.** Ни поиском слова, ни длиной, ни
«не пустой». Всё берётся из трассы: `route`, `vars`, `prompt_of`, `output_of`,
`status`.

Три теста отсюда убраны именно по этому правилу — они искали в ответе приметы
отказа, символ `@` и считали слова. Подробности и живые примеры, на которых
правило куплено, — `.claude/docs/testing_llm.md`.

Минимум вопросов и ответов: каждый стоит от десяти секунд и денег.

## Запуск — руками, путём к папке

    .venv/bin/python3 -m pytest tests_llm/dating_talk -q

⚠ Сами они не идут: папки нет в `testpaths`. Модель одна на тесты и на прод, и
прогон занимает её очередь вместо живых собеседников.

⚠ Красное здесь — повод посмотреть трассу (`/admin/workflow_trace`), а **не
перезапустить**. Утверждения берутся из трассы и от прогона к прогону не меняются:
покраснело — значит сломано.
"""

import pytest

from tests_llm.dating_talk.conftest import (STEP_ANSWER, STEP_BRANCH,
                                            STEP_FACTS_TAGS, STEP_FACTS_PLAIN,
                                            STEP_SILENCE)

pytestmark = pytest.mark.llm_live

class TestTheTalkGoesThrough:
    """⚠ Первое, что должно работать: агент вообще отвечает."""

    async def test_a_plain_message_gets_an_answer(self, talk):
        """⚠ «Ответила» спрашиваем у маршрута, а не у длины строки.

        Здесь стояло `got.text.strip()`. Пустой ответ — это законный исход
        «Тишина», и у него свой шаг: маршрут о нём говорит прямо, а длина строки
        лишь намекает.
        """
        got = await talk('Hi! How was your day?')

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'
        assert not got.went_through(STEP_SILENCE), \
            f'на обычное приветствие ушла в тишину.{got}'

    async def test_the_route_reaches_the_answer_step(self, talk):
        """Маршрут кончается отдачей ответа, а не обрывается посередине."""
        got = await talk("I'm from Berlin, and you?")

        assert STEP_ANSWER in got.route or STEP_BRANCH in got.route, \
            f'прогон не дошёл ни до ответа, ни до ветки.{got}'


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


class TestGirlFactsAreSearchedByTagsFirst:
    """⚠⚠ Факты девушки ищутся сперва по тегам, без тегов — только как откат.

    «Анализ сообщения» размечает реплику тегами, и поиск фактов собеседника и
    разговора ими пользовался, а поиск фактов самой девушки — нет. Одним вызовом
    это не чинится: `tags` — поле `must`, указал его — и факты без этих тегов не
    найдутся вовсе. Отсюда второй шаг и откат.
    """

    async def test_the_tagged_search_always_runs(self, talk):
        """⚠ Он первый в цепочке: не отработал — не будет и отката."""
        got = await talk('Hi! How was your day?')

        assert got.went_through(STEP_FACTS_TAGS), \
            f'поиск фактов девушки по тегам не отработал.{got}'

    async def test_nothing_found_falls_back_to_the_plain_search(self, talk):
        """⚠⚠ Откат: не нашлось по тегам — ищем без них.

        Ожидание не в том, что она ответит про физику, а в том, что из двух
        исходов случился **правильный**: нашлось по тегам — откат не нужен;
        не нашлось — откат обязан отработать.

        ## ⚠⚠ Тест смотрел на переменную, которой нет

        Здесь стояло `got.vars.get('qdrant_fact_search_result_tagged')` —
        имя, выдуманное при написании теста. Настоящее несёт **номер шага**
        (`qdrant_fact_search_1529_result_str`), а номера у каждой базы свои:
        вписать его значило бы сломать тест на проде.

        Из-за этого `.get()` всегда возвращал `None`, и ветка «нашлось по тегам»
        считалась провалом: тест краснел два раза из пяти при исправном
        workflow. Проверено по трассе — маршрут в обоих случаях шёл верно.

        Теперь спрашиваем **вывод шага** (`output_of`): он лежит в трассе под
        именем шага, и знать номер не нужно.
        """
        got = await talk('Do you follow quantum chromodynamics research?')

        assert got.went_through(STEP_FACTS_TAGS), f'шаг с тегами не отработал.{got}'

        # Нашлось по тегам — откат не нужен и не должен был случиться.
        if got.output_of(STEP_FACTS_TAGS).strip():
            return

        assert got.went_through(STEP_FACTS_PLAIN), \
            f'по тегам не нашлось, а откат не отработал.{got}'

    async def test_the_answer_survives_either_path(self, talk):
        """⚠⚠ Этот тест поймал живую ошибку.

        Прежде шаг без тегов отрабатывал всегда, и его переменная существовала к
        моменту генерации сама собой. Теперь его можно пропустить — и переменной
        не стало вовсе, а сторож меток роняет шаг, когда метка осталась без
        значения. «Генерация ответа» отказывала ровно тогда, когда поиск по тегам
        срабатывал, — то есть на удаче, а не на неудаче.
        """
        for question in ('So what is your job like these days?',
                         'What do you do on weekends?'):
            got = await talk(question)

            assert got.status == 'success', \
                f'прогон оборвался на {question!r}.{got}'
