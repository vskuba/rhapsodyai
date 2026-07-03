import pytest
import httpx
import uuid
import subprocess
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


@pytest.fixture(autouse=True, scope="module")
def cleanup_test_companions():
    """Cleanup all companions starting with 'comp_' after tests are completed."""
    yield
    # Delete test companions using docker exec to avoid local MySQL dependencies
    subprocess.run([
        "docker", "exec", "-i", "1ad71ee7eb97_rhapsodyai-mysql-1",
        "mysql", "-u", "developer", "-ppassword", "project",
        "-e", "DELETE FROM companion WHERE name LIKE 'comp_%';"
    ], capture_output=True)


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
            response = await client.post("/companion", json={"name": unique_name})
            assert response.status_code == 401

    async def test_companion_get_or_create(self, client: httpx.AsyncClient):
        """Test getting or creating a companion and updating its title."""
        # Keep name and titles under 25 characters to prevent DB column CHAR(25) truncation
        unique_name = f"comp_{uuid.uuid4().hex[:8]}" # 15 chars
        initial_title = f"Init_{unique_name}" # 20 chars
        updated_title = f"Upd_{unique_name}" # 19 chars

        # 1. First post/create call (companion doesn't exist, should create it with initial_title)
        response1 = await client.post("/companion", json={"name": unique_name, "title": initial_title})
        assert response1.status_code == 200
        data1 = response1.json()
        assert "result" in data1
        companion1 = data1["result"]
        assert companion1["name"] == unique_name
        assert companion1["title"] == initial_title
        assert isinstance(companion1["id"], int)
        companion_id = companion1["id"]

        # 2. Second post/create call (companion exists, should return the same companion and not change title if not passed)
        response2 = await client.post("/companion", json={"name": unique_name})
        assert response2.status_code == 200
        data2 = response2.json()
        assert "result" in data2
        companion2 = data2["result"]
        assert companion2["id"] == companion_id
        assert companion2["name"] == unique_name
        assert companion2["title"] == initial_title

        # 3. Third post/create call with updated_title (should update the companion's title in the DB)
        response3 = await client.post("/companion", json={"name": unique_name, "title": updated_title})
        assert response3.status_code == 200
        data3 = response3.json()
        assert "result" in data3
        companion3 = data3["result"]
        assert companion3["id"] == companion_id
        assert companion3["name"] == unique_name
        assert companion3["title"] == updated_title
