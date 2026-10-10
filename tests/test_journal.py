"""Журнал ошибок установки — `/api/journal` и запись через обработчик логгера.

Проверяется то, ради чего журнал заведён:

* ошибка, записанная кодом, видна через ручку;
* повтор той же ошибки **не заводит вторую строку**, а увеличивает счётчик —
  ради этого и считается отпечаток;
* меняющиеся числа в тексте отпечаток не разводят;
* запись на уровне ERROR попадает в журнал сама, через обработчик корневого
  логгера, — то есть новый код не должен ничего знать про журнал.

⚠ Текст ошибки здесь всегда с меткой `JOURNAL_TEST_MARK`, а источник — свой
(`pytest`): сюита ходит в общую базу установки, и чистка «по всему журналу»
снесла бы живые записи.
"""
import logging
import uuid
from typing import AsyncGenerator

import httpx
import pytest

from tests.conftest import BASE_URL
from tests.constants import TEST_AUTH

from journal_.journal_key import journal_key
from dashboard.src.page.journal.journal_store import journal_store_write
from dashboard.src.page.journal.journal_install import journal_install_here, journal_install_remove

pytestmark = pytest.mark.core

# Метка тестовых записей: по ней тесты находят своё.
JOURNAL_TEST_MARK = 'pytest_journal'

# Источник тестовых записей. Не из `JOURNAL_STORE_SOURCES`: так тестовые строки не
# смешиваются с настоящими ни в отборе по процессу, ни на глаз.
JOURNAL_TEST_SOURCE = 'pytest'


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as session:
        await session.post('/auth/login', json=TEST_AUTH)
        yield session
        await session.delete(f'/api/journal?source={JOURNAL_TEST_SOURCE}')


class TestJournalAuth:
    """Журнал закрыт: он показывает пути файлов и трассировки."""

    async def test_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as anon:
            response = await anon.get('/api/journal')
            assert response.status_code in (401, 403)

    async def test_clear_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as anon:
            response = await anon.delete('/api/journal')
            assert response.status_code in (401, 403)


class TestJournalContract:
    """Форма ответа: её читает страница «Журнал» (/admin/journal)."""

    async def test_list_shape(self, client: httpx.AsyncClient):
        response = await client.get('/api/journal')
        assert response.status_code == 200

        result = response.json()['result']
        assert isinstance(result['rows'], list)
        for field in ('total', 'page', 'pages', 'sources'):
            assert field in result

    async def test_sources_come_from_server(self, client: httpx.AsyncClient):
        """⚠ Подписи процессов отдаёт сервер: своей копии страница не держит."""
        result = (await client.get('/api/journal')).json()['result']
        assert 'uvicorn' in result['sources']
        assert result['sources']['uvicorn']


class TestJournalWrite:
    """Запись и чтение: то, ради чего таблица заведена."""

    async def test_written_error_is_visible(self, client: httpx.AsyncClient):
        message = f'{JOURNAL_TEST_MARK}: {uuid.uuid4()}'
        journal_store_write(JOURNAL_TEST_SOURCE, message, logger_name='tests')

        result = (await client.get(f'/api/journal?q={JOURNAL_TEST_MARK}')).json()['result']
        found = [row for row in result['rows'] if row['message'] == message]

        assert len(found) == 1
        assert found[0]['source'] == JOURNAL_TEST_SOURCE
        assert found[0]['hits'] == 1

    async def test_repeat_counts_instead_of_new_row(self, client: httpx.AsyncClient):
        """⚠ Главное свойство журнала: зациклившаяся ошибка — строка со счётчиком."""
        message = f'{JOURNAL_TEST_MARK}: повтор {uuid.uuid4()}'
        for _ in range(3):
            journal_store_write(JOURNAL_TEST_SOURCE, message, logger_name='tests')

        rows = await _rows(client, message)

        assert len(rows) == 1
        assert rows[0]['hits'] == 3
        assert rows[0]['last_at'] >= rows[0]['first_at']

    async def test_deleted_row_disappears(self, client: httpx.AsyncClient):
        message = f'{JOURNAL_TEST_MARK}: на удаление {uuid.uuid4()}'
        journal_store_write(JOURNAL_TEST_SOURCE, message, logger_name='tests')

        rows = await _rows(client, message)
        assert len(rows) == 1

        response = await client.delete(f'/api/journal/{rows[0]["id"]}')
        assert response.status_code == 200
        assert response.json()['result']['deleted'] == 1

        assert not await _rows(client, message)


