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


class TestItDoesNotAbsorb:
    """⚠⚠⚠ Эта дверь **ничего не удаляет**, и так было не всегда.

    Поглощение здесь стояло и было неверным: оно убирает висящие реплики, чей
    текст входит в новый вопрос, а верно это ровно там, где вызывающий знает,
    что его вопрос — **склейка наших же висящих строк**. Знает это одно место:
    прогон (`companion_session_add`), где склейку делает сама панель.

    Сюда приходит обмен, сочинённый кем угодно. Правило вхождения — обычная
    подстрока, и на чужом тексте оно срабатывает наугад: `'ok'` входит в
    `'I will book a flight'` («bo-ok»). То есть это была не защита от дубля, а
    мина — и на проде она не сработала ни разу только потому, что вопрос сюда
    не передаёт никто.
    """

    async def test_a_lone_question_survives(self, sides):
        """Строка с одним вопросом подходила под условия поглощения: ответ
        пуст, вопрос входит сам в себя. Теперь удалять некому вовсе."""
        got = await companion_session_put(**sides, question='did you send it?',
                                          kind='mail', source_uid='t-5')

        rows = await _rows(_owner(sides))

        assert rows, 'запись исчезла — поглощение вернулось'
        assert int(rows[0]['id']) == int(got['id']), (
            'ответ назвал номер строки, которой нет')

    async def test_an_exchange_that_swallowed_it_keeps_it(self, sides):
        """⚠ Даже вобравший её обмен висящую строку **не трогает**.

        Прежде он её убирал. Если дубль в ленте когда-нибудь станет виден —
        чинить его надо у той двери, что склеивала, а не удалением здесь: тут
        про склейку ничего не известно.
        """
        await companion_session_put(**sides, question='did you send it?',
                                    kind='mail', source_uid='t-8')
        await companion_session_put(**sides,
                                    question='well? did you send it?',
                                    answer='yes', kind='mail',
                                    source_uid='t-9')

        assert len(await _rows(_owner(sides))) == 2

    async def test_a_short_pending_line_is_not_eaten(self, sides):
        """⚠⚠ Тот самый случай, из-за которого поглощение и снято.

        «ok» входит подстрокой в «book» — и реплика, которой собеседник
        открыл разговор, исчезла бы молча.
        """
        await companion_session_put(**sides, question='ok', source_uid='t-10')
        await companion_session_put(**sides,
                                    question='I will book a flight',
                                    answer='great', source_uid='t-11')

        texts = [r['question'] for r in await _rows(_owner(sides))]

        assert 'ok' in texts, 'короткая реплика съедена по вхождению подстроки'

    async def test_nothing_here_deletes(self):
        """⚠ Сторож на сам код: `DELETE` и поглощение сюда не возвращаются.

        Проверяется **вызовами**, а не текстом файла: имя `_pending_absorb`
        стоит в соседнем объяснении, и поиск по строке краснел бы на верном
        коде.
        """
        from tests_.tests_guard import tests_guard_calls

        calls = tests_guard_calls(companion_session_put)

        assert '_pending_absorb' not in calls


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


class TestTheMomentCanBeTold:
    """⚠⚠ Время половины — довод, а не только часы сервера.

    Здесь стояло «времени в доводах нет», и для письма по обещанию это верно:
    его шлют в тот же миг. А правку оператора пишут руками в панели сайта, и
    узнаёт о ней источник заходом импорта — иногда через сутки. Поставь такой
    строке «сейчас», и привезённая переписка легла бы в ленту одним числом:
    агент увидел бы недельный разговор случившимся в одну минуту.
    """

    async def test_our_half_keeps_the_told_moment(self, sides):
        got = await companion_session_put(**sides, answer='написано вчера',
                                          source_uid='t-when-1',
                                          said_at='2026-10-20 08:15:00')

        assert got['saved'] == 1, got['why']

        row = (await _rows(_owner(sides)))[0]

        assert str(row['answer_at']) == '2026-10-20 08:15:00'

    async def test_his_half_keeps_it_too(self, sides):
        """Половины обмена мерятся одними часами — обе берут один довод."""
        await companion_session_put(**sides, question='он спросил вчера',
                                    source_uid='t-when-2',
                                    said_at='2026-10-20 08:15:00')

        row = (await _rows(_owner(sides)))[0]

        assert str(row['question_at']) == '2026-10-20 08:15:00'

    async def test_delivery_is_stamped_by_the_same_moment(self, sides):
        """⚠ Доставка не может быть позже самой реплики: время одно."""
        await companion_session_put(**sides, answer='ушло вчера',
                                    source_uid='t-when-3', delivered=True,
                                    said_at='2026-10-20 08:15:00')

        row = (await _rows(_owner(sides)))[0]

        assert str(row['delivered_at']) == '2026-10-20 08:15:00'

    async def test_without_it_nothing_changes(self, sides):
        """⚠ Прежнее поведение — умолчание: пусто значит «сейчас».

        Письму по обещанию довод не нужен, и требовать его значило бы менять
        работающую дорогу ради новой.
        """
        from datetime_.datetime_ import datetime_utc_now

        before = datetime_utc_now().replace(tzinfo=None)
        await companion_session_put(**sides, answer='шлём сейчас',
                                    source_uid='t-when-4')

        row = (await _rows(_owner(sides)))[0]

        assert row['answer_at'] >= before.replace(microsecond=0)

    async def test_an_unreadable_moment_falls_back_to_now(self, sides):
        """Непонятная строка — «сейчас», а не отказ.

        ⚠ Сторона ошибки выбрана: потерять реплику из-за формата даты хуже,
        чем показать её не тем часом. То же правило у приёма входящего.
        """
        got = await companion_session_put(**sides, answer='время не разобрать',
                                          source_uid='t-when-5',
                                          said_at='позавчера вечером')

        assert got['saved'] == 1, got['why']
        assert (await _rows(_owner(sides)))[0]['answer_at'] is not None


