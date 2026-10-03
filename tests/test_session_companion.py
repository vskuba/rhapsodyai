"""Вкладка «Чат» страницы «Сессии»: ручки разговоров пары.

Что здесь стережётся — отличия от соседней ручки (`test_session.py`), ради
которых разговоры и читаются отдельно:

* разговор опознаётся **тройкой** (наша сторона, собеседник, канал): чат и
  почта одной пары не сливаются в одну строку;
* **неподтверждённый ответ показывается** — в отличие от ленты, которую
  получает агент (`companion_session_rows` его прячет). «Что сочинили, но не
  отправили» и есть вопрос, с которым на страницу приходят;
* отбор «не доставлено» смотрит на **нашу половину**: строка без ответа не
  может быть недоставленной.

⚠ Данные заводит сам тест, инструментом (`companion_session_add`), а не ищет в
базе: на пустой установке искать нечего, а на живой числа меняются от прогона
к прогону.

⚠ В базу ходим драйвером, а не `docker exec`: образец и фикстура
`db_pool_release` — `tests/test_companion_session_delivered.py`.

⚠ Гостевой клиент для проверки 401 — свой и БЕЗ общего транспорта
(`http_pool_transport`): его `aclose()` унёс бы транспорт у всех, кто ещё
работает (довод целиком — у фикстуры `client` в `conftest.py`). Образец —
`tests/test_companion.py`.
"""
import uuid

import pytest
import httpx

from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.tool.companion.companion_session import (companion_session_add,
                                                  companion_session_delivered,
                                                  companion_session_history)
from tests.conftest import BASE_URL

pytestmark = pytest.mark.auth


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой."""
    yield
    await mysql_pool_close()


@pytest.fixture
async def talk():
    """Разговор одной пары: три обмена чатом и один письмом. Убирает за собой.

    Расклад подобран так, чтобы различать отборы:

        чат  q1 / a1  доставлено      — обычный обмен
        чат  q2 / a2  НЕ доставлено   — сочинили, но не отправили
        чат  q3 / —                   — он написал, мы смолчали
        почта m1 / m2 доставлено      — другой канал той же пары
    """
    mark = uuid.uuid4().hex[:8]
    owner_key, companion_key = f'own_{mark}', f'him_{mark}'

    first = await companion_session_add(owner_key, companion_key,
                                        question='q1', answer='a1')
    await companion_session_delivered(int(first['id']))
    await companion_session_add(owner_key, companion_key,
                                question='q2', answer='a2')
    await companion_session_add(owner_key, companion_key, question='q3')
    mail = await companion_session_add(owner_key, companion_key, question='m1',
                                       answer='m2', kind='mail')
    await companion_session_delivered(int(mail['id']))

    async with mysql_get_db_async() as db:
        await db.execute('SELECT `id`, `unique_id` FROM `companion`'
                         ' WHERE `unique_id` IN (%s, %s)',
                         (owner_key, companion_key))
        rows = {row['unique_id']: row['id'] for row in await db.fetchall()}

    # Ключи отдаём вместе с номерами: номера нужны ручкам страницы, ключи —
    # инструменту, когда тест дописывает в тот же разговор свой обмен.
    yield {'owner_id': rows[owner_key], 'companion_id': rows[companion_key],
           'owner_key': owner_key, 'companion_key': companion_key}

    async with mysql_get_db_async() as db:
        await db.execute(
            'DELETE s FROM `companion_session` s'
            ' JOIN `companion` c ON c.`id` = s.`owner_id`'
            ' WHERE c.`unique_id` = %s', (owner_key,))
        await db.execute('DELETE FROM `companion` WHERE `unique_id` IN (%s, %s)',
                         (owner_key, companion_key))
        await db.connection.commit()


class TestAuth:
    async def test_endpoints_require_auth(self):
        """Без входа — 401 на всех ручках, а не пустой список.

        ⚠ Удаление в списке обязательно: ручка разрушающая, и «гостю отвечаем
        пустым списком» для неё означало бы «гость удаляет».
        """
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as guest:
            assert (await guest.get('/session/companion/kind/list')).status_code == 401
            assert (await guest.post('/session/companion/list',
                                     json={})).status_code == 401
            assert (await guest.post('/session/companion/messages',
                                     json={'owner_id': 1,
                                           'companion_id': 2})).status_code == 401
            assert (await guest.delete(
                '/session/companion/1/answer')).status_code == 401


class TestKindList:
    async def test_kinds_are_the_enum(self, client):
        """Каналы — оба значения столбца, а не те, что встретились в данных."""
        response = await client.get('/session/companion/kind/list')

        assert response.status_code == 200
        assert response.json()['result'] == ['chat', 'mail']


class TestPairList:
    async def test_channels_do_not_merge(self, client, talk):
        """⚠⚠ Разговор — тройка: чат и почта одной пары идут строками врозь."""
        rows = await _pairs(client, {'owner_id': talk['owner_id']})

        assert sorted(row['kind'] for row in rows) == ['chat', 'mail']

    async def test_counters(self, client, talk):
        """Счётчики считают половины, а не строки: три обмена, два ответа."""
        rows = await _pairs(client, {'owner_id': talk['owner_id'], 'kind': 'chat'})

        assert len(rows) == 1
        assert rows[0]['exchange_count'] == 3
        assert rows[0]['question_count'] == 3
        assert rows[0]['answer_count'] == 2
        assert rows[0]['undelivered_count'] == 1

    async def test_keys_of_both_sides_are_returned(self, client, talk):
        """Ключи сторон приходят с выдачей: заголовки записей не уникальны."""
        rows = await _pairs(client, {'owner_id': talk['owner_id'], 'kind': 'chat'})

        assert rows[0]['owner_unique_id']
        assert rows[0]['companion_unique_id']

    async def test_delivered_filter_narrows_counters(self, client, talk):
        """⚠ Отбор «не доставлено» — это НАША половина без отметки.

        Строка `q3` ответа не имеет вовсе и под отбор не попадает: отметки у
        неё нет и быть не может, а в «не доставлено» она читалась бы как
        потерянная реплика.
        """
        rows = await _pairs(client, {'owner_id': talk['owner_id'], 'kind': 'chat',
                                     'delivered': 'no'})

        assert len(rows) == 1
        assert rows[0]['exchange_count'] == 1

    async def test_unknown_kind_is_not_a_filter(self, client, talk):
        """Незнакомый канал — «любой», а не 422: отбор это удобство чтения."""
        rows = await _pairs(client, {'owner_id': talk['owner_id'], 'kind': 'bogus'})

        assert len(rows) == 2


class TestExchanges:
    async def test_order_is_chronological(self, client, talk):
        """Берём последние, отдаём по возрастанию — диалог читают сверху вниз."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})

        assert [row['question'] for row in rows] == ['q1', 'q2', 'q3']

    async def test_undelivered_answer_is_visible(self, client, talk):
        """⚠⚠ Неподтверждённый ответ показан — ради этого вкладка и нужна.

        Лента агента (`companion_session_rows`) его прячет: продолжать
        несказанное нельзя. Человеку наоборот — это главный вопрос.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        second = [row for row in rows if row['question'] == 'q2'][0]

        assert second['answer'] == 'a2'
        assert second['delivered_at'] is None

    async def test_limit_takes_the_tail(self, client, talk):
        """Предел отрезает начало разговора, а не конец."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat', 'limit': 1})

        assert [row['question'] for row in rows] == ['q3']

    async def test_channel_does_not_leak(self, client, talk):
        """Письма не подмешиваются в чат: канал разговора — часть ключа."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'mail'})

        assert [row['question'] for row in rows] == ['m1']

    async def test_delivered_filter(self, client, talk):
        """Отбор доставки работает и внутри разговора, тем же условием."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat', 'delivered': 'no'})

        assert [row['question'] for row in rows] == ['q2']


