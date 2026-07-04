"""
User Cabinet page and endpoint tests.

Tests cover:
- Accessing /admin/cabinet HTML page (requires authentication)
- Reading the current user's details (GET /auth/me)
- Updating the current user's email and LLM model (PUT /auth/me)
- Validation checks for updating user details
"""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


class TestCabinetFlow:
    """Test the complete cabinet flow including HTML and JSON API endpoints."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            # Login as standard user first
            await client.post(
                "/auth/login",
                json={"username": "user1", "password": "admin123"},
            )
            yield client

    async def test_cabinet_page_requires_auth(self):
        """Test that accessing the cabinet HTML page redirects to login when unauthenticated."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False) as client:
            response = await client.get("/admin/cabinet")
            assert response.status_code == 307
            assert response.headers.get("location") == "/login"

    async def test_cabinet_page_accessible_with_auth(self, client: httpx.AsyncClient):
        """Test that the cabinet HTML page is accessible when authenticated."""
        response = await client.get("/admin/cabinet")
        assert response.status_code == 200
        assert "Личный кабинет" in response.text
        assert "cabinet-form" in response.text
        assert "tokensSection" in response.text

    async def test_get_current_user_profile(self, client: httpx.AsyncClient):
        """Test getting current user's details via GET /auth/me."""
        response = await client.get("/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        user = data["user"]
        assert user["username"] == "user1"
        assert "email" in user
        assert "role" in user
        assert "llm_ids" in user

    async def test_update_current_user_profile(self, client: httpx.AsyncClient):
        """Test successfully updating the user's email."""
        # 1. Update user profile details
        update_payload = {
            "email": "updated_user1@example.com"
        }
        update_response = await client.put("/auth/me", json=update_payload)
        assert update_response.status_code == 200
        
        data = update_response.json()
        assert "user" in data
        updated_user = data["user"]
        assert updated_user["email"] == "updated_user1@example.com"

        # 2. Verify changes persist via GET /auth/me
        get_response = await client.get("/auth/me")
        assert get_response.status_code == 200
        user = get_response.json()["user"]
        assert user["email"] == "updated_user1@example.com"

        # 3. Restore original user1 profile state to prevent test pollution
        restore_payload = {
            "email": "developer@rhapsody.com"
        }
        restore_response = await client.put("/auth/me", json=restore_payload)
        assert restore_response.status_code == 200

    async def test_update_profile_missing_email(self, client: httpx.AsyncClient):
        """Test that updating profile without an email returns a 400 Bad Request error."""
        update_payload = {
            "email": None
        }
        response = await client.put("/auth/me", json=update_payload)
        assert response.status_code == 400
        assert "Email is required" in response.text
