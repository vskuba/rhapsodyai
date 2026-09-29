"""Журнал запросов к базе — счётчик, сброс пачкой и ручка `/api/journal/mysql`.

Проверяется то, ради чего журнал заведён:

* повтор запроса **не заводит вторую строку**, а складывается в счётчики — ради
  этого и считается отпечаток вида запроса;
* меняющаяся длина списка `IN (%s, %s, …)` отпечаток не разводит;
* значения запроса доезжают, но **без секретов**;
* ответов базы в журнале нет ни в каком виде;
* значения хранятся от самого долгого прогона, а не от последнего;
* сброс не считает сам себя — иначе пачка никогда бы не опустела;
* выключатель — настройка `journal_mysql_enabled`, и работает она без
  перезапуска: сверку зовёт каждый такт сброса.

⚠ Тестовые строки заводятся с источником `pytest`, а не из `JOURNAL_SOURCES`:
сюита ходит в общую базу установки, и чистка «по всему журналу» снесла бы живые
счётчики. Та же дисциплина, что в `test_journal.py`.
"""
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import pytest

from tests.conftest import BASE_URL
from tests.constants import TEST_AUTH

pytestmark = pytest.mark.core

# Источник тестовых строк: по нему они находятся и по нему же убираются.
JOURNAL_MYSQL_TEST_SOURCE = 'pytest'

# Примета тестовых запросов в тексте — чтобы отбор не цеплял живые.
JOURNAL_MYSQL_TEST_MARK = 'pytest_journal_mysql'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после каждого теста.

    Пул модульный и привязан к циклу событий, в котором создан, а pytest-asyncio
    даёт каждому тесту свой. Та же дисциплина, что в `test_task_log.py`.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=15.0) as session:
        await session.post('/auth/login', json=TEST_AUTH)
        yield session
        await session.delete(f'/api/journal/mysql?source={JOURNAL_MYSQL_TEST_SOURCE}')


@pytest.fixture
async def counted():
    """Счётчик включён под тестовым источником и очищен до и после."""
    from mysql_.mysql_watch import mysql_watch_drain, mysql_watch_off, mysql_watch_on

    mysql_watch_drain()
    mysql_watch_on(JOURNAL_MYSQL_TEST_SOURCE)
    yield
    mysql_watch_drain()
    mysql_watch_off()


def _shape(query: str, args=None, ms: float = 1.0, rows: int = 1) -> None:
    """Записать один прогон запроса в счётчик — как это делает `mysql_.execute`."""
    from mysql_.mysql_watch import mysql_watch_note

    mysql_watch_note(query, args, ms, rows)


class TestShapeIsOneRow:
    """Строка одна на ВИД запроса: иначе шесть тысяч запросов в минуту утопят таблицу."""

    def test_same_query_counted_once(self, counted):
        """Повторы складываются в один вид, а не заводят по строке на прогон."""
        from mysql_.mysql_watch import mysql_watch_drain

        for _ in range(5):
            _shape('SELECT id FROM t WHERE a = %s', (1,), ms=2.0, rows=1)

        rows = mysql_watch_drain()

        assert len(rows) == 1, 'один и тот же запрос разошёлся по строкам'
        assert rows[0]['hits'] == 5
        assert rows[0]['total_ms'] == pytest.approx(10.0)

    def test_in_list_length_does_not_split_the_shape(self, counted):
        """
        ⚠ Число плейсхолдеров в `IN (...)` равно длине списка значений. Без
        сведения один и тот же отбор заводил бы новый вид на каждый размер
        списка — и журнал засыпало бы почти одинаковыми строками.
        """
        from mysql_.mysql_watch import mysql_watch_drain

        _shape('SELECT id FROM t WHERE a IN (%s, %s)', (1, 2))
        _shape('SELECT id FROM t WHERE a IN (%s, %s, %s, %s)', (1, 2, 3, 4))

        rows = mysql_watch_drain()

        assert len(rows) == 1, 'списки разной длины разошлись по видам'
        assert rows[0]['hits'] == 2

    def test_whitespace_does_not_split_the_shape(self, counted):
        """Запрос, склеенный из строк, и он же в одну строку — один вид."""
        from mysql_.mysql_watch import mysql_watch_drain

        _shape('SELECT id\n  FROM t\n WHERE a = %s', (1,))
        _shape('SELECT id FROM t WHERE a = %s', (1,))

        assert len(mysql_watch_drain()) == 1


