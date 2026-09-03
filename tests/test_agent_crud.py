import os
from tests.constants import TEST_AUTH
"""
Agent CRUD tests.

Tests cover:
- Creating a new agent (POST /agent)
- Reading agent list (GET /agent/list)
- Reading a single agent (GET /agent/{agent_id})
- Updating an agent (PUT /agent/{agent_id})
- Deleting an agent (DELETE /agent/{agent_id})
- Workflow variable handling
- Required field validation
"""

import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_AGENT_PREFIX = "test_agent_"


class TestAgentCRUD:
    """Test the complete agent CRUD flow."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client with admin authentication."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post(
                "/auth/login",
                json=TEST_AUTH,
            )
            yield client

    async def test_get_agent_list(self, client: httpx.AsyncClient):
        """Test getting agent list."""
        response = await client.request("GET", "/agent/list", json={"find_by": {}})
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_create_agent_minimal(self, client: httpx.AsyncClient):
        """Test creating an agent with minimal required fields."""
        response = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}minimal",
                "title": "Minimal Test Agent",
                "greeting": "",
                "prompt_system": "",
                "node_id": None,
                "workflow_id": None,
                "description": "",
                "role_ids": [],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        agent = data["result"]
        assert agent["name"] == f"{TEST_AGENT_PREFIX}minimal"
        assert agent["title"] == "Minimal Test Agent"
        assert "id" in agent
        return agent["id"]

    async def test_create_agent_full(self, client: httpx.AsyncClient):
        """Test creating an agent with all fields including workflow_variable."""
        # First get dependencies
        node_res = await client.get("/node/list")
        workflow_res = await client.get("/workflow/list")
        role_res = await client.get("/role/list")

        node_id = node_res.json()["result"][0]["id"] if node_res.json()["result"] else None
        workflow_id = workflow_res.json()["result"][0]["id"] if workflow_res.json()["result"] else None
        role_id = role_res.json()["result"][0]["id"] if role_res.json()["result"] else None

        workflow_variable = {"test_key": "test_value", "another_key": "another_value"}

        response = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}full",
                "title": "Full Test Agent",
                "greeting": "Hello! I am a test agent.",
                "prompt_system": "You are a helpful test assistant.",
                "node_id": node_id,
                "workflow_id": workflow_id,
                "description": "A fully configured test agent",
                "role_ids": [role_id] if role_id else [],
                "workflow_variable": workflow_variable,
            },
        )
        assert response.status_code == 200
        data = response.json()
        agent = data["result"]
        # workflow_variable may be returned as dict or string
        stored = agent["workflow_variable"]
        if isinstance(stored, str):
            import json
            stored = json.loads(stored)
        assert stored == workflow_variable
        return agent["id"]

    async def test_get_agent_by_id(self, client: httpx.AsyncClient):
        """Test getting a single agent by ID."""
        # Create first
        create_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}get",
                "title": "Get Test Agent",
                "greeting": "Hi",
                "prompt_system": "System prompt",
                "node_id": None,
                "workflow_id": None,
                "description": "Test get by ID",
                "role_ids": [],
            },
        )
        agent_id = create_res.json()["result"]["id"]

        # Get by ID
        response = await client.get(f"/agent/{agent_id}")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        agent = data["result"]
        assert agent["id"] == agent_id
        assert agent["name"] == f"{TEST_AGENT_PREFIX}get"
        assert agent["title"] == "Get Test Agent"

    async def test_update_agent(self, client: httpx.AsyncClient):
        """Test updating an agent."""
        # Create first
        create_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}update",
                "title": "Original Title",
                "greeting": "Original greeting",
                "prompt_system": "Original prompt",
                "node_id": None,
                "workflow_id": None,
                "description": "Original description",
                "role_ids": [],
            },
        )
        agent_id = create_res.json()["result"]["id"]

        # Update
        response = await client.put(
            f"/agent/{agent_id}",
            json={
                "name": f"{TEST_AGENT_PREFIX}updated",
                "title": "Updated Title",
                "greeting": "Updated greeting",
                "prompt_system": "Updated prompt",
                "node_id": None,
                "workflow_id": None,
                "description": "Updated description",
                "role_ids": [],
                "workflow_variable": {"updated": "true"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify update
        get_res = await client.get(f"/agent/{agent_id}")
        agent = get_res.json()["result"]
        assert agent["title"] == "Updated Title"
        stored = agent["workflow_variable"]
        if isinstance(stored, str):
            import json
            stored = json.loads(stored)
        assert stored == {"updated": "true"}

    async def test_update_agent_partial(self, client: httpx.AsyncClient):
        """Test updating only some fields of an agent."""
        create_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}partial",
                "title": "Partial Test",
                "greeting": "Original",
                "prompt_system": "Original",
                "node_id": None,
                "workflow_id": None,
                "description": "Original",
                "role_ids": [],
            },
        )
        agent_id = create_res.json()["result"]["id"]

        # Update only title and greeting
        response = await client.put(
            f"/agent/{agent_id}",
            json={
                "title": "Partial Updated",
                "greeting": "Updated greeting",
            },
        )
        assert response.status_code == 200

        # Verify only those fields changed
        get_res = await client.get(f"/agent/{agent_id}")
        agent = get_res.json()["result"]
        assert agent["title"] == "Partial Updated"
        assert agent["greeting"] == "Updated greeting"
        assert agent["name"] == f"{TEST_AGENT_PREFIX}partial"  # Unchanged
        assert agent["prompt_system"] == "Original"  # Unchanged

    async def test_delete_agent(self, client: httpx.AsyncClient):
        """Test deleting an agent."""
        # Create first
        create_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}delete",
                "title": "Delete Test Agent",
                "greeting": "Bye",
                "prompt_system": "System",
                "node_id": None,
                "workflow_id": None,
                "description": "Will be deleted",
                "role_ids": [],
            },
        )
        agent_id = create_res.json()["result"]["id"]

        # Delete
        response = await client.delete(f"/agent/{agent_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify deleted
        get_res = await client.get(f"/agent/{agent_id}")
        # Should return 404 or empty result
        assert get_res.status_code in [200, 404]
        if get_res.status_code == 200:
            assert get_res.json().get("result") is None

    async def test_agent_list_filtering_by_user_nodes_and_role(self, client: httpx.AsyncClient):
        """Test filtering the agent list by user role and nodes (dual criteria)."""
        # 1. Create a test user with 'manager_dating' role and associated nodes [2, 4]
        user_res = await client.post(
            "/user",
            json={
                "username": "test_filter_user",
                "email": "test_filter_user@example.com",
                "role_id": 2,
                "node_ids": [2, 4]
            },
        )
        assert user_res.status_code == 200
        user_id = user_res.json()["result"]["id"]

        # 2. Create 3 agents:
        # Agent A: matching node and matching role (node_id = 2, role_id = 2)
        agent_a_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}filter_a",
                "title": "Agent A (Matching)",
                "greeting": "Hi",
                "prompt_system": "",
                "node_id": 2,
                "role_ids": [2],  # 'manager_dating' role
                "workflow_id": None,
                "description": "",
            },
        )
        assert agent_a_res.status_code == 200
        agent_a_id = agent_a_res.json()["result"]["id"]

        # Agent B: different node but matching role (node_id = 6, role_id = 2)
        agent_b_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}filter_b",
                "title": "Agent B (Wrong Node)",
                "greeting": "Hi",
                "prompt_system": "",
                "node_id": 6,
                "role_ids": [2],  # 'manager_dating' role
                "workflow_id": None,
                "description": "",
            },
        )
        assert agent_b_res.status_code == 200
        agent_b_id = agent_b_res.json()["result"]["id"]

        # Agent C: matching node but different role (node_id = 2, role_id = 1)
        agent_c_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}filter_c",
                "title": "Agent C (Wrong Role)",
                "greeting": "Hi",
                "prompt_system": "",
                "node_id": 2,
                "role_ids": [1],  # 'admin' role
                "workflow_id": None,
                "description": "",
            },
        )
        assert agent_c_res.status_code == 200
        agent_c_id = agent_c_res.json()["result"]["id"]

        # 3. Request agent list for our test user
        list_res = await client.request("GET", "/agent/list", json={"find_by": {"user_id": user_id}})
        assert list_res.status_code == 200
        agents = list_res.json()["result"]
        agent_ids = [a["id"] for a in agents]

        # Verify that Agent A (matching both) is in the list, but Agents B and C are NOT!
        assert agent_a_id in agent_ids
        assert agent_b_id not in agent_ids
        assert agent_c_id not in agent_ids

        # 4. Request agent list for admin user (admin has role 'admin')
        admin_list_res = await client.request("GET", "/agent/list", json={"find_by": {"user_id": 1}})
        assert admin_list_res.status_code == 200
        admin_agents = admin_list_res.json()["result"]
        admin_agent_ids = [a["id"] for a in admin_agents]

        # Verify that for admin role, ALL agents are returned
        assert agent_a_id in admin_agent_ids
        assert agent_b_id in admin_agent_ids
        assert agent_c_id in admin_agent_ids

        # Clean up
        await client.delete(f"/user/{user_id}")
        await client.delete(f"/agent/{agent_a_id}")
        await client.delete(f"/agent/{agent_b_id}")
        await client.delete(f"/agent/{agent_c_id}")

    async def test_agent_list_get_hides_other_role_agents_for_nonadmin_session(self, client: httpx.AsyncClient):
        """Regression test: GET /agent/list called without an explicit user_id (as the
        admin/agent.html page does) must filter by the *caller's own session role*, not
        return everything unfiltered. Previously a plain 'user' session would see agents
        restricted to role_id == 'admin'."""
        # 1. Create a non-admin user with a real password (so it can log in) and node access
        user_res = await client.post(
            "/user",
            json={
                "username": "test_role_filter_user",
                "email": "test_role_filter_user@example.com",
                "role_id": 2,
                "password": "testpass123",
                "node_ids": [2, 4],
            },
        )
        assert user_res.status_code == 200
        user_id = user_res.json()["result"]["id"]

        # 2. Create an admin-only agent and a manager_dating-role agent, both on a node the user has access to
        admin_agent_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}role_admin",
                "title": "Admin Only Agent",
                "greeting": "",
                "prompt_system": "",
                "node_id": 2,
                "role_ids": [1],  # 'admin' role
                "workflow_id": None,
                "description": "",
            },
        )
        assert admin_agent_res.status_code == 200
        admin_agent_id = admin_agent_res.json()["result"]["id"]

        user_agent_res = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}role_user",
                "title": "User Role Agent",
                "greeting": "",
                "prompt_system": "",
                "node_id": 2,
                "role_ids": [2],  # 'manager_dating' role
                "workflow_id": None,
                "description": "",
            },
        )
        assert user_agent_res.status_code == 200
        user_agent_id = user_agent_res.json()["result"]["id"]

        try:
            # 3. Log in as the non-admin user in a separate session and call GET /agent/list
            #    exactly like admin/agent.html does: no find_by, no user_id.
            async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as user_client:
                login_res = await user_client.post(
                    "/auth/login",
                    json={"username": "test_role_filter_user", "password": "testpass123"},
                )
                assert login_res.status_code == 200

                list_res = await user_client.get("/agent/list")
                assert list_res.status_code == 200
                agent_ids = [a["id"] for a in list_res.json()["result"]]

                assert admin_agent_id not in agent_ids
                assert user_agent_id in agent_ids
        finally:
            # Clean up (back on the admin session)
            await client.delete(f"/user/{user_id}")
            await client.delete(f"/agent/{admin_agent_id}")
            await client.delete(f"/agent/{user_agent_id}")

    async def test_delete_nonexistent_agent(self, client: httpx.AsyncClient):
        """Test deleting a non-existent agent returns error."""
        response = await client.delete("/agent/999999")
        assert response.status_code == 200  # Current API returns 200 with error status
        data = response.json()
        assert data["status"] == "error"

    async def test_agent_workflow_variable_json_handling(self, client: httpx.AsyncClient):
        """Test that workflow_variable is properly stored/retrieved as JSON."""
        complex_vars = {
            "string_key": "string_value",
            "number_key": 42,
            "bool_key": True,
            "nested": {"inner": "value"},
            "array": [1, 2, 3]
        }

        response = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}json",
                "title": "JSON Test Agent",
                "greeting": "",
                "prompt_system": "",
                "node_id": None,
                "workflow_id": None,
                "description": "",
                "role_ids": [],
                "workflow_variable": complex_vars,
            },
        )
        assert response.status_code == 200
        agent_id = response.json()["result"]["id"]

        # Retrieve and verify
        get_res = await client.get(f"/agent/{agent_id}")
        agent = get_res.json()["result"]
        # JSON may be returned as dict (already parsed) or string
        stored = agent["workflow_variable"]
        if isinstance(stored, str):
            import json
            stored = json.loads(stored)
        assert stored == complex_vars

    async def test_agent_list_post_schema_validation(self, client: httpx.AsyncClient):
        """Test POST /agent/list schema validation and response structure."""
        # Create a test agent
        response = await client.post(
            "/agent",
            json={
                "name": f"{TEST_AGENT_PREFIX}schema_test",
                "title": "Schema Test Agent",
                "greeting": "Hello",
                "prompt_system": "Act as a helpful assistant",
                "node_id": 2,
                "workflow_id": None,
                "description": "Verification of POST /agent/list",
                "role_ids": [2],
            },
        )
        assert response.status_code == 200
        agent_id = response.json()["result"]["id"]

        try:
            # Query the newly created agent using POST /agent/list with API Key
            list_res = await client.post(
                "/agent/list",
                headers={"X-API-KEY": "8fd15581-36ae-48ed-812f-3b3d11d427f0"},
                json={
                    "find_by": {"id": agent_id}
                }
            )
            assert list_res.status_code == 200
            data = list_res.json()
            assert "result" in data
            assert isinstance(data["result"], list)
            assert len(data["result"]) >= 1

            # Check that each returned agent has only the expected schema fields: id, name, title
            agent = data["result"][0]
            assert set(agent.keys()) == {"id", "name", "title"}

            assert agent["id"] == agent_id
            assert agent["name"] == f"{TEST_AGENT_PREFIX}schema_test"
            assert agent["title"] == "Schema Test Agent"

        finally:
            # Clean up the test agent
            await client.delete(f"/agent/{agent_id}")


class TestAgentCreateByNameSiteGroup:
    """POST /agent/create: обязательный `site` с форматом и факультативный `group_name` (#34543)."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @staticmethod
    def _payload(name: str, **overrides) -> dict:
        payload = {
            "node": "Telegram",
            "name": name,
            # workflow без шага agent_create_or_update — агент заводится записью,
            # без прогона через /chat/ask с LLM.
            "workflow": "test",
            "site": "support24",
        }
        payload.update(overrides)
        return payload

    async def test_create_requires_site(self, client: httpx.AsyncClient):
        """Без `site` точка обязана отказать 422 и не завести агента."""
        payload = self._payload(f"{TEST_AGENT_PREFIX}no_site")
        payload.pop("site")
        response = await client.post("/agent/create", json=payload)
        assert response.status_code == 422

        found = await client.get("/agent/name/" + payload["name"])
        assert found.status_code == 404

    @pytest.mark.parametrize("bad_site", ["Bad Name!", "site-01", "site_01", "Сайт", "Site01", "a b", ""])
    async def test_create_rejects_site_format(self, client: httpx.AsyncClient, bad_site: str):
        """`site` — только строчная латиница и цифры; всё остальное — 422 (#34543)."""
        response = await client.post(
            "/agent/create",
            json=self._payload(f"{TEST_AGENT_PREFIX}bad_site", site=bad_site),
        )
        assert response.status_code == 422

    async def test_create_stores_site_and_group_name(self, client: httpx.AsyncClient):
        """Переданные `site` и `group_name` ложатся в ответ и в строку агента."""
        payload = self._payload(f"{TEST_AGENT_PREFIX}site_group",
                                site="support24", group_name="Service")
        response = await client.post("/agent/create", json=payload)
        assert response.status_code == 201, response.text

        try:
            result = response.json()["result"]
            assert result["site"] == "support24"

            row = (await client.get(f"/agent/{result['id']}")).json()["result"]
            assert row["site"] == "support24"
            assert row["group_name"] == "Service"
        finally:
            await client.delete(f"/agent/{result['id']}")

    async def test_create_without_group_name_keeps_empty(self, client: httpx.AsyncClient):
        """`group_name` факультативен: не передан — группы нет, агент заведён."""
        payload = self._payload(f"{TEST_AGENT_PREFIX}no_group")
        response = await client.post("/agent/create", json=payload)
        assert response.status_code == 201, response.text

        try:
            result = response.json()["result"]
            row = (await client.get(f"/agent/{result['id']}")).json()["result"]
            assert row["site"] == "support24"
            assert not row["group_name"]
        finally:
            await client.delete(f"/agent/{result['id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
