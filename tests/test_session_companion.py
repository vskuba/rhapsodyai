"""Вкладка «Чат» страницы «Сессии»: ручки разговоров пары.

Что здесь стережётся — отличия от соседней ручки (`test_session.py`), ради
которых разговоры и читаются отдельно:

* разговор опознаётся **тройкой** (наша сторона, собеседник, канал): чат и
  почта одной пары не сливаются в одну строку;
* **неподтверждённый ответ показывается** — в отличие от ленты, которую
  получает агент (`companion_session_rows` его прячет). «Что сочинили, но не
  отправили» и есть вопрос, с которым на страницу приходят;
* отбор «не доставлено» смотрит на **нашу половину**: строка без ответа не
  может быть недоставленной;
* **отбор не прячет строк** — убранный нами ответ не выносит из выдачи обмен, в
  котором лежит настоящая реплика собеседника (`TestDeletedUnderDeliveredFilter`,
  там же беда, из-за которой класс написан).

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
            assert (await guest.post('/session/companion/answer/delete',
                                     json={'ids': [1]})).status_code == 401


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
        # ⚠⚠ `delivered_at` остаётся, в отличие от текста и времени сочинения:
        # отметка о доставке — запись о случившемся, собеседник ответ получил, и
        # наша правка убрала его из памяти агента, а не с его экрана. Обнули её —
        # и обмен, найденный отбором «Доставлен», приходил бы без единого следа
        # доставки, то есть страница не могла бы объяснить, почему он в выдаче.
        assert same['delivered_at'] is not None

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


class TestDeletedUnderDeliveredFilter:
    """⚠⚠ Отбор по доставке не имеет права прятать обмен с убранным ответом.

    Беда, из-за которой класс написан: в `_delivered_condition` стояло
    `AND answer_deleted_at IS NULL`, и под отбором «Доставлен» обмен с убранным
    ответом исчезал **строкой целиком** — вместе с вопросом собеседника. Тот
    вопрос настоящий, он был доставлен, и к нашей правке отношения не имеет:
    убирали мы свою половину.

    Условие было написано по доводу «убранного на странице нет, незачем его и
    отбирать», и довод неверен дважды. Отметка ничего не отменяет в прошлом —
    ответ был доставлен, собеседник его прочёл; и условие про НАШУ половину,
    применённое к строке, выкидывает заодно его половину.

    ⚠ Поэтому здесь проверяется не формулировка условия, а то, что видно
    человеку: строка под «Доставлен» на месте, его слова целы, пометка и текст
    подсказки при ней.
    """

    async def test_delivered_filter_keeps_the_question(self, client, talk):
        """Под «Доставлен» обмен остаётся, и его реплика вместе с ним."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat', 'delivered': 'yes'})
        same = [row for row in left if row['id'] == first['id']]

        assert len(same) == 1, 'обмен с убранным ответом выпал из «Доставлен»'
        assert same[0]['question'] == 'q1'
        assert same[0]['answer'] == ''
        assert same[0]['answer_deleted_text'] == 'a1'
        assert same[0]['delivered_at'] is not None

    async def test_delivered_filter_keeps_a_row_without_question(self, client,
                                                                 talk):
        """⚠⚠ И обмен, где убранный ответ был ВСЕЙ строкой, тоже остаётся.

        Инвайт, письмо, инициатива — две трети строк установки. Показывать в
        такой строке после правки нечего, кроме пометки, — и именно поэтому её
        нельзя прятать: иначе «сколько доставленного мы убрали» не видно ничем,
        строка просто исчезает из разговора.
        """
        alone = await companion_session_add(talk['owner_key'],
                                            talk['companion_key'],
                                            answer='наш инвайт')
        await companion_session_delivered(int(alone['id']))
        await client.delete(f'/session/companion/{alone["id"]}/answer')

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat', 'delivered': 'yes'})
        same = [row for row in left if row['id'] == int(alone['id'])]

        assert len(same) == 1
        assert same[0]['question'] == ''
        assert same[0]['answer_deleted_text'] == 'наш инвайт'
        assert same[0]['delivered_at'] is not None

    async def test_undelivered_filter_does_not_claim_it(self, client, talk):
        """В «Не доставлено» убранный доставленный ответ не попадает.

        Иначе отбор читался бы упрёком: ответ как раз доставлен, и убрали его
        ровно потому, что собеседник его получил.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat', 'delivered': 'no'})

        assert [row['question'] for row in left] == ['q2']

    async def test_undelivered_filter_keeps_the_undelivered_one(self, client,
                                                                talk):
        """А сочинённый и не отправленный — остаётся в «Не доставлено».

        Отбор отвечает про `delivered_at`, и отметка «убрано» этого ответа не
        меняет: отправлен он так и не был.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        second = [row for row in rows if row['question'] == 'q2'][0]

        await client.delete(f'/session/companion/{second["id"]}/answer')

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat', 'delivered': 'no'})
        same = [row for row in left if row['id'] == second['id']]

        assert len(same) == 1
        assert same[0]['answer_deleted_text'] == 'a2'

    async def test_pair_list_keeps_the_talk(self, client, talk):
        """Разговор не пропадает из списка, даже если убрали всё доставленное.

        Разговор с одним доставленным обменом: убрали ответ — и список под
        «Доставлен» обязан его показать. Пропади он, человек решил бы, что
        правкой снёс переписку.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        pairs = await _pairs(client, {'owner_id': talk['owner_id'],
                                      'kind': 'chat', 'delivered': 'yes'})

        assert len(pairs) == 1
        assert pairs[0]['exchange_count'] == 1

    async def test_deleted_count_answers_how_many(self, client, talk):
        """`deleted_count` считает убранное — под тем же отбором, что соседи.

        Под «Доставлен» это и есть ответ на «сколько доставленного мы убрали»:
        вопрос, из-за которого отметку и перестали прятать из отбора.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]
        second = [row for row in rows if row['question'] == 'q2'][0]

        before = await _pairs(client, {'owner_id': talk['owner_id'],
                                       'kind': 'chat'})

        assert before[0]['deleted_count'] == 0

        await client.delete(f'/session/companion/{first["id"]}/answer')
        await client.delete(f'/session/companion/{second["id"]}/answer')

        both = await _pairs(client, {'owner_id': talk['owner_id'],
                                     'kind': 'chat'})

        assert both[0]['deleted_count'] == 2

        # Доставлен был только первый — отбор отделяет один от другого.
        delivered = await _pairs(client, {'owner_id': talk['owner_id'],
                                          'kind': 'chat', 'delivered': 'yes'})

        assert delivered[0]['deleted_count'] == 1

    async def test_prompt_feed_still_forgets_it(self, client, talk):
        """⚠⚠ Послабление отбора НЕ протекло в ленту агента.

        Страница показывает убранное, модель — нет, и это ровно то расхождение,
        ради которого отметка заведена. Правка отбора на странице обязана
        оставить ленту в покое; проверяем после правки, а не вместо неё.
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        first = [row for row in rows if row['question'] == 'q1'][0]

        await client.delete(f'/session/companion/{first["id"]}/answer')

        feed = await companion_session_history(talk['owner_key'],
                                               talk['companion_key'])

        assert 'a1' not in feed
        assert 'q1' in feed


class TestAnswerDeleteMany:
    """Кнопка «Удалить все»: та же правка пачкой по списку номеров.

    ⚠⚠ Стережётся здесь то же, что у поштучной, плюс обещание самой пачки:
    **она не делает ничего нового**. Уходят наши ответы перечисленных обменов,
    реплики собеседника остаются все, тексты остаются в базе, соседний канал не
    трогается. Разойдись пачка с поштучной хоть одним условием — и «убрал всё
    кнопкой» значило бы не то же самое, что «нащёлкал чипами».

    ⚠ Отдельно стережётся ответ числами, а не `404`: пропуски здесь обычны
    (обмен без ответа, уже убранный), и отказ всей пачке из-за одного такого
    заставил бы страницу повторять отбор сервера.
    """

    async def test_two_answers_go_at_once(self, client, talk):
        """Два обмена одним запросом: ответов нет, вопросы на месте."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        ids = [row['id'] for row in rows if row['answer']]

        assert len(ids) == 2

        response = await client.post('/session/companion/answer/delete',
                                     json={'ids': ids})

        assert response.status_code == 200
        assert response.json()['result'] == {'deleted': 2, 'skipped': 0}

        left = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})

        assert [row['answer'] for row in left] == ['', '', '']
        assert sorted(row['question'] for row in left) == ['q1', 'q2', 'q3']
        # Текст убранного приходит отдельным полем — тем же, что у поштучной:
        # страница рисует «было удалено» и кладёт его в подсказку.
        assert sorted(row['answer_deleted_text'] for row in left) \
            == ['', 'a1', 'a2']

    async def test_text_stays_in_the_table(self, client, talk):
        """⚠⚠ В базе тексты целы — у пачки стирается та же видимость."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        ids = [row['id'] for row in rows if row['answer']]

        await client.post('/session/companion/answer/delete', json={'ids': ids})

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `answer`, `answer_deleted_at` FROM `companion_session`'
                f' WHERE `id` IN ({", ".join(["%s"] * len(ids))})', tuple(ids))
            stored = await db.fetchall()

        assert sorted(row['answer'] for row in stored) == ['a1', 'a2']
        assert all(row['answer_deleted_at'] is not None for row in stored)

    async def test_prompt_feed_forgets_them(self, client, talk):
        """⚠⚠ Лента в промпт агента не знает ни одного из убранных пачкой.

        Ради этого отметка и заведена. Пачка ставит её одним `UPDATE`, и забыть
        в нём условие — это «на странице ответов нет, а модель их помнит».
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        ids = [row['id'] for row in rows if row['answer']]

        await client.post('/session/companion/answer/delete', json={'ids': ids})

        feed = await companion_session_history(talk['owner_key'],
                                               talk['companion_key'])

        assert 'a1' not in feed
        assert 'a2' not in feed
        assert 'q1' in feed

    async def test_other_channel_untouched(self, client, talk):
        """Почта той же пары не трогается: в пачке только показанные номера."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})

        await client.post('/session/companion/answer/delete',
                          json={'ids': [row['id'] for row in rows
                                        if row['answer']]})

        mail = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'mail'})

        assert [row['answer'] for row in mail] == ['m2']

    async def test_skipped_are_counted_not_refused(self, client, talk):
        """⚠⚠ Уже убранный и обмен без ответа — число `skipped`, а не отказ.

        Повторное нажатие кнопки — обычное дело (лента перечиталась, человек
        нажал ещё раз), и `404` всей пачке из-за одной такой строки означал бы
        «кнопка сломалась».
        """
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        answered = [row['id'] for row in rows if row['answer']]
        silent = [row['id'] for row in rows if not row['answer']]

        await client.delete(f'/session/companion/{answered[0]}/answer')

        response = await client.post('/session/companion/answer/delete',
                                     json={'ids': answered + silent})

        assert response.status_code == 200
        # Лёг один: первый уже убран поштучно, у третьего ответа нет вовсе.
        assert response.json()['result'] == {'deleted': 1, 'skipped': 2}

    async def test_repeat_deletes_nothing(self, client, talk):
        """Повтор той же пачки — `deleted: 0`: отметка не переставляется."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})
        ids = [row['id'] for row in rows if row['answer']]

        await client.post('/session/companion/answer/delete', json={'ids': ids})

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `answer_deleted_at` FROM `companion_session`'
                ' WHERE `id` = %s', (ids[0],))
            first = (await db.fetchone())['answer_deleted_at']

        response = await client.post('/session/companion/answer/delete',
                                     json={'ids': ids})

        assert response.json()['result'] == {'deleted': 0, 'skipped': 2}

        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `answer_deleted_at` FROM `companion_session`'
                ' WHERE `id` = %s', (ids[0],))

            assert (await db.fetchone())['answer_deleted_at'] == first

    async def test_empty_list_is_400(self, client):
        """Пустой список — отказ, а не «убрано ноль, и всё хорошо»."""
        response = await client.post('/session/companion/answer/delete',
                                     json={'ids': []})

        assert response.status_code == 400

    async def test_counters_drop_the_hidden_answers(self, client, talk):
        """Счётчики разговора считают убранное пачкой так же, как поштучное."""
        rows = await _exchanges(client, {'owner_id': talk['owner_id'],
                                         'companion_id': talk['companion_id'],
                                         'kind': 'chat'})

        await client.post('/session/companion/answer/delete',
                          json={'ids': [row['id'] for row in rows
                                        if row['answer']]})

        pairs = await _pairs(client, {'owner_id': talk['owner_id'],
                                      'kind': 'chat'})

        assert pairs[0]['answer_count'] == 0
        assert pairs[0]['undelivered_count'] == 0
        assert pairs[0]['deleted_count'] == 2
        # ⚠ Обмены из ленты не пропадают: убрана половина, а не строка.
        assert pairs[0]['exchange_count'] == 3


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