class TestTheOneDoorHoldsBothRoads:
    """⚠⚠ Одна дверь вместо двух: `incoming(text=X)` это `add(question=X)`.

    Различались они по-настоящему, пока в `put` стояло поглощение. Его сняли —
    и двери сошлись слово в слово: по 35 строк кода, расхождения в именах
    доводов. Цена разделения измерена: `said_at` и переезд ключа на части
    пришлось вносить **дважды**, по одному и тому же доводу.

    ⚠ Проверяется **совпадение строк**, а не то, что код похож: похожесть
    разойдётся молча, а совпадение записи — нет.
    """

    @staticmethod
    def _shape(row: dict) -> dict:
        """Строка без того, что заведомо своё у каждой записи."""
        return {k: v for k, v in row.items()
                if k not in ('id', 'source_uid', 'question_at', 'answer_at')}

    async def test_a_reply_lands_the_same_either_way(self, sides):
        """Та же строка, каким бы из двух способов её ни положили."""
        from src.tool.companion.companion_session import (
            companion_session_incoming)

        await companion_session_put(**sides, question='он написал',
                                    source_uid='one:put')
        await companion_session_incoming(**sides, text='он написал',
                                         source_uid='one:in')

        rows = await _rows(_owner(sides))

        assert len(rows) == 2
        assert self._shape(rows[0]) == self._shape(rows[1]), (
            'две двери пишут разные строки — сливать их было нельзя')

    async def test_both_roads_reach_the_same_pair(self, sides):
        """⚠ И под один ключ: иначе пара расщепилась бы надвое."""
        from src.tool.companion.companion_session import (
            companion_session_incoming)

        await companion_session_incoming(**sides, text='его слова',
                                         source_uid='one:k1')
        await companion_session_put(**sides, answer='наши слова',
                                    source_uid='one:k2')

        assert len(await _rows(_owner(sides))) == 2


class TestTheIdComesBackForLaterDelivery:
    """⚠⚠ `id` возвращается **и при повторе** — на нём держится отметка
    доставки задним числом.

    Положили недоставленным, запомнили номер, а когда дошло — пометили.
    Верни дверь ноль на повторе, номер потерялся бы, и отметить стало бы
    нечем.
    """

    async def test_a_new_row_answers_with_its_number(self, sides):
        got = await companion_session_put(**sides, answer='ушло потом',
                                          source_uid='id:1')

        assert got['saved'] == 1 and got['id'] > 0
        assert int((await _rows(_owner(sides)))[0]['id']) == int(got['id'])

    async def test_a_repeat_answers_with_the_same_number(self, sides):
        first = await companion_session_put(**sides, answer='ушло потом',
                                            source_uid='id:2')
        again = await companion_session_put(**sides, answer='ушло потом',
                                            source_uid='id:2')

        assert again['saved'] == 0, 'повтор положил вторую строку'
        assert int(again['id']) == int(first['id']), (
            'повтор не назвал номер уже записанной строки — отмечать нечем')

    async def test_undelivered_can_be_marked_later(self, sides):
        """Сквозной путь из спеки: положили без отметки → пометили по номеру."""
        from src.tool.companion.companion_session import (
            companion_session_delivered)

        got = await companion_session_put(**sides, answer='дойдёт позже',
                                          source_uid='id:3', delivered=False)

        assert (await _rows(_owner(sides)))[0]['delivered_at'] is None

        marked = await companion_session_delivered(int(got['id']))

        assert marked['marked'] == 1, marked.get('why')
        assert (await _rows(_owner(sides)))[0]['delivered_at'] is not None