class TestAnswerDelete:
    """Чип «удалить» в хвосте нашей половины: убрать НАШ ответ.

    ⚠⚠ Стережётся здесь два разных обещания, и оба легко потерять правкой:

    * **его слова остаются** — строка в таблице это обмен, обе половины лежат в
      её колонках, и `DELETE` строки стёр бы заодно реплику собеседника;
    * **наш текст остаётся в базе** — убирается видимость (`answer_deleted_at`),
      а не содержимое: решение «ответ лишний» принимает человек и может
      ошибиться.

    Из второго следует третье, и оно тонкое: читатели расходятся. Лента агента
    убранного не знает вовсе, а страница знает — рисует «было удалено» и даёт
    текст подсказкой: человек разбирается в своей же правке. Здесь проверяются
    обе стороны этого расхождения.
    """

    async def test_question_survives(self, client, talk):
        """Его реплика на месте, нашего ответа в `answer` страница не даёт."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        response = await client.delete(f'/session/companion/{first["id"]}/answer')

        assert response.status_code == 200
        assert response.json()['result']['answer_deleted_at']

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        same = [row for row in left if row['id'] == first['id']][0]

        assert same['question'] == 'q1'
        assert same['answer'] == ''
        assert same['delivered_at'] is None

    async def test_page_gets_the_text_for_the_tooltip(self, client, talk):
        """⚠⚠ Страница получает убранный текст — отдельным полем.

        На его месте в ленте стоит «было удалено», а сам текст показывается
        подсказкой. В `answer` его класть нельзя: по этому полю страница судит
        «ответ есть», и убранный снова выглядел бы сказанным — с чипом доставки
        и чипом удаления.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        same = [row for row in left if row['id'] == first['id']][0]

        assert same['answer'] == ''
        assert same['answer_deleted_text'] == 'a1'
        assert same['answer_deleted_at']

    async def test_live_answer_has_no_deleted_fields(self, client, talk):
        """У живого ответа поля пометки пусты — иначе лента метила бы всё."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        assert first['answer'] == 'a1'
        assert first['answer_deleted_at'] is None
        assert first['answer_deleted_text'] == ''

    async def test_text_stays_in_the_table(self, client, talk):
        """⚠⚠ В базе текст цел — стирается видимость, а не содержимое."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        async with mysql_get_db_async() as db:
            await db.execute('SELECT `answer`, `answer_at`, `delivered_at`,'
                             ' `answer_deleted_at` FROM `companion_session`'
                             ' WHERE `id` = %s', (first['id'],))
            stored = await db.fetchone()

        assert stored['answer'] == 'a1'
        assert stored['answer_at'] is not None
        assert stored['delivered_at'] is not None
        assert stored['answer_deleted_at'] is not None

    async def test_prompt_feed_forgets_it(self, client, talk):
        """⚠⚠ Лента в промпт агента убранного ответа не знает.

        Ради этого отметка и заведена: пока ответ в ленте, модель продолжает
        разговор от сказанного по ошибке. Страница и промпт обязаны
        договариваться — проверяем именно `companion_session_rows`, а не только
        ручку.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        before = await companion_session_history(talk['owner_key'],
                                                 talk['companion_key'])

        assert 'a1' in before

        await client.delete(f'/session/companion/{first["id"]}/answer')

        after = await companion_session_history(talk['owner_key'],
                                                talk['companion_key'])

        assert 'a1' not in after
        # Его реплика остаётся и в промпте: убрали нашу половину, не обмен.
        assert 'q1' in after

    async def test_neighbours_survive(self, client, talk):
        """Соседние обмены разговора не трогаются.

        Берём средний (`q2`): правка первого или последнего прошла бы и при
        ошибке в условии — «задели всё до/после».
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        second = [row for row in rows if row['question'] == 'q2'][0]

        await client.delete(f'/session/companion/{second["id"]}/answer')

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})

        assert [row['question'] for row in left] == ['q1', 'q2', 'q3']
        assert [row['answer'] for row in left] == ['a1', '', '']

    async def test_other_channel_untouched(self, client, talk):
        """Письмо той же пары не трогается: правится строка, а не разговор."""
        chat = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})

        await client.delete(f'/session/companion/{chat[0]["id"]}/answer')

        mail = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'mail'})

        assert [(row['question'], row['answer']) for row in mail] == [('m1', 'm2')]

    async def test_row_without_question_stays_on_the_page(self, client, talk):
        """⚠ Обмен без его реплики со страницы НЕ пропадает.

        Инвайт, письмо, инициатива: наш ответ — вся строка. Показывать в ней
        всё равно есть что — пометку «было удалено»; исчезай такие строки,
        человек видел бы одну свою правку пометкой, а другую пропажей строки.

        Из промпта она при этом уходит целиком: там пометок не рисуют.
        """
        alone = await companion_session_add(talk['owner_key'],
                                            talk['companion_key'],
                                            answer='наш инвайт')
        await companion_session_delivered(int(alone['id']))

        response = await client.delete(f'/session/companion/{alone["id"]}/answer')

        assert response.status_code == 200

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        same = [row for row in left if row['id'] == int(alone['id'])]

        assert len(same) == 1
        assert same[0]['answer_deleted_text'] == 'наш инвайт'

        feed = await companion_session_history(talk['owner_key'],
                                               talk['companion_key'])

        assert 'наш инвайт' not in feed

    async def test_counters_drop_the_hidden_answer(self, client, talk):
        """Счётчики разговора считают видимое: ответов стало меньше.

        Иначе «наших ответов 2» стояло бы над лентой, в которой их один, —
        и человек искал бы пропажу.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        pairs = await _pairs(client, {'owner_id': talk['owner_id'],
                                      'kind': 'chat'})

        assert pairs[0]['exchange_count'] == 3
        assert pairs[0]['question_count'] == 3
        assert pairs[0]['answer_count'] == 1

    async def test_missing_row_is_404(self, client):
        """Нет такой строки — 404, а не «убрано ноль»."""
        response = await client.delete('/session/companion/2147483647/answer')

        assert response.status_code == 404

    async def test_without_answer_is_404(self, client, talk):
        """Нечего убирать (он написал, мы смолчали) — тоже 404."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        silent = [row for row in rows if row['question'] == 'q3'][0]

        response = await client.delete(f'/session/companion/{silent["id"]}/answer')

        assert response.status_code == 404

    async def test_second_time_is_404(self, client, talk):
        """Повторное нажатие — 404: убирать уже нечего.

        «Ноль, и всё хорошо» означало бы, что нажатие по уже убранному ответу
        выглядит как новая работа.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        assert (await client.delete(
            f'/session/companion/{first["id"]}/answer')).status_code == 200
        assert (await client.delete(
            f'/session/companion/{first["id"]}/answer')).status_code == 404


async def _pairs(client, body):
    """Разговоры по отбору — ответ ручки списком."""
    response = await client.post('/session/companion/list', json=body)

    assert response.status_code == 200

    return response.json()['result']


async def _exchanges(client, body):
    """Обмены разговора — ответ ручки списком."""
    response = await client.post('/session/companion/messages', json=body)

    assert response.status_code == 200

    return response.json()['result']
