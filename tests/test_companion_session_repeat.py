"""Анти-луп по разговору пары: что считается повтором, а что законно.

⚠⚠ Что здесь стережётся. Прежняя проверка (`session_response_repeat_check`)
искала прошлые ответы по `session_uuid`, а сосед его не передаёт: движок заводит
новый ключ на каждый запрос, и сравнивать было не с чем никогда — 818 вызовов на
проде, `repeat = 0` во всех. Поломка выглядела как штатная работа, потому что
ноль — законный ответ проверки. Отсюда и тесты: они держат не код, а **источник**
— разговор пары, который живёт в `companion_session` и адресуется ключами сторон.

⚠ Второе, что легко потерять при правке: повтор требует **обоих** условий, пока
входящее сообщение есть. Один и тот же ответ на разные вопросы — не зацикливание.

⚠ Тесты зовут инструмент напрямую: прогон workflow стоит вызова модели, общей с
продом, а проверяется здесь чтение таблицы.

⚠ `asyncio_mode = "auto"` в `pyproject.toml` — своей метки тестам не нужно.
"""
import uuid

import pytest

from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.tool.companion.companion_session import (
    companion_session_add, companion_session_delivered,
    companion_session_repeat_check)

pytestmark = pytest.mark.core


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой."""
    yield
    await mysql_pool_close()


@pytest.fixture
async def pair():
    """Пара ключей, по которой заводится разговор. Убирается за собой."""
    mark = uuid.uuid4().hex[:8]
    keys = (f'rep_own_{mark}', f'rep_him_{mark}')

    yield keys

    async with mysql_get_db_async() as db:
        await db.execute(
            'DELETE s FROM `companion_session` s'
            ' JOIN `companion` c ON c.`id` = s.`owner_id`'
            ' WHERE c.`unique_id` = %s', (keys[0],))
        await db.execute('DELETE FROM `companion` WHERE `unique_id` IN (%s, %s)',
                         keys)
        await db.connection.commit()


class TestRepeatNeedsBothHalves:
    async def test_same_answer_to_same_question_is_repeat(self, pair):
        """Тот же ответ на то же сообщение — зацикливание."""
        await companion_session_add(pair[0], pair[1],
                                    question='ok', answer='sleeping already')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'sleeping already', 'ok')

        assert got['repeat'] == 1, got['why']

    async def test_same_answer_to_new_question_is_allowed(self, pair):
        """⚠ Тот же ответ на РАЗНЫЙ вопрос законен: «да» бывает ответом на многое."""
        await companion_session_add(pair[0], pair[1],
                                    question='ok', answer='sleeping already')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'sleeping already', 'what are you doing tomorrow?')

        assert got['repeat'] == 0, got['why']

    async def test_new_answer_is_allowed(self, pair):
        """Новый текст не повтор, даже если сообщение то же самое."""
        await companion_session_add(pair[0], pair[1],
                                    question='ok', answer='sleeping already')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'reading a book, actually', 'ok')

        assert got['repeat'] == 0, got['why']


class TestWeSpokeFirst:
    async def test_repeated_opening_is_repeat(self, pair):
        """⚠⚠ Заговорили мы сами — второго условия нет, хватает повтора ответа.

        Письмо избранному и инициатива идут без входящего сообщения вовсе. Требуй
        проверка обе половины, она на этих ходах не сработала бы никогда — а
        именно там повтор и заметнее всего: человек получает два похожих письма.
        """
        await companion_session_add(pair[0], pair[1], answer='remembered you today')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'remembered you today')

        assert got['repeat'] == 1, got['why']

    async def test_new_opening_is_allowed(self, pair):
        await companion_session_add(pair[0], pair[1], answer='remembered you today')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'the rain finally stopped here')

        assert got['repeat'] == 0, got['why']


class TestComparedTextIsNormalized:
    async def test_case_and_punctuation_do_not_hide_repeat(self, pair):
        """Регистр, знаки и эмодзи у повтора меняются, а слова — нет."""
        await companion_session_add(pair[0], pair[1], answer='remembered you today')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'REMEMBERED you, today!!! 😊')

        assert got['repeat'] == 1, got['why']


class TestSourceIsTheWholeRecord:
    async def test_undelivered_answer_still_counts(self, pair):
        """⚠⚠ Неподтверждённый ответ из сравнения не выпадает.

        Лента для промпта его прячет — агент не должен продолжать несказанное.
        Здесь вопрос другой: не сочиняли ли мы это уже. Ответ лежит в очереди и
        может уйти следом, поэтому второй такой же — повтор.
        """
        await companion_session_add(pair[0], pair[1], answer='remembered you today')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'remembered you today')

        assert got['repeat'] == 1, got['why']

    async def test_delivered_answer_counts_too(self, pair):
        """И подтверждённый — тоже: отметка на сравнение не влияет."""
        made = await companion_session_add(pair[0], pair[1],
                                           answer='remembered you today')
        await companion_session_delivered(int(made['id']))

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'remembered you today')

        assert got['repeat'] == 1, got['why']


class TestChannelsDoNotMix:
    async def test_letter_does_not_repeat_a_chat_line(self, pair):
        """⚠ Чат и письма — разные разговоры: сказанное в чате письму не повтор."""
        await companion_session_add(pair[0], pair[1],
                                    answer='remembered you today', kind='chat')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'remembered you today', kind='mail')

        assert got['repeat'] == 0, got['why']

    async def test_unknown_channel_falls_back_to_chat(self, pair):
        """Неизвестный канал — чат, как и у соседних функций файла."""
        await companion_session_add(pair[0], pair[1],
                                    answer='remembered you today', kind='chat')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'remembered you today', kind='telegram')

        assert got['repeat'] == 1, got['why']


class TestIncomingAlreadyWritten:
    async def test_pending_incoming_does_not_match_itself(self, pair):
        """⚠⚠ Сообщение, записанное приёмом до ответа, собой себя не повторяет.

        `companion_session_incoming` кладёт его реплику сразу, не дожидаясь
        ответа. Не выпади висящая строка из сравнения, второе условие
        выполнялось бы всегда — и проверка гасила бы ответ на каждое новое
        сообщение.
        """
        await companion_session_add(pair[0], pair[1],
                                    question='ok', answer='sleeping already')
        # Висящая реплика: его слова есть, нашего ответа ещё нет.
        await companion_session_add(pair[0], pair[1], question='and tomorrow?')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'sleeping already', 'and tomorrow?')

        assert got['repeat'] == 0, got['why']

    async def test_pending_incoming_that_repeats_is_still_a_repeat(self, pair):
        """⚠ Висящая реплика выпадает одна: прошлое «ок» в сравнении остаётся."""
        await companion_session_add(pair[0], pair[1],
                                    question='ok', answer='sleeping already')
        await companion_session_add(pair[0], pair[1], question='ok')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'sleeping already', 'ok')

        assert got['repeat'] == 1, got['why']

    async def test_answered_question_is_not_hidden(self, pair):
        """⚠⚠ Закрытый ответом обмен — прошлое, и прятать его нельзя.

        Отбрасывай проверка «первое совпадение» без оглядки на ответ, настоящее
        зацикливание («ок» → «сплю уже» → «ок») осталось бы незамеченным: ровно
        та строка, что его и доказывает, выпала бы из сравнения.
        """
        await companion_session_add(pair[0], pair[1],
                                    question='ok', answer='sleeping already')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'sleeping already', 'ok')

        assert got['repeat'] == 1, got['why']


class TestNothingToCompare:
    async def test_unknown_pair_is_not_a_repeat(self):
        """Пары нет — сравнивать не с чем, ответ пропускаем."""
        got = await companion_session_repeat_check(
            'rep_own_missing', 'rep_him_missing', 'hello there')

        assert got['repeat'] == 0
        assert got['why']

    async def test_empty_keys_are_not_a_repeat(self):
        """⚠ Пустой ключ — «части не доехали», а не «повтор»."""
        got = await companion_session_repeat_check('', '', 'hello there')

        assert got['repeat'] == 0

    async def test_empty_draft_is_not_a_repeat(self, pair):
        """Пустоту гасят шаги до проверки, повтором она не является."""
        await companion_session_add(pair[0], pair[1], answer='remembered you today')

        got = await companion_session_repeat_check(pair[0], pair[1], '   ')

        assert got['repeat'] == 0


class TestLimitComesFromWorkflow:
    async def test_limit_arrives_as_text(self, pair):
        """⚠ Предел приходит workflow-переменной, то есть строкой; мусор — умолчание."""
        await companion_session_add(pair[0], pair[1], answer='remembered you today')

        for given in ('3', '', 'не число', 0):
            got = await companion_session_repeat_check(
                pair[0], pair[1], 'remembered you today', limit=given)

            assert got['repeat'] == 1, f'предел {given!r}: {got["why"]}'

    async def test_older_than_the_limit_is_out_of_sight(self, pair):
        """За пределом окна повтор не ищется: спрошенное месяц назад спрашивают снова."""
        await companion_session_add(pair[0], pair[1], answer='the oldest line')

        for filler in range(3):
            await companion_session_add(pair[0], pair[1], answer=f'filler {filler}')

        got = await companion_session_repeat_check(
            pair[0], pair[1], 'the oldest line', limit=2)

        assert got['repeat'] == 0, got['why']
