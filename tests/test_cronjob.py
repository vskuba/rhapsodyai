"""
Cronjob execution tests.

Tests cover:
- Executing the Qdrant sync cronjob (POST /cronjob)
- Handling non-existent cronjob files
- Restricting execution to allowed cronjob directories
- Guarding the endpoint by the X-Forwarded-For chain (private hops pass, public or unparsable — 403)
"""
import os
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.core

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestCronjobFlow:
    """Test the cronjob endpoint execution."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=120.0) as client:
            yield client

    async def test_fact_qdrant_sync_cronjob(self, client: httpx.AsyncClient):
        """Test successful execution of the fact Qdrant sync cronjob."""
        payload = {
            "cronjob_path": "src/cronjob/fact/fact_qdrant_sync.py",
            "metadata": {},
            "timeout": 120
        }
        response = await client.post("/cronjob", json=payload)
        
        # We expect a successful execution with status code 200
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "result" in data
        assert isinstance(data["result"], str)
        # Verify that either all synced successfully or some other expected log message
        assert "Все данные во всех коллекциях синхронизированы" in data["result"] or "Соединение с Qdrant закрыто" in data["result"] or "синхронизации" in data["result"]

    async def test_nonexistent_cronjob(self, client: httpx.AsyncClient):
        """Test execution of a non-existent cronjob file returns 400 Bad Request."""
        payload = {
            "cronjob_path": "src/cronjob/fact/nonexistent_cronjob.py",
            "metadata": {},
            "timeout": 120
        }
        response = await client.post("/cronjob", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "не найден" in data["detail"] or "not found" in data["detail"].lower()

    async def test_unauthorized_cronjob_path(self, client: httpx.AsyncClient):
        """Test that execution is restricted to the allowed src/cronjob/ directory."""
        payload = {
            "cronjob_path": "src/ai/ai_fact.py",
            "metadata": {},
            "timeout": 120
        }
        response = await client.post("/cronjob", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Недопустимый путь к cronjob" in data["detail"] or "invalid" in data["detail"].lower()

    @pytest.mark.parametrize("cronjob_path", [
        "src/cronjob/../../main_telegram.py",
        "src/cronjob/../../../etc/hosts",
        "src/cronjob/fact/../../ai/ai_fact.py",
    ])
    async def test_path_escape_is_rejected(self, client: httpx.AsyncClient,
                                           cronjob_path: str):
        """⚠⚠ Приставка на месте, а файл чужой — через `..`.

        Проверка пути сравнивала начало строки, и `src/cronjob/../../x.py` её
        проходил: приставка `src/cronjob/` есть. Точка публична (`/cronjob` в
        белом списке `auth_middleware`), так что это был запуск любого `.py`
        установки кем угодно. Поймано аудитом: ответ был не «не найден», а
        «Timeout exceeded» — то есть `main_telegram.py` успел стартовать.

        ⚠ Ждём именно «недопустимый путь», а не «не найден»: файл-то
        существует, и отказать обязана проверка каталога, а не проверка наличия.
        """
        response = await client.post("/cronjob", json={
            "cronjob_path": cronjob_path,
            "metadata": {},
            "timeout": 5,
        })
        assert response.status_code == 400, response.text
        assert "Недопустимый путь к cronjob" in response.json()["detail"]

    async def test_nested_cronjob_path_still_allowed(self, client: httpx.AsyncClient):
        """Подкаталог внутри разрешённого — можно: там живёт `fact/`.

        Страховка от перегиба: запрет обхода не должен запереть вложенные
        задания, которых у нас целая папка.
        """
        response = await client.post("/cronjob", json={
            "cronjob_path": "src/cronjob/fact/nonexistent_cronjob.py",
            "metadata": {},
            "timeout": 5,
        })
        assert response.status_code == 400, response.text
        assert "не найден" in response.json()["detail"]

    async def test_public_forwarded_for_is_forbidden(self, client: httpx.AsyncClient):
        """Запрос, прошедший через прокси с публичного адреса, ручка отвергает сама (вторая линия за Caddy)."""
        payload = {"cronjob_path": "src/cronjob/fact/fact_qdrant_sync.py", "metadata": {}, "timeout": 5}
        response = await client.post("/cronjob", json=payload, headers={"X-Forwarded-For": "93.184.216.34"})
        assert response.status_code == 403

    @pytest.mark.parametrize("forwarded_for", [
        "10.0.0.5",
        "10.0.0.5, 172.16.5.9, 192.168.10.20",
        "192.168.10.20, 10.0.0.5",
    ])
    async def test_private_forwarded_for_chain_passes_guard(self, client: httpx.AsyncClient,
                                                            forwarded_for: str):
        """Цепочка только из частных адресов (`10.x`, `172.16.x`, `192.168.x`) — защита не мешает.

        `net_private_request` смотрит не на приватность клиента, а чтобы в
        `X-Forwarded-For` не было ни одного публичного хопа: цепочка из внутренних
        прокси — docker-сеть, Caddy — норма, запрос идёт в обработчик.

        ⚠ Файл берём заведомо несуществующий: 400 «не найден» — значит, ручка
        дошла до проверки пути, то есть защита пропустила. С 403 до этого текста
        дело бы не дошло.
        """
        response = await client.post("/cronjob", json={
            "cronjob_path": "src/cronjob/fact/nonexistent_cronjob.py",
            "metadata": {},
            "timeout": 5,
        }, headers={"X-Forwarded-For": forwarded_for})
        assert response.status_code != 403, response.text
        assert response.status_code == 400, response.text
        assert "не найден" in response.json()["detail"]

    @pytest.mark.parametrize("forwarded_for", [
        "93.184.216.34, 10.0.0.5",
        "10.0.0.5, 93.184.216.34, 192.168.10.20",
        "192.168.10.20, 172.16.5.9, 8.8.8.8",
    ])
    async def test_mixed_forwarded_for_chain_is_forbidden(self, client: httpx.AsyncClient,
                                                          forwarded_for: str):
        """Хоть один публичный адрес в цепочке — 403, в какой бы позиции он ни стоял.

        `net_private_request` требует `all(...)`: публичный хоп не прячется ни в
        начале (клиент шёл снаружи), ни в середине или в конце цепочки прокси.
        Ровно `172.16.x` — частная (`/12`), а `8.8.8.8` и `93.184.216.34` —
        публичные; документальные сети (`192.0.2.x`, `203.0.113.x`) тут не годятся:
        `ipaddress` считает их частными.
        """
        response = await client.post("/cronjob", json={
            "cronjob_path": "src/cronjob/fact/nonexistent_cronjob.py",
            "metadata": {},
            "timeout": 5,
        }, headers={"X-Forwarded-For": forwarded_for})
        assert response.status_code == 403, response.text

    @pytest.mark.parametrize("forwarded_for", [
        "garbage",
        "999.999.999.999",
        "10.0.0.5, not-an-ip, 192.168.10.20",
    ])
    async def test_unparsable_forwarded_for_is_forbidden(self, client: httpx.AsyncClient,
                                                         forwarded_for: str):
        """Мусор вместо адреса в цепочке — 403: неразобранный хоп считается чужим.

        Прокси, который пишет в `X-Forwarded-For` имя хоста вместо IP, не должен
        открывать ручку: `net_private_address` на не-адрес отвечает False, и вся
        цепочка считается внешней — закрытая по умолчанию, а не по умолчанию
        открытая. Мусор и в середине цепочки между настоящими частными адресами
        тоже отсекает: позиция не спасает.
        """
        response = await client.post("/cronjob", json={
            "cronjob_path": "src/cronjob/fact/nonexistent_cronjob.py",
            "metadata": {},
            "timeout": 5,
        }, headers={"X-Forwarded-For": forwarded_for})
        assert response.status_code == 403, response.text
