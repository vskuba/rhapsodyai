import os
from tests.constants import TEST_AUTH
"""
User Access Token CRUD and API validation tests.

Tests cover:
- Getting user access tokens (GET /user/{user_id}/token)
- Generating a random UUIDv4 access token for a user (POST /user/{user_id}/token)
- Deleting an access token (DELETE /user/token/{token_id})
- Foreign key cascading deletion (when user is deleted, their tokens should also be deleted)
- Querying agent list with API key (POST /agent/list)
"""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.auth

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestUserAccessToken:
    """Test user access token management and API key usage."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            # Login as admin first
            await client.post(
                "/auth/login",
                json=TEST_AUTH,
            )
            yield client

    @pytest.fixture
    async def own_key(self, client: httpx.AsyncClient) -> AsyncGenerator[str, None]:
        """Свежий токен доступа **своей** учётки — той, под которой вошёл `client`.

        ⚠⚠ Заводится и удаляется тестом. Готовый ключ из базы для этого не годится:
        он принадлежит неизвестно кому, и его роль решает, что будет в ответе. Так и
        вышло — тест падал на чужом ключе при полностью исправном коде.

        ⚠ Учётка берётся из `/auth/me`, а не пишется литералом: сюита ходит под
        разными именами (`QA_USERNAME`), и второе написание разошлось бы с первым.
        """
        # ⚠ `/auth/me` отдаёт `{"user": …}`, а не общий конверт `result`: это единственная
        # ручка с таким ответом, и тот же ключ читает `test_cabinet.py`.
        me = await client.get('/auth/me')
        assert me.status_code == 200, 'сюита не вошла — токен выдавать некому'
        user_id = me.json()['user']['id']

        made = await client.post(f'/user/{user_id}/token')
        assert made.status_code == 200, f'токен не выдался: {made.text[:200]}'
        row = made.json()['result']

        yield row['token']

        await client.delete(f"/user/token/{row['id']}")

    async def test_access_token_lifecycle(self, client: httpx.AsyncClient):
        # 1. Create a temporary test user
        user_response = await client.post(
            "/user",
            json={
                "username": "test_token_user",
                "email": "test_token_user@example.com",
                "llm_id": None
            },
        )
        assert user_response.status_code == 200
        user = user_response.json()["result"]
        user_id = user["id"]

        try:
            # 2. Get initial tokens list (should be empty)
            tokens_response = await client.get(f"/user/{user_id}/token")
            assert tokens_response.status_code == 200
            assert tokens_response.json()["result"] == []

            # 3. Generate a new token
            create_response = await client.post(f"/user/{user_id}/token")
            assert create_response.status_code == 200
            new_token = create_response.json()["result"]
            assert new_token["user_id"] == user_id
            assert len(new_token["token"]) == 36  # UUIDv4 is 36 chars

            token_id = new_token["id"]

            # 4. Fetch list again, check that the token is present
            tokens_response2 = await client.get(f"/user/{user_id}/token")
            assert tokens_response2.status_code == 200
            tokens = tokens_response2.json()["result"]
            assert len(tokens) == 1
            assert tokens[0]["id"] == token_id
            assert tokens[0]["token"] == new_token["token"]

            # 5. Delete the token
            delete_response = await client.delete(f"/user/token/{token_id}")
            assert delete_response.status_code == 200
            assert delete_response.json()["result"]["deleted"] is True

            # 6. Fetch list again, check that it is empty
            tokens_response3 = await client.get(f"/user/{user_id}/token")
            assert tokens_response3.status_code == 200
            assert tokens_response3.json()["result"] == []

        finally:
            # Cleanup: delete the test user
            await client.delete(f"/user/{user_id}")

    async def test_agent_list_with_api_key(self, own_key: str):
        """Test querying agent list via POST /agent/list using an API Key.

        ⚠⚠ Ключ **заводится тестом**, а не берётся готовым из базы. Прежде здесь
        стоял литерал `8fd15581-…`, и тест падал при исправном коде: этот ключ в
        базе есть, но принадлежит роли `manager_dating`, а она видит агентов только
        своих узлов — проверка же ждала «агентов admin». Красное при исправном коде
        приучает не смотреть на красное (`testing.md`).
        """
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False) as anon_client:
            # 1. Query with valid API key
            headers = {"X-API-KEY": own_key}
            payload = {"find_by": {}}
            response = await anon_client.post("/agent/list", json=payload, headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert "result" in data
            assert isinstance(data["result"], list)
            # ⚠ Ключ выдан той же учётке, под которой ходит сюита, — полноправной:
            # она видит всех агентов, и список обязан быть непустым.
            assert len(data["result"]) > 0, (
                'по своему же ключу список агентов пуст — либо ключ не признан, '
                'либо агентов нет в базе вовсе')

            # Verify that only "id", "name", and "title" are returned for agents
            for agent in data["result"]:
                assert set(agent.keys()) == {"id", "name", "title"}

            # 2. Query with invalid API key
            headers_invalid = {"X-API-KEY": "invalid-token-value"}
            response_invalid = await anon_client.post("/agent/list", json=payload, headers=headers_invalid)
            assert response_invalid.status_code == 401
            # ⚠ Текст отказа общий у всех панелей («нужен вход»), а не наш
            # прежний «Invalid API Key»: разбор «кто пришёл» уехал в скелет
            # (`panel_auth_required`). Сторожим **код**: он и есть договор —
            # по тексту отказа клиенты не ветвятся, а перевод его на язык
            # установки менял бы проверку, ничего не проверяя.
            assert response_invalid.json()["detail"]

            # 3. Query new token-route without header (should fail validation with 401)
            response_no_header = await anon_client.post("/agent/list", json=payload)
            assert response_no_header.status_code == 401
            # ⚠ Тот же довод, что и ниже: сторожим код, а не текст отказа.
            assert response_no_header.json()["detail"]

            # 4. Query session-route without session (should return 401)
            response_no_auth = await anon_client.get("/agent/list")
            assert response_no_auth.status_code == 401
            assert "Not authenticated" in response_no_auth.text

    async def test_get_user_by_api_key(self):
        """Test getting user details via GET /user using an API Key."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False) as anon_client:
            # 1. Query with valid API key
            headers = {"X-API-KEY": "8fd15581-36ae-48ed-812f-3b3d11d427f0"}
            response = await anon_client.get("/user", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert "result" in data
            assert isinstance(data["result"]["id"], int)
            assert data["result"]["id"] > 0
            assert isinstance(data["result"]["username"], str)
            assert len(data["result"]["username"]) > 0

            # 2. Query with invalid API key
            headers_invalid = {"X-API-KEY": "invalid-token-value"}
            response_invalid = await anon_client.get("/user", headers=headers_invalid)
            assert response_invalid.status_code == 401
            # ⚠ Текст отказа общий у всех панелей («нужен вход»), а не наш
            # прежний «Invalid API Key»: разбор «кто пришёл» уехал в скелет
            # (`panel_auth_required`). Сторожим **код**: он и есть договор —
            # по тексту отказа клиенты не ветвятся, а перевод его на язык
            # установки менял бы проверку, ничего не проверяя.
            assert response_invalid.json()["detail"]

            # 3. Query without API key (should fail validation with 401)
            response_no_header = await anon_client.get("/user")
            assert response_no_header.status_code == 401
            # ⚠ Тот же довод, что и ниже: сторожим код, а не текст отказа.
            assert response_no_header.json()["detail"]
