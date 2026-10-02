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
                                                  companion_session_delivered)
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

    yield {'owner_id': rows[owner_key], 'companion_id': rows[companion_key]}

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
        """Без входа — 401 на всех трёх ручках, а не пустой список."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as guest:
            assert (await guest.get('/session/companion/kind/list')).status_code == 401
            assert (await guest.post('/session/companion/list',
                                     json={})).status_code == 401
            assert (await guest.post('/session/companion/messages',
                                     json={'owner_id': 1,
                                           'companion_id': 2})).status_code == 401


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
