import os
from tests.constants import TEST_AUTH
"""Node CRUD tests — /node endpoints."""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_NODE_PREFIX = "test_node_"


class TestNodeCRUD:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            await self._cleanup(client)
            yield client
            await self._cleanup(client)

    @staticmethod
    async def _cleanup(client: httpx.AsyncClient):
        try:
            resp = await client.get("/node/list")
            if resp.status_code == 200:
                for node in resp.json().get("result", []):
                    if node.get("name", "").startswith(TEST_NODE_PREFIX):
                        await client.delete(f"/node/{node['id']}")
        except Exception:
            pass

    async def test_node_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/node/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_node_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/node/list")
            assert resp.status_code in (401, 403)

    async def test_create_node(self, client: httpx.AsyncClient):
        resp = await client.post("/node", json={"name": f"{TEST_NODE_PREFIX}create", "position": 99})
        assert resp.status_code == 200
        node_id = resp.json()["result"]
        assert isinstance(node_id, int)

        get_resp = await client.get(f"/node/{node_id}")
        assert get_resp.status_code == 200
        node = get_resp.json()["result"]
        assert node["name"] == f"{TEST_NODE_PREFIX}create"
        assert node["position"] == 99
        assert "llm_ids" in node
        assert isinstance(node["llm_ids"], list)

    async def test_create_node_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.post("/node", json={"name": f"{TEST_NODE_PREFIX}anon"})
            assert resp.status_code in (401, 403)

    async def test_update_node(self, client: httpx.AsyncClient):
        resp = await client.post("/node", json={"name": f"{TEST_NODE_PREFIX}update_orig", "position": 1})
        assert resp.status_code == 200
        node_id = resp.json()["result"]

        upd = await client.put(f"/node/{node_id}", json={"name": f"{TEST_NODE_PREFIX}update_new", "position": 50})
        assert upd.status_code == 200

        node = (await client.get(f"/node/{node_id}")).json()["result"]
        assert node["name"] == f"{TEST_NODE_PREFIX}update_new"
        assert node["position"] == 50

    async def test_update_node_partial(self, client: httpx.AsyncClient):
        resp = await client.post("/node", json={"name": f"{TEST_NODE_PREFIX}partial", "position": 10})
        node_id = resp.json()["result"]

        upd = await client.put(f"/node/{node_id}", json={"position": 77})
        assert upd.status_code == 200

        node = (await client.get(f"/node/{node_id}")).json()["result"]
        assert node["name"] == f"{TEST_NODE_PREFIX}partial"
        assert node["position"] == 77

    async def test_delete_node(self, client: httpx.AsyncClient):
        resp = await client.post("/node", json={"name": f"{TEST_NODE_PREFIX}delete", "position": 0})
        node_id = resp.json()["result"]

        del_resp = await client.delete(f"/node/{node_id}")
        assert del_resp.status_code == 200
        assert del_resp.json().get("status") == "success"

        ids = [n["id"] for n in (await client.get("/node/list")).json()["result"]]
        assert node_id not in ids

    async def test_delete_nonexistent_node(self, client: httpx.AsyncClient):
        resp = await client.delete("/node/999999")
        assert resp.status_code == 200
        assert resp.json().get("status") == "error"

    async def test_get_nonexistent_node_returns_none(self, client: httpx.AsyncClient):
        resp = await client.get("/node/999999")
        assert resp.status_code == 200
        assert resp.json()["result"] is None

    async def test_node_list_sorted_by_name(self, client: httpx.AsyncClient):
        nodes = (await client.get("/node/list")).json()["result"]
        names = [n["name"] for n in nodes]
        assert names == sorted(names)
