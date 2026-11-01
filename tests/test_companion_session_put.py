"""Обмен, сочинённый не прогоном: письмо по обещанию, правка оператора, чужой сервис.

⚠⚠ Что здесь стережётся. В `companion_session` вели две дороги, и обе про
текст, придуманный моделью: прогон workflow и приём его реплики. А отправить
человеку можно и то, чего модель сейчас не сочиняла. Поймано на проде
01.11.2026: письма по намерениям уходят собеседнику, а истории про них нет —
и следующий прогон строит ответ так, будто обещанного письма не было.

⚠⚠⚠ Половина тестов — про **порядок поглощения**. Оно убирает висящие строки,
чей вопрос входит в новый, и вызови мы его после вставки, запись с одним
вопросом подошла бы под это условие сама и **удалила бы себя**. Поймано живьём
при разработке: строка исчезала в тот же миг, а ответ был `saved: 1` с номером
несуществующей строки.
"""
import uuid

import pytest
from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.tool.companion.companion_session import companion_session_put

# ⚠ Группа `core`, как у соседних проверок разговора: прогон по маркеру
# обязан их захватывать — иначе файл не запустится вовсе.
pytestmark = [pytest.mark.asyncio, pytest.mark.core]


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой."""
    yield
    await mysql_pool_close()


@pytest.fixture
async def sides():
    """Части сторон, из которых дверь сама склеит ключи. Убирается за собой."""
    mark = uuid.uuid4().hex[:8]
    parts = {'owner_id': f'90{mark[:4]}', 'owner_name': f'own_{mark}',
             'companion_id': f'91{mark[:4]}', 'companion_name': f'him_{mark}'}

    yield parts

    keys = (f"{parts['owner_id']}_{parts['owner_name']}",
            f"{parts['companion_id']}_{parts['companion_name']}")

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
            '       s.`answer_at`, s.`delivered_at`, s.`created_at`,'
            '       s.`source_uid`, s.`kind`'
            '  FROM `companion_session` s'
            '  JOIN `companion` c ON c.`id` = s.`owner_id`'
            ' WHERE c.`unique_id` = %s ORDER BY s.`id`', (owner_key,))

        return list(await db.fetchall() or [])


def _owner(sides: dict) -> str:
    return f"{sides['owner_id']}_{sides['owner_name']}"


class TestHalvesAreNamedNotGuessed:
    """⚠⚠ У обмена две половины, и дверь принимает их **по именам колонок**.

    Прими она один «текст», ей пришлось бы решать за вызывающего, чья это
    реплика, — а вызывающему догадываться о её решении.
    """

    async def test_our_half_lands_as_answer(self, sides):
        got = await companion_session_put(**sides, answer='as promised',
                                          kind='mail', source_uid='t-1',
                                          delivered=True)

        assert got['saved'] == 1, got['why']

        row = (await _rows(_owner(sides)))[0]

        assert row['answer'] == 'as promised', 'наша половина легла не туда'
        assert row['question'] == '', 'он молчал, а вопрос не пуст'
        # ⚠ Время у половины ставится, только если половина есть: пустая
        # половина со временем читалась бы как «сказал и промолчал».
        assert row['question_at'] is None, 'у пустого вопроса стоит время'
        assert row['answer_at'] is not None, 'у нашей половины нет времени'
        assert row['delivered_at'] is not None, 'доставка не отмечена'

    async def test_his_half_lands_as_question(self, sides):
        got = await companion_session_put(**sides, question='did you send it?',
                                          kind='mail', source_uid='t-2')

        assert got['saved'] == 1, got['why']

        row = (await _rows(_owner(sides)))[0]

        assert row['question'] == 'did you send it?'
        assert row['answer'] == '', 'мы не отвечали, а ответ не пуст'
        assert row['delivered_at'] is None, (
            'доставка отмечена у обмена без нашей половины — отмечать нечего')

    async def test_both_halves_are_a_legal_row(self, sides):
        """Обмен, где он спросил и мы ответили, — такая же законная запись."""
        await companion_session_put(**sides, question='well?',
                                    answer='here you go', source_uid='t-3')

        row = (await _rows(_owner(sides)))[0]

        assert row['question'] and row['answer'], 'половина потерялась'

    async def test_both_empty_is_the_only_refusal(self, sides):
        got = await companion_session_put(**sides, kind='mail')

        assert got['saved'] == 0 and got['id'] == 0
        assert 'пусты' in got['why'], got['why']


class TestTheKeyIsJoinedHere:
    """⚠⚠ Склейка `{номер}_{имя}` принадлежит этой стороне.

    У прогона её держит шаг workflow. Прими дверь готовый ключ, правило лежало
    бы в каждом проекте-вызывающем и разошлось бы молча: завелась бы вторая
    запись той же пары, и агент писал бы человеку как незнакомому.
    """

    async def test_parts_become_one_key(self, sides):
        await companion_session_put(**sides, answer='hi', source_uid='t-4')

        rows = await _rows(_owner(sides))

        assert rows, 'ключ собрался не тем правилом — разговор не нашёлся'

    async def test_a_missing_part_is_refused(self, sides):
        """⚠ Половинка ключа (`_angelas`, `625499_`) — запись, под которой
        разговор найти уже нельзя. Лучше отказ."""
        for gone in ('owner_name', 'companion_id'):
            args = dict(sides)
            args[gone] = ''
            got = await companion_session_put(**args, answer='hi')

            assert got['saved'] == 0, f'записалось без части «{gone}»'
            assert 'стороны' in got['why'], got['why']


class TestAbsorbRunsBeforeTheInsert:
    """⚠⚠⚠ Порядок, который стоил отладки: поглощение — **до** вставки."""

    async def test_a_lone_question_does_not_delete_itself(self, sides):
        """Строка с одним вопросом подходит под условия поглощения: ответ
        пуст, вопрос входит сам в себя. Вставь её раньше — она исчезнет."""
        got = await companion_session_put(**sides, question='did you send it?',
                                          kind='mail', source_uid='t-5')

        rows = await _rows(_owner(sides))

        assert rows, (
            'запись съела сама себя: поглощение зовётся после вставки, а не до')
        assert int(rows[0]['id']) == int(got['id']), (
            'ответ назвал номер строки, которой нет')

    async def test_a_stranger_exchange_keeps_it(self, sides):
        """⚠ Чужой вопрос висящую строку не трогает — границы узкие нарочно."""
        await companion_session_put(**sides, question='did you send it?',
                                    kind='mail', source_uid='t-6')
        await companion_session_put(**sides, question='well?', answer='yes',
                                    kind='mail', source_uid='t-7')

        assert len(await _rows(_owner(sides))) == 2, (
            'посторонний обмен убрал чужую висящую реплику')

    async def test_an_exchange_that_swallowed_it_absorbs(self, sides):
        """А вобравший её — поглощает: иначе лента покажет её дважды."""
        await companion_session_put(**sides, question='did you send it?',
                                    kind='mail', source_uid='t-8')
        await companion_session_put(**sides,
                                    question='well? did you send it?',
                                    answer='yes', kind='mail',
                                    source_uid='t-9')

        rows = await _rows(_owner(sides))

        assert len(rows) == 1, (
            'висящая реплика осталась рядом с обменом, который её вобрал')


class TestRepeatDoesNotDouble:
    """⚠ Повтор вызова не кладёт вторую строку — защита на `source_uid`."""

    async def test_same_source_uid_is_kept_once(self, sides):
        first = await companion_session_put(**sides, answer='hi',
                                            kind='mail', source_uid='t-10')
        again = await companion_session_put(**sides, answer='hi',
                                            kind='mail', source_uid='t-10')

        assert again['saved'] == 0 and again['id'] == first['id']
        assert len(await _rows(_owner(sides))) == 1

    async def test_an_unknown_channel_is_refused(self, sides):
        got = await companion_session_put(**sides, answer='hi', kind='telegram')

        assert got['saved'] == 0 and 'канал' in got['why'], got['why']
