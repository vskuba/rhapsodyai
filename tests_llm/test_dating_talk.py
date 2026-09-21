"""Чат с девушкой: разговор доходит до ответа и сворачивает куда надо.

## ⚠⚠ Что здесь проверяется

Не «хорошо ли отвечает модель» — этого тестом не измерить. Проверяется **ход
разговора**: прогон дошёл до конца, пошёл по той ветке, по какой должен, и
структурные решения шагов совпали с замыслом.

Минимум вопросов и ответов: каждый стоит от десяти секунд и денег.

## ⚠ Запуск — только руками

    .venv/bin/python3 -m pytest tests_llm/ -v -s

Папки нет в `testpaths`, полная сюита её не видит. Перед выкладкой их **не
гоняют**: тесты плавающие, стопроцентного зелёного не дают и не должны.

Красное здесь — повод посмотреть трассу (`/admin/workflow_trace`), а не
перезапустить.
"""

import pytest

from tests_llm.conftest import STEP_ANSWER, STEP_BRANCH, STEP_TOPIC

pytestmark = pytest.mark.llm

# Приметы отказа: узкий список, а не «похоже на нет». Ловим ровно то, что уже
# видели в живых ответах, — иначе тест начнёт спорить о формулировках.
DENIAL = ("don't share photo", 'dont share photo', "don't send photo", 'dont send photo',
          "don't send pic", 'dont send pic', 'not sending photo', 'не отправляю фото',
          'не шлю фото')


def _denies(text: str) -> str:
    low = str(text or '').lower()

    return next((one for one in DENIAL if one in low), '')


class TestTheTalkGoesThrough:
    """⚠ Первое, что должно работать: агент вообще отвечает."""

    async def test_a_plain_message_gets_an_answer(self, talk):
        got = await talk('Hi! How was your day?')

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'
        assert got.text.strip(), f'ответ пустой.{got}'

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
        """⚠⚠ Этот тест поймал живую ошибку: на «пришли свои» ветка отвечала
        «i dont send pics here» и ставила `photo_deal = mail`.

        Причина — системный промпт персоны (`girl_prompt_system`): «The same
        applies to photos: you don't send them». Он перебивает промпт шага, и
        правится там, а не здесь.
        """
        got = await talk("Can you send me your photos? I'd love to see more of you")

        assert got.vars.get('photo_deal') in ('mine', 'both'), \
            f'свои фотографии не пообещали.{got}'

    async def test_it_does_not_refuse_outright(self, talk):
        """Прямой отказ — то, что промпт ветки запрещает отдельным пунктом:
        «он спросил прямо, и уклончивость читается как „нет"»."""
        got = await talk('Can you send me your photos?')
        found = _denies(got.text)

        assert not found, f'ответ отказывает («{found}»).{got}'

    async def test_going_to_letters_is_agreed(self, talk):
        """Переход в письма без упоминания фотографий — тоже случай ветки."""
        got = await talk("Let's continue in letters, it's easier to write there")

        assert got.went_through(STEP_BRANCH), f'переход в письма мимо ветки.{got}'
        assert got.vars.get('photo_deal'), f'ветка не назвала, о чём договорились.{got}'


class TestTheBranchKeepsTheRules:
    """⚠ Запреты промпта — то, что дороже всего стоит на живом сайте."""

    async def test_no_contacts_leak(self, talk):
        """Почта и телефон вне сайта — прямой запрет промпта и повод для бана."""
        got = await talk('Send me your photos to my email, what is your email?')

        assert '@' not in got.text, f'в ответе почта.{got}'

    async def test_the_answer_is_short(self, talk):
        """⚠ До 25 слов по промпту. Берём запас вдвое: считаем не редактуру, а
        срыв в сочинение — длинный ответ в чате выдаёт бота вернее опечаток."""
        got = await talk('I want to send you my photos, can I?')

        assert len(got.text.split()) <= 50, f'ответ разросся.{got}'


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
        got = await talk('so can i?', history=(
            'Gerard: can i send you a few photos of me?\n'
            'Она: hmm, maybe\n'))

        assert got.vars.get('talk_topic') == 'photo_mail', \
            f'короткий вопрос без истории не прочитался.{got}'
