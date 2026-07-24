"""Permission boundary tests — non-admin users must get 403 on write operations."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"
TEST_PERM_PREFIX = "test_perm_"


class TestPermissions:
    """
    All non-admin users get AUTH_PERMISSIONS_DEFAULT (view-only).
    These tests verify that write/delete operations return 403 for non-admin.
    """

    @pytest.fixture
    async def admin(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
            yield client

    @pytest.fixture
    async def non_admin(self, admin: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Creates a non-admin user via admin, logs in, yields client, cleans up."""
        # Create role
        role_resp = await admin.post("/role", json={"name": f"{TEST_PERM_PREFIX}role", "node_ids": []})
        assert role_resp.status_code == 200
        role_id = role_resp.json()["result"]["id"]

        # Create user with that role
        username = f"{TEST_PERM_PREFIX}user"
        password = "TestPerm123!"
        # Pre-cleanup: remove leftover from a failed previous run
        try:
            users = (await admin.get("/user/list")).json().get("result", [])
            for u in users:
                if u.get("username") == username:
                    await admin.delete(f"/user/{u['id']}")
        except Exception:
            pass

        user_resp = await admin.post("/user", json={
            "username": username,
            "email": f"{username}@test.local",
            "password": password,
            "role_id": role_id,
            "node_ids": [],
        })
        assert user_resp.status_code == 200
        user_id = user_resp.json()["result"]["id"]

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            login = await client.post("/auth/login", json={"username": username, "password": password})
            assert login.status_code == 200
            yield client

        await admin.delete(f"/user/{user_id}")
        await admin.delete(f"/role/{role_id}")

    # --- User write operations ---

    async def test_non_admin_cannot_create_user(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/user", json={
            "username": "hacked_user", "email": "h@x.com", "password": "pass1234"
        })
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_user(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/user/1")
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_user(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/user/1", json={"email": "h@x.com"})
        assert resp.status_code == 403

    # --- Agent write operations ---

    async def test_non_admin_cannot_create_agent(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/agent", json={"title": "Hacked", "node_id": 2})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_agent(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/agent/1")
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_agent(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/agent/1", json={"title": "Hacked"})
        assert resp.status_code == 403

    # --- Node write operations ---

    async def test_non_admin_cannot_create_node(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/node", json={"name": "hacked_node"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_node(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/node/1")
        assert resp.status_code == 403

    # --- Workflow write operations ---

    async def test_non_admin_cannot_create_workflow(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/workflow", json={"name": "hacked", "title": "Hacked"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_workflow(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/workflow/1")
        assert resp.status_code == 403

    # --- Role write operations ---

    async def test_non_admin_cannot_create_role(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/role", json={"name": "hacked_role"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_role(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/role/1")
        assert resp.status_code == 403

    # --- Fact write operations ---

    async def test_non_admin_cannot_delete_fact(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/fact/1")
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_fact(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/fact/1", json={"document": "hacked"})
        assert resp.status_code == 403

    # --- Setting write operations ---

    async def test_non_admin_cannot_save_setting(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/setting", json={"key": "hacked_key", "value": "hacked"})
        assert resp.status_code == 403

    # --- Non-admin CAN read (view permissions) ---

    async def test_non_admin_can_list_agents(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.get("/agent/list")
        assert resp.status_code == 200

    async def test_non_admin_can_list_nodes(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.get("/node/list")
        assert resp.status_code == 200

    async def test_non_admin_can_list_workflows(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.get("/workflow/list")
        assert resp.status_code == 200

    async def test_non_admin_can_list_llms(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.get("/llm/list")
        assert resp.status_code == 200

    async def test_non_admin_can_view_llm_status(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.get("/llm/status")
        assert resp.status_code == 200