class TestJournalFingerprint:
    """Отпечаток решает, что считать «той же самой ошибкой».

    ⚠ Сама функция — в общем слое (`journal_key`), а проверки остались
    здесь: они стерегут **поведение**, на которое опирается наш журнал, и
    у слоя своих проверок нет.
    """

    def test_changing_numbers_do_not_split_rows(self):
        """«Задача 5219 не найдена» и «задача 5220 не найдена» — одна ошибка."""
        first = journal_key('worker', 'tests', message='задача 5219 не найдена')
        second = journal_key('worker', 'tests', message='задача 5220 не найдена')

        assert first == second

    def test_different_text_splits_rows(self):
        first = journal_key('worker', 'tests', message='задача не найдена')
        second = journal_key('worker', 'tests', message='агент не найден')

        assert first != second

    def test_traceback_tail_does_not_split_rows(self):
        """⚠ Отпечаток считается по первой строке: адреса в трассировке плавают."""
        first = journal_key('worker', 'tests', message='сбой\nFile "a.py", line 1')
        second = journal_key('worker', 'tests', message='сбой\nFile "b.py", line 2')

        assert first == second

    def test_source_splits_rows(self):
        """Одна ошибка у воркера и у сервера — разные строки: чинят разное."""
        first = journal_key('worker', 'tests', message='нет соединения')
        second = journal_key('uvicorn', 'tests', message='нет соединения')

        assert first != second


class TestJournalHandler:
    """⚠ Ошибка попадает в журнал сама — код о журнале ничего не знает."""

    async def test_logged_error_reaches_journal(self, client: httpx.AsyncClient):
        message = f'{JOURNAL_TEST_MARK}: через логгер {uuid.uuid4()}'

        journal_install_here(JOURNAL_TEST_SOURCE)
        try:
            logging.getLogger('tests.journal').error(message)
        finally:
            journal_install_remove()

        rows = await _rows(client, message)

        assert len(rows) == 1
        assert rows[0]['logger'] == 'tests.journal'
        assert rows[0]['level'] == 'ERROR'

    async def test_exception_brings_traceback_and_place(self, client: httpx.AsyncClient):
        """Трассировка и место падения — то, ради чего в журнал вообще смотрят."""
        message = f'{JOURNAL_TEST_MARK}: с исключением {uuid.uuid4()}'

        journal_install_here(JOURNAL_TEST_SOURCE)
        try:
            try:
                {}['нет такого ключа']
            except KeyError:
                logging.getLogger('tests.journal').exception(message)
        finally:
            journal_install_remove()

        rows = await _rows(client, message)

        assert len(rows) == 1
        assert 'KeyError' in (rows[0]['traceback'] or '')
        assert rows[0]['context']['file'].endswith('test_journal.py')

    async def test_warning_stays_out(self, client: httpx.AsyncClient):
        """⚠ Ниже ERROR в журнал не попадает: WARNING значит «странно, но работаем»."""
        message = f'{JOURNAL_TEST_MARK}: предупреждение {uuid.uuid4()}'

        journal_install_here(JOURNAL_TEST_SOURCE)
        try:
            logging.getLogger('tests.journal').warning(message)
        finally:
            journal_install_remove()

        assert not await _rows(client, message)


# ── Приватное ────────────────────────────────────────────────────────────────


async def _rows(client: httpx.AsyncClient, message: str) -> list[dict]:
    """Строки журнала по тексту — через ручку, а не напрямую в базу.

    ⚠ Прямой вызов `journal_store_rows` из теста падает на втором тесте: пул
    aiomysql привязан к циклу событий, в котором заведён, а pytest-asyncio даёт
    каждому тесту новый цикл — второй тест получает пул с закрытым циклом.
    Запись (`journal_store_write`) этим не страдает: она синхронная, своим
    соединением.
    """
    params = {'source': JOURNAL_TEST_SOURCE, 'q': message}
    response = await client.get('/api/journal', params=params)
    assert response.status_code == 200

    return response.json()['result']['rows']