class TestValuesAreKept:
    """Значения нужны — без них «WHERE id = %s» не отвечает ни на один вопрос."""

    def test_secrets_are_masked(self, counted):
        """
        ⚠ Через значения в журнал уезжает всё, чем машина авторизуется. Вырезает
        их тот же код, что чистит журнал запросов (`mysql_log_args`) — второй
        копии правил быть не должно.
        """
        from mysql_.mysql_watch import mysql_watch_drain

        _shape('UPDATE u SET name = %s, password = %s WHERE id = %s',
               ('вова', 'очень-секретный-пароль', 7))

        args = mysql_watch_drain()[0]['slow_args']

        assert 'вова' in args, 'вырезано лишнее: обычное значение должно остаться'
        assert 'очень-секретный-пароль' not in args, 'пароль уехал в журнал'

    def test_slowest_run_wins_the_values(self, counted):
        """
        Вопрос звучит «почему этот запрос **иногда** медленный», и отвечают на
        него значения того прогона, который и был медленным. Значения последнего
        к нему отношения не имеют.
        """
        from mysql_.mysql_watch import mysql_watch_drain

        _shape('SELECT id FROM t WHERE a = %s', ('медленный',), ms=500.0, rows=9)
        _shape('SELECT id FROM t WHERE a = %s', ('быстрый',), ms=1.0, rows=1)

        row = mysql_watch_drain()[0]

        assert 'медленный' in row['slow_args']
        assert row['slow_ms'] == pytest.approx(500.0)
        assert row['slow_rows'] == 9, 'строки медленного прогона заменились чужими'
        assert row['max_ms'] == pytest.approx(500.0)


class TestFlushAccumulates:
    """Сброс складывает пачку со строкой, а не перезаписывает её."""

    async def test_counters_add_up_across_batches(self, client, counted):
        """Числа копятся между сбросами: пачка приносит своё «за последние полминуты»."""
        from src.journal.journal_mysql import journal_mysql_flush

        query = f'SELECT id FROM {JOURNAL_MYSQL_TEST_MARK} WHERE a = %s'

        _shape(query, (1,), ms=10.0, rows=2)
        assert await journal_mysql_flush() == 1

        _shape(query, (2,), ms=30.0, rows=3)
        assert await journal_mysql_flush() == 1

        got = await client.get('/api/journal/mysql',
                               params={'source': JOURNAL_MYSQL_TEST_SOURCE,
                                       'q': JOURNAL_MYSQL_TEST_MARK})
        rows = got.json()['result']['rows']

        assert len(rows) == 1, 'две пачки завели две строки вместо одной'
        assert rows[0]['hits'] == 2
        assert rows[0]['total_ms'] == pytest.approx(40.0)
        assert rows[0]['total_rows'] == 5
        assert rows[0]['max_ms'] == pytest.approx(30.0)

    async def test_flush_does_not_count_itself(self, client, counted):
        """
        ⚠ Сброс ходит в базу обычными запросами. Считай он их — своя же запись
        попадала бы в следующую пачку, и та никогда бы не опустела.
        """
        from mysql_.mysql_watch import mysql_watch_drain
        from src.journal.journal_mysql import journal_mysql_flush

        _shape(f'SELECT id FROM {JOURNAL_MYSQL_TEST_MARK} WHERE a = %s', (1,))
        await journal_mysql_flush()

        assert mysql_watch_drain() == [], 'сброс насчитал сам себя'


class TestAnswersAreNotStored:
    """⚠ Ответов базы в журнале нет: только запрос, значения и числа."""

    async def test_row_carries_no_result_field(self, client, counted):
        """Ни одного поля с данными строк — единственное, что знаем, это их число."""
        from src.journal.journal_mysql import journal_mysql_flush

        _shape(f'SELECT secret_column FROM {JOURNAL_MYSQL_TEST_MARK}', None, ms=5.0, rows=42)
        await journal_mysql_flush()

        got = await client.get('/api/journal/mysql',
                               params={'source': JOURNAL_MYSQL_TEST_SOURCE,
                                       'q': JOURNAL_MYSQL_TEST_MARK})
        row = got.json()['result']['rows'][0]

        assert row['max_rows'] == 42
        assert not [key for key in row if 'result' in key or 'response' in key], \
            'в строке журнала появилось поле с ответом базы'


class TestListHandle:
    """Ручка: отбор, сортировка и итоги по всему отбору, а не по странице."""

    async def test_orders_are_a_closed_list(self, client):
        """
        Имя колонки для сортировки не должно приезжать из запроса. Неизвестный
        ключ молча превращается в умолчание, а не в кусок SQL.
        """
        from src.journal.journal_mysql import JOURNAL_MYSQL_ORDER

        got = await client.get('/api/journal/mysql',
                               params={'order': 'total_ms; DROP TABLE x'})

        assert got.status_code == 200
        assert got.json()['result']['orders'] == list(JOURNAL_MYSQL_ORDER)

    async def test_totals_cover_the_whole_selection(self, client, counted):
        """Итоги считаются по отбору целиком: страница показывает лишь верхушку."""
        from src.journal.journal_mysql import journal_mysql_flush

        for number in range(3):
            _shape(f'SELECT {number} FROM {JOURNAL_MYSQL_TEST_MARK} WHERE a = %s', (1,),
                   ms=7.0, rows=1)
        await journal_mysql_flush()

        got = await client.get('/api/journal/mysql',
                               params={'source': JOURNAL_MYSQL_TEST_SOURCE,
                                       'q': JOURNAL_MYSQL_TEST_MARK, 'per_page': 1})
        result = got.json()['result']

        assert len(result['rows']) == 1, 'страница не ограничилась размером'
        assert result['total'] == 3
        assert result['totals']['hits'] == 3
        assert result['totals']['total_ms'] == pytest.approx(21.0)


