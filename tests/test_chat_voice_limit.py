"""`/chat/voice` и `/chat/messages`: находки пентеста 2026-11-02.

Две правки под одним файлом — обе про вход `chat:ask`, обе ловятся HTTP-ом:

* **#5** `/chat/voice` складывал temp-файл в рабочий каталог (`/app`,
  смонтированный репозиторий) под именем из запроса и не убирал его при сбое
  распознавания (не было `finally`). Повтор с разными именами засорял дерево и
  заполнял диск. Теперь имя даёт `tempfile` в системном temp, уборка — в
  `finally`.

* **#6** `limit` уходил в SQL как есть: `-1` ронял запрос 500-м, гигантское
  значение тянуло из базы сколько скажут. Теперь поле зажато `1..200`, всё вне
  диапазона — 422 на входе.

⚠ Тесты требуют поднятый uvicorn на BASE_URL (маркер `integration`). Вход —
гостевой: у роли `guest` есть ровно `chat:ask`, и этого обеим точкам довольно.
"""
import os

import httpx
import pytest
from dotenv import load_dotenv

from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.auth, pytest.mark.integration]


@pytest.fixture
async def admin():
    """Полноправный клиент — им убирают тестового гостя."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=10.0) as client:
        await client.post('/auth/login', json=TEST_AUTH)
        yield client


@pytest.fixture
async def guest(admin: httpx.AsyncClient):
    """Анонимная сессия с `chat:ask` — и уборка за ней."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=30.0) as client:
        resp = await client.post('/auth/guest', json={})
        assert resp.status_code == 200, resp.text
        guest_id = resp.json()['user']['id']

        yield client

    await admin.delete(f'/api/users/{guest_id}')


class TestVoiceLeavesNoFile:
    """`/chat/voice` не роняет temp-файл в рабочий каталог.

    ⚠ Напрямую заглянуть в `/app` контейнера из HTTP-теста нечем, поэтому
    сторожим то, что видно снаружи: сбой распознавания отвечает 500 (а не
    падением процесса), то есть `finally` отработал и запрос завершился штатно.
    Отсутствие файла в `/app` проверено руками на стенде при разборе находки.
    """

    async def test_broken_audio_is_a_clean_500(self, guest: httpx.AsyncClient):
        """Не-wav: распознать нечего — 500, но процесс жив и уборка прошла."""
        files = {'file': ('x', b'not-a-wav-at-all', 'application/octet-stream')}
        resp = await guest.post('/chat/voice', files=files)
        assert resp.status_code == 500, resp.text

    async def test_client_filename_is_ignored(self, guest: httpx.AsyncClient):
        """⚠⚠ Имя из запроса в путь не попадает: обход каталога через `..` в
        имени больше не адресует ничего — ответ тот же 500 распознавания, а не
        отказ записи по несуществующему пути."""
        files = {'file': ('../../evil', b'junk', 'application/octet-stream')}
        resp = await guest.post('/chat/voice', files=files)
        assert resp.status_code == 500, resp.text
        # Старый код отвечал бы «No such file or directory: 'temp_../../evil.wav'»
        # — то есть пытался писать по пути из имени. Теперь путь свой.
        assert 'temp_' not in resp.text


class TestMessagesLimitIsClamped:
    """`limit` зажат в `1..200`; всё вне — 422 на входе, до SQL не доходит."""

    @pytest.mark.parametrize('limit', [-1, 0, 201, 999999999])
    async def test_out_of_range_is_422(self, guest: httpx.AsyncClient, limit: int):
        resp = await guest.post('/chat/messages',
                                json={'session_uuid': 'zzz', 'limit': limit})
        assert resp.status_code == 422, f'limit={limit}: {resp.status_code} {resp.text[:120]}'

    @pytest.mark.parametrize('limit', [1, 50, 200])
    async def test_in_range_is_ok(self, guest: httpx.AsyncClient, limit: int):
        resp = await guest.post('/chat/messages',
                                json={'session_uuid': 'zzz', 'limit': limit})
        assert resp.status_code == 200, f'limit={limit}: {resp.status_code} {resp.text[:120]}'

    async def test_default_without_limit_works(self, guest: httpx.AsyncClient):
        """Поле необязательное: без него берётся умолчание (10)."""
        resp = await guest.post('/chat/messages', json={'session_uuid': 'zzz'})
        assert resp.status_code == 200, resp.text
