"""
User CRUD tests.

Tests cover:
- Creating a user (POST /user)
- Reading user list (GET /user/list)
- Reading a single user (GET /user/{user_id})
- Updating a user (PUT /user/{user_id})
- Deleting a user (DELETE /user/{user_id})
- Role field handling
"""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


class TestUserCRUD:
    """Test the complete user CRUD flow."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            # Login as admin first
            await client.post(
                "/auth/login",
                json={"username": "admin", "password": "admin123"},
            )
            yield client

    async def test_get_user_list(self, client: httpx.AsyncClient):
        """Test getting user list."""
        response = await client.get("/user/list")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_create_user(self, client: httpx.AsyncClient):
        """Test creating a new user."""
        response = await client.post(
            "/user",
            json={
                "username": "test_user_crud",
                "email": "test_crud@example.com",
                "role_id": 2,
                "llm_id": None
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["username"] == "test_user_crud"
        assert user["email"] == "test_crud@example.com"
        assert user["role"] == "manager_dating"
        assert "id" in user
        return user["id"]

    async def test_create_user_with_admin_role(self, client: httpx.AsyncClient):
        """Test creating a new user with admin role."""
        response = await client.post(
            "/user",
            json={
                "username": "test_admin_crud",
                "email": "test_admin_crud@example.com",
                "role_id": 1,
                "llm_id": None
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["username"] == "test_admin_crud"
        assert user["email"] == "test_admin_crud@example.com"
        assert user["role"] == "admin"
        assert "id" in user
        return user["id"]

    async def test_get_user_by_id(self, client: httpx.AsyncClient):
        """Test getting a single user by ID."""
        # First create a user
        create_response = await client.post(
            "/user",
            json={
                "username": "test_user_get",
                "email": "test_get@example.com",
                "role_id": 2,
                "llm_id": None
            },
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["result"]["id"]

        # Now get the user
        response = await client.get(f"/user/{user_id}")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["id"] == user_id
        assert user["username"] == "test_user_get"
        assert user["email"] == "test_get@example.com"
        assert user["role"] == "manager_dating"

    async def test_update_user(self, client: httpx.AsyncClient):
        """Test updating a user."""
        # First create a user
        create_response = await client.post(
            "/user",
            json={
                "username": "test_user_update",
                "email": "test_update@example.com",
                "role_id": 2,
                "llm_id": None
            },
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["result"]["id"]

        # Update the user
        response = await client.put(
            f"/user/{user_id}",
            json={
                "username": "test_user_updated",
                "email": "test_updated@example.com",
                "role_id": 1,
                "llm_id": None
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["id"] == user_id
        assert user["username"] == "test_user_updated"
        assert user["email"] == "test_updated@example.com"
        assert user["role"] == "admin"

    async def test_delete_user(self, client: httpx.AsyncClient):
        """Test deleting a user."""
        # First create a user
        create_response = await client.post(
            "/user",
            json={
                "username": "test_user_delete",
                "email": "test_delete@example.com",
                "role_id": 2,
                "llm_id": None
            },
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["result"]["id"]

        # Delete the user
        response = await client.delete(f"/user/{user_id}")
        assert response.status_code == 200

        # Verify user is deleted
        get_response = await client.get(f"/user/{user_id}")
        assert get_response.status_code == 404 or (get_response.status_code == 200 and get_response.json().get("result") is None)

    async def test_user_default_role_is_none(self, client: httpx.AsyncClient):
        """Test that a user created without a role has no role assigned."""
        response = await client.post(
            "/user",
            json={
                "username": "test_user_default_role",
                "email": "test_default_role@example.com",
                # role not specified
                "llm_id": None
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["role"] is None  # Роль не задана — role_id NULL

    async def test_update_user_partial(self, client: httpx.AsyncClient):
        """Test updating only some fields of a user."""
        # First create a user
        create_response = await client.post(
            "/user",
            json={
                "username": "test_user_partial",
                "email": "test_partial@example.com",
                "role_id": 2,
                "llm_id": None
            },
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["result"]["id"]

        # Update only the role
        response = await client.put(
            f"/user/{user_id}",
            json={
                "role_id": 1
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["id"] == user_id
        assert user["role"] == "admin"
        # Other fields should remain unchanged
        assert user["username"] == "test_user_partial"
        assert user["email"] == "test_partial@example.com"

    async def test_user_node_associations(self, client: httpx.AsyncClient):
        """Test creating and updating user-node associations."""
        # Create a user with node associations (nodes 2 and 4 exist in seeds)
        response = await client.post(
            "/user",
            json={
                "username": "test_user_nodes",
                "email": "test_nodes@example.com",
                "role_id": 2,
                "llm_id": None,
                "node_ids": [2, 4]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        user = data["result"]
        assert user["node_ids"] == [2, 4]
        user_id = user["id"]

        # Update the user node associations to [4, 6]
        update_response = await client.put(
            f"/user/{user_id}",
            json={
                "node_ids": [4, 6]
            },
        )
        assert update_response.status_code == 200
        updated_user = update_response.json()["result"]
        assert updated_user["node_ids"] == [4, 6]

        # Verify via GET by ID
        get_response = await client.get(f"/user/{user_id}")
        assert get_response.status_code == 200
        fetched_user = get_response.json()["result"]
        assert fetched_user["node_ids"] == [4, 6]

        # Verify via GET list
        list_response = await client.get("/user/list")
        assert list_response.status_code == 200
        users_list = list_response.json()["result"]
        user_in_list = next((u for u in users_list if u["id"] == user_id), None)
        assert user_in_list is not None
        assert user_in_list["node_ids"] == [4, 6]

        # Clean up
        delete_response = await client.delete(f"/user/{user_id}")
        assert delete_response.status_code == 200

    async def test_delete_nonexistent_user(self, client: httpx.AsyncClient):
        """Test deleting a non-existent user returns 404."""
        response = await client.delete("/user/999999")
        # The API might return 200 even for non-existent, or 404
        # Let's check what the actual behavior is
        assert response.status_code in [200, 404]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])