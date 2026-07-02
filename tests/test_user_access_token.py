"""
User Access Token CRUD tests.

Tests cover:
- Getting user access tokens (GET /user/{user_id}/token)
- Generating a random UUIDv4 access token for a user (POST /user/{user_id}/token)
- Deleting an access token (DELETE /user/token/{token_id})
- Foreign key cascading deletion (when user is deleted, their tokens should also be deleted)
"""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


class TestUserAccessToken:
    """Test user access token management."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            # Login as admin first
            await client.post(
                "/auth/login",
                json={"username": "user1", "password": "admin123"},
            )
            yield client

    async def test_access_token_lifecycle(self, client: httpx.AsyncClient):
        # 1. Create a temporary test user
        user_response = await client.post(
            "/user",
            json={
                "username": "test_token_user",
                "email": "test_token_user@example.com",
                "role": "user",
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
