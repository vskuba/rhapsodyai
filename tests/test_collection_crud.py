import os
from tests.constants import TEST_AUTH
"""
Collection CRUD tests.

Tests cover:
- Creating a collection (POST /collection)
- Reading collections list (GET /collection/list)
- Reading a single collection (GET /collection/{collection_id})
- Updating a collection (PUT /collection/{collection_id})
- Deleting a collection (DELETE /collection/{collection_id})
- Node selection handling (node_id)
"""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_COLL_PREFIX = "test_coll_"


class TestCollectionCRUD:
    """Test the complete collection CRUD flow."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            # Login as admin first
            await client.post(
                "/auth/login",
                json=TEST_AUTH,
            )
            # Pre-cleanup in case of previous run failure
            try:
                list_response = await client.get("/collection/list")
                if list_response.status_code == 200:
                    collections = list_response.json().get("result", [])
                    for coll in collections:
                        if coll.get("name", "").startswith(TEST_COLL_PREFIX):
                            await client.delete(f"/collection/{coll['id']}")
            except Exception:
                pass

            yield client

            # Post-cleanup
            try:
                list_response = await client.get("/collection/list")
                if list_response.status_code == 200:
                    collections = list_response.json().get("result", [])
                    for coll in collections:
                        if coll.get("name", "").startswith(TEST_COLL_PREFIX):
                            await client.delete(f"/collection/{coll['id']}")
            except Exception:
                pass

    async def test_get_collection_list(self, client: httpx.AsyncClient):
        """Test getting collection list."""
        response = await client.get("/collection/list")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)
        # Verify the seeded collections exist
        names = [c["name"] for c in data["result"]]
        assert "dating_girl" in names
        assert "dating_companion" in names

    async def test_create_collection(self, client: httpx.AsyncClient):
        """Test creating a new collection with a custom node_id."""
        response = await client.post(
            "/collection",
            json={
                "name": f"{TEST_COLL_PREFIX}create",
                "node_id": 5,
                "position": 10,
                "language": "en,ua",
                "description": "Test Collection Description"
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        new_id = data["result"]
        assert isinstance(new_id, int)

        # Retrieve and verify
        get_response = await client.get(f"/collection/{new_id}")
        assert get_response.status_code == 200
        coll_data = get_response.json()["result"]
        assert coll_data["name"] == f"{TEST_COLL_PREFIX}create"
        assert coll_data["node_id"] == 5
        assert coll_data["position"] == 10
        assert coll_data["language"] == "en,ua"
        assert coll_data["description"] == "Test Collection Description"

    async def test_update_collection(self, client: httpx.AsyncClient):
        """Test updating an existing collection."""
        # Create first
        response = await client.post(
            "/collection",
            json={
                "name": f"{TEST_COLL_PREFIX}update",
                "node_id": 0,
                "position": 0,
                "language": "ru",
                "description": "Original Description"
            },
        )
        assert response.status_code == 200
        new_id = response.json()["result"]

        # Update
        update_response = await client.put(
            f"/collection/{new_id}",
            json={
                "name": f"{TEST_COLL_PREFIX}updated",
                "node_id": 2,
                "position": 5,
                "language": "ru,en",
                "description": "Updated Description"
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["result"] is True

        # Retrieve and verify
        get_response = await client.get(f"/collection/{new_id}")
        assert get_response.status_code == 200
        coll_data = get_response.json()["result"]
        assert coll_data["name"] == f"{TEST_COLL_PREFIX}updated"
        assert coll_data["node_id"] == 2
        assert coll_data["position"] == 5
        assert coll_data["language"] == "ru,en"
        assert coll_data["description"] == "Updated Description"

    async def test_delete_collection(self, client: httpx.AsyncClient):
        """Test deleting a collection."""
        # Create first
        response = await client.post(
            "/collection",
            json={
                "name": f"{TEST_COLL_PREFIX}delete",
                "node_id": 1,
                "position": 1,
                "language": "en",
                "description": "Delete Me"
            },
        )
        assert response.status_code == 200
        new_id = response.json()["result"]

        # Delete
        delete_response = await client.delete(f"/collection/{new_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["result"] is True

        # Verify it is not in the list anymore
        list_response = await client.get("/collection/list")
        assert list_response.status_code == 200
        collections = list_response.json()["result"]
        ids = [c["id"] for c in collections]
        assert new_id not in ids
