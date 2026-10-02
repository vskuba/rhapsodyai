"""Приём входящего: реплика собеседника попадает к нам и без нашего ответа.

⚠⚠ Что здесь стережётся. Единственная дорога в `companion_session` шла через
прогон workflow, а его запускает `/chat/ask` — то есть **решение ответить**.
Реплика, оставшаяся без ответа, не попадала к нам ничем: ни ошибки, ни следа.
Замерено на проде 02.10.2026 — двенадцать таких за восемь дней, среди них
«how did you sleep???» и «sent you photo».

⚠⚠⚠ Вторая половина задачи — **не задвоить**. Приём пишет реплику сразу, а
через минуту агент отвечает, и шаг workflow кладёт обмен, где та же реплика
стоит вопросом (автоответчик соседа склеивает хвост). Висящие строки при этом
обязаны исчезнуть: `_pending_absorb`. Это единственное место, где инструмент
удаляет строки, и границы у него узкие — им здесь посвящена половина тестов.

⚠ Тесты зовут инструмент напрямую: проверяется запись в таблицу, а не HTTP.
Ручка над ним тонкая (`/chat/message/incoming`) и своей логики не несёт.
"""
import uuid

import pytest

from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.tool.companion.companion_session import (companion_session_add,
                                                  companion_session_delivered,
                                                  companion_session_incoming,
                                                  companion_session_rows)

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
    keys = (f'in_own_{mark}', f'in_him_{mark}')

    yield keys

    async with mysql_get_db_async() as db:
        await db.execute(
            'DELETE s FROM `companion_session` s'
            ' JOIN `companion` c ON c.`id` = s.`owner_id`'
            ' WHERE c.`unique_id` = %s', (keys[0],))
        await db.execute('DELETE FROM `companion` WHERE `unique_id` IN (%s, %s)',
                         keys)
        await db.connection.commit()


async def _rows(owner_key: str) -> list:
    """Строки разговора этой стороны, по порядку записи."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT s.`id`, s.`question`, s.`answer`, s.`question_at`,'
            '       s.`delivered_at`, s.`source_uid`'
            '  FROM `companion_session` s'
            '  JOIN `companion` c ON c.`id` = s.`owner_id`'
            ' WHERE c.`unique_id` = %s ORDER BY s.`id`', (owner_key,))

        return list(await db.fetchall() or [])


class TestIncomingIsStored:
    async def test_reply_without_answer_reaches_us(self, pair):
        """⚠⚠ Ради этого всё: реплика записана, хотя мы не отвечали."""
        got = await companion_session_incoming(*pair, 'how did you sleep???',
                                               source_uid='probe:1')

        assert got['saved'] == 1 and got['id'] > 0

        rows = await _rows(pair[0])

        assert len(rows) == 1
        assert rows[0]['question'] == 'how did you sleep???'
        assert rows[0]['answer'] == '', 'ответа нет — его ещё не сочинили'
        assert rows[0]['delivered_at'] is None, \
            'отметка доставки про НАШУ реплику, а её тут нет'

    async def test_said_at_is_kept(self, pair):
        """Время берётся у источника: реплику могли привезти задним числом."""
        await companion_session_incoming(*pair, 'вчерашнее', source_uid='probe:2',
                                         said_at='2026-09-30 07:08:00')

        rows = await _rows(pair[0])

        assert str(rows[0]['question_at']) == '2026-09-30 07:08:00'

    async def test_repeat_does_not_double(self, pair):
        """⚠ Повтор вызова не кладёт вторую строку — защита на `source_uid`."""
        first = await companion_session_incoming(*pair, 'ты тут?',
                                                 source_uid='probe:3')
        again = await companion_session_incoming(*pair, 'ты тут?',
                                                 source_uid='probe:3')

        assert again['saved'] == 0 and again['id'] == first['id']
        assert len(await _rows(pair[0])) == 1

    async def test_empty_text_is_refused(self, pair):
        """Пустая реплика — не «запиши пустоту», а «части не доехали»."""
        got = await companion_session_incoming(*pair, '   ', source_uid='probe:4')

        assert got['saved'] == 0 and got['why']
        assert await _rows(pair[0]) == []


class TestPendingIsAbsorbed:
    async def test_queue_collapses_into_one_exchange(self, pair):
        """⚠⚠⚠ Три принятые реплики исчезают, когда приходит обмен с ними.

        Иначе лента показала бы их дважды: висящими строками и в составе
        обмена. Склейку делает автоответчик соседа, разделитель — пустая
        строка.
        """
        for i, text in enumerate(('mmmmmm', 'good and you???',
                                  'how did you sleep???')):
            await companion_session_incoming(*pair, text, source_uid=f'q:{i}')

        assert len(await _rows(pair[0])) == 3

        glued = 'mmmmmm\n\ngood and you???\n\nhow did you sleep???'
        await companion_session_add(*pair, question=glued,
                                    answer='coffee was perfect')

        rows = await _rows(pair[0])

        assert len(rows) == 1, 'висящие реплики не убрались'
        assert rows[0]['question'] == glued and rows[0]['answer']

    async def test_foreign_reply_survives(self, pair):
        """⚠ Реплика, не вошедшая в вопрос, остаётся: удаляем только своё."""
        await companion_session_incoming(*pair, 'про погоду', source_uid='f:1')
        await companion_session_incoming(*pair, 'про работу', source_uid='f:2')

        await companion_session_add(*pair, question='про погоду',
                                    answer='да, холодно')

        left = [r['question'] for r in await _rows(pair[0])]

        assert 'про работу' in left, 'убрали реплику, которой не отвечали'

    async def test_answered_row_is_not_touched(self, pair):
        """Строка с ответом не поглощается: у неё наша половина уже написана."""
        made = await companion_session_add(*pair, question='ты тут?',
                                           answer='тут')
        await companion_session_delivered(int(made['id']))

        await companion_session_add(*pair, question='ты тут? и ещё раз ты тут?',
                                    answer='да')

        rows = await _rows(pair[0])

        assert len(rows) == 2, 'закрытый обмен убирать нельзя'

    async def test_stale_pending_survives(self, pair):
        """⚠ Вчерашняя висящая реплика к сегодняшнему ответу не относится."""
        old = await companion_session_incoming(*pair, 'вчерашнее',
                                               source_uid='s:1')

        async with mysql_get_db_async() as db:
            await db.execute('UPDATE `companion_session`'
                             ' SET `created_at` = NOW() - INTERVAL 2 DAY'
                             ' WHERE `id` = %s', (int(old['id']),))
            await db.connection.commit()

        await companion_session_add(*pair, question='вчерашнее и сегодняшнее',
                                    answer='ответ')

        assert any(r['id'] == old['id'] for r in await _rows(pair[0])), \
            'съели вчерашнюю реплику, которая к этому ответу не относится'


class TestFeedStaysHonest:
    async def test_pending_reply_is_visible_to_the_agent(self, pair):
        """Принятая реплика идёт в ленту сразу: его слова доставлены приходом.

        ⚠ Это не противоречит `delivered_at`: та отметка про НАШ ответ, а
        здесь его нет вовсе. Выдачу `companion_session_rows` строка проходит
        по условию «вопрос непуст».
        """
        await companion_session_incoming(*pair, 'ты меня слышишь?',
                                         source_uid='v:1')

        feed = await companion_session_rows(*pair)

        assert len(feed) == 1
        assert feed[0]['question'] == 'ты меня слышишь?'
        assert feed[0]['answer'] == '', 'ответа не было — выдумывать нечего'
