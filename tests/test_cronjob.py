"""
Cronjob execution tests.

Tests cover:
- Executing the Qdrant sync cronjob (POST /cronjob)
- Handling non-existent cronjob files
- Restricting execution to allowed cronjob directories
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
