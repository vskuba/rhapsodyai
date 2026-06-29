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

BASE_URL = "http://localhost:8011"
TEST_AGENT_PREFIX = "test_agent_"


class TestAgentCRUD:
    """Test the complete agent CRUD flow."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client with admin authentication."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post(
                "/auth/login",
                json={"username": "user1", "password": "admin123"},
            )
            yield client

    async def test_get_agent_list(self, client: httpx.AsyncClient):
        """Test getting agent list."""
        response = await client.get("/agent/list")
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
                "llm_id": None,
                "workflow_id": None,
                "description": "",
                "role_id": None,
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
        llm_res = await client.get("/llm/list")
        node_res = await client.get("/node/list")
        workflow_res = await client.get("/workflow/list")
        role_res = await client.get("/role/list")

        llm_id = llm_res.json()["result"][0]["id"] if llm_res.json()["result"] else None
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
                "llm_id": llm_id,
                "workflow_id": workflow_id,
                "description": "A fully configured test agent",
                "role_id": role_id,
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
                "llm_id": None,
                "workflow_id": None,
                "description": "Test get by ID",
                "role_id": None,
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
                "llm_id": None,
                "workflow_id": None,
                "description": "Original description",
                "role_id": None,
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
                "llm_id": None,
                "workflow_id": None,
                "description": "Updated description",
                "role_id": None,
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
                "llm_id": None,
                "workflow_id": None,
                "description": "Original",
                "role_id": None,
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
                "llm_id": None,
                "workflow_id": None,
                "description": "Will be deleted",
                "role_id": None,
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
                "llm_id": None,
                "workflow_id": None,
                "description": "",
                "role_id": None,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])