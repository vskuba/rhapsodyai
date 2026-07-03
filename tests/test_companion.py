import pytest
import httpx
import uuid
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


class TestCompanionFlow:
    """Test the complete companion endpoint flow."""

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

    async def test_companion_requires_auth(self):
        """Test that accessing the companion endpoint requires authentication."""
        unique_name = f"comp_{uuid.uuid4().hex[:10]}"
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False) as client:
            response = await client.get(f"/companion/{unique_name}")
            assert response.status_code == 401

    async def test_companion_get_or_create(self, client: httpx.AsyncClient):
        """Test getting or creating a companion."""
        unique_name = f"comp_{uuid.uuid4().hex[:10]}"

        # 1. First get/create call (companion doesn't exist, should create it)
        response1 = await client.get(f"/companion/{unique_name}")
        assert response1.status_code == 200
        data1 = response1.json()
        assert "result" in data1
        companion1 = data1["result"]
        assert companion1["name"] == unique_name
        assert companion1["title"] == unique_name
        assert isinstance(companion1["id"], int)
        companion_id = companion1["id"]

        # 2. Second get/create call (companion exists, should return the exact same companion)
        response2 = await client.get(f"/companion/{unique_name}")
        assert response2.status_code == 200
        data2 = response2.json()
        assert "result" in data2
        companion2 = data2["result"]
        assert companion2["id"] == companion_id
        assert companion2["name"] == unique_name
        assert companion2["title"] == unique_name