class TestSettingIsTheSwitch:
    """
    Выключатель — строка `journal_mysql_enabled` в таблице настроек, а не
    переменная окружения. Смысл именно в этом: счёт включают тогда, когда что-то
    тормозит, — то есть на живой установке и без перезапуска контейнеров.
    """

    @pytest.fixture
    async def setting_restored(self):
        """Вернуть настройке прежнее значение, чем бы тест её ни сделал."""
        from setting_.setting_ import setting_get, setting_set
        from src.journal.journal_mysql import JOURNAL_MYSQL_SETTING

        was = await setting_get(JOURNAL_MYSQL_SETTING, '1')
        yield
        await setting_set(JOURNAL_MYSQL_SETTING, was)

    async def test_switch_off_stops_counting(self, counted, setting_restored):
        """Снятая настройка гасит счёт — и сверка это замечает без перезапуска."""
        from mysql_.mysql_watch import mysql_watch_drain, mysql_watch_enabled
        from setting_.setting_ import setting_set
        from src.journal.journal_mysql import (JOURNAL_MYSQL_SETTING,
                                               journal_mysql_watch_start)

        await setting_set(JOURNAL_MYSQL_SETTING, '0')

        assert await journal_mysql_watch_start(JOURNAL_MYSQL_TEST_SOURCE) is False
        assert mysql_watch_enabled() is False

        _shape('SELECT id FROM t WHERE a = %s', (1,))

        assert mysql_watch_drain() == [], 'выключенный счётчик всё равно считает'

    async def test_switch_back_on_resumes(self, counted, setting_restored):
        """И возвращает его обратно: такт сброса зовёт ту же сверку по кругу."""
        from mysql_.mysql_watch import mysql_watch_drain
        from setting_.setting_ import setting_set
        from src.journal.journal_mysql import (JOURNAL_MYSQL_SETTING,
                                               journal_mysql_watch_start)

        await setting_set(JOURNAL_MYSQL_SETTING, '0')
        await journal_mysql_watch_start(JOURNAL_MYSQL_TEST_SOURCE)

        await setting_set(JOURNAL_MYSQL_SETTING, '1')

        assert await journal_mysql_watch_start(JOURNAL_MYSQL_TEST_SOURCE) is True

        _shape('SELECT id FROM t WHERE a = %s', (1,))

        assert len(mysql_watch_drain()) == 1, 'счёт не вернулся после включения'

    async def test_reading_the_setting_is_not_counted(self, counted):
        """
        ⚠ Свой поход за настройкой счётчику не показываем: иначе в журнале завёлся
        бы вид запроса, который делает сам журнал, — и рос бы он ровно от того,
        что журнал включён.
        """
        from mysql_.mysql_watch import mysql_watch_drain
        from src.journal.journal_mysql import journal_mysql_enabled

        await journal_mysql_enabled()

        assert mysql_watch_drain() == [], 'запрос настройки попал в журнал запросов'


class TestWatchIsCheap:
    """Счётчик обязан быть дешевле того, что считает, и не ронять вызывающего."""

    def test_broken_input_does_not_raise(self, counted):
        """Любая неудача счёта — молчаливая: иначе он ронял бы запросы приложения."""
        from mysql_.mysql_watch import mysql_watch_drain, mysql_watch_note

        mysql_watch_note(None, object(), 'не число', None)

        assert isinstance(mysql_watch_drain(), list)

    def test_shapes_have_a_ceiling(self, counted):
        """
        ⚠ Потолок на число видов — от утечки: текст запроса бывает собран по
        месту, и при неудачной сборке видов станет сколько угодно.
        """
        from mysql_.mysql_watch import MYSQL_WATCH_SHAPES_MAX, mysql_watch_drain

        for number in range(MYSQL_WATCH_SHAPES_MAX + 50):
            _shape(f'SELECT {number} FROM t')

        assert len(mysql_watch_drain()) == MYSQL_WATCH_SHAPES_MAX


class TestTimeIsUtc:
    """Время в строках — UTC, как всё в проекте: сдвигает его страница."""

    def test_marks_are_timezone_aware(self, counted):
        from mysql_.mysql_watch import mysql_watch_drain

        _shape('SELECT id FROM t')
        row = mysql_watch_drain()[0]

        assert row['first_at'].tzinfo is not None, 'время без пояса — его нечем сдвигать'
        assert row['first_at'] <= datetime.now(timezone.utc)
