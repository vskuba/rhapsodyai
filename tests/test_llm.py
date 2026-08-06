from tests.constants import TEST_AUTH
"""LLM endpoint tests — /llm/list, /llm/status, /llm/usage/stats."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


class TestLlm:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    # --- /llm/list ---

    async def test_llm_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_llm_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/llm/list")
            assert resp.status_code in (401, 403)

    async def test_llm_list_items_have_required_fields(self, client: httpx.AsyncClient):
        llms = (await client.get("/llm/list")).json()["result"]
        if llms:
            llm = llms[0]
            for field in ("id", "name"):
                assert field in llm, f"Missing field: {field}"

    async def test_llm_list_sorted_by_name(self, client: httpx.AsyncClient):
        llms = (await client.get("/llm/list")).json()["result"]
        names = [l["name"] for l in llms]
        assert names == sorted(names)

    # --- /llm/status ---

    async def test_llm_status_returns_result(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert "nodes" in result
        # Интервал сброса ошибок теперь в секундах (`reset_seconds`, было `reset_hours`)
        assert "reset_seconds" in result
        assert "llms" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["llms"], list)

    async def test_llm_status_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/llm/status")
            assert resp.status_code in (401, 403)

    async def test_llm_status_with_valid_node_id(self, client: httpx.AsyncClient):
        nodes = (await client.get("/llm/status")).json()["result"]["nodes"]
        if nodes:
            node_id = nodes[0]["id"]
            resp = await client.get(f"/llm/status?node_id={node_id}")
            assert resp.status_code == 200
            assert resp.json()["result"]["node_id"] == node_id

    async def test_llm_status_invalid_reset_seconds_rejected(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/status?reset_seconds=999")
        assert resp.status_code == 400

    async def test_llm_status_valid_reset_seconds(self, client: httpx.AsyncClient):
        # Значение должно быть из LLM_ERROR_RESET_SECONDS, иначе роутер отвечает 400.
        # Параметр сохраняется как настройка системы, поэтому исходное возвращаем.
        before = (await client.get("/llm/status")).json()["result"]["reset_seconds"]
        try:
            resp = await client.get("/llm/status?reset_seconds=45")
            assert resp.status_code == 200
            assert resp.json()["result"]["reset_seconds"] == 45
        finally:
            await client.get(f"/llm/status?reset_seconds={before}")

    async def test_llm_status_llm_fields(self, client: httpx.AsyncClient):
        llms = (await client.get("/llm/status")).json()["result"]["llms"]
        if llms:
            llm = llms[0]
            for field in ("id", "name", "provider", "position", "active", "requests"):
                assert field in llm, f"Missing field: {field}"
            for counter in ("m1", "m5", "m10", "d7"):
                assert counter in llm["requests"]

    # --- /llm/usage/stats ---

    async def test_llm_usage_stats_returns_result(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/usage/stats")
        assert resp.status_code == 200
        assert "result" in resp.json()

    async def test_llm_usage_stats_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/llm/usage/stats")
            assert resp.status_code in (401, 403)

    async def test_llm_usage_stats_with_node_id(self, client: httpx.AsyncClient):
        nodes = (await client.get("/llm/status")).json()["result"]["nodes"]
        if nodes:
            node_id = nodes[0]["id"]
            resp = await client.get(f"/llm/usage/stats?node_id={node_id}")
            assert resp.status_code == 200

    async def test_llm_usage_stats_custom_days(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/usage/stats?days=14")
        assert resp.status_code == 200
