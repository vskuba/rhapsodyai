"""Workflow trace read-only tests — /workflow_trace/run/list, /run/{uuid}."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"


class TestWorkflowTrace:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
            yield client

    # --- /workflow_trace/run/list ---

    async def test_trace_list_returns_result_and_pagination(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "pagination" in data
        assert isinstance(data["result"], list)

    async def test_trace_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/workflow_trace/run/list")
            assert resp.status_code in (401, 403)

    async def test_trace_list_pagination_fields(self, client: httpx.AsyncClient):
        pagination = (await client.get("/workflow_trace/run/list")).json()["pagination"]
        for field in ("current_page", "total_pages", "total_records"):
            assert field in pagination

    async def test_trace_list_pagination_page_param(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?page=1&limit=5")
        assert resp.status_code == 200
        pagination = resp.json()["pagination"]
        assert pagination["current_page"] == 1

    async def test_trace_list_limit_capped_at_100(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?limit=9999")
        assert resp.status_code == 200
        assert len(resp.json()["result"]) <= 100

    async def test_trace_list_filter_by_status_running(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=running")
        assert resp.status_code == 200
        runs = resp.json()["result"]
        for run in runs:
            assert run["status"] == "running"

    async def test_trace_list_filter_by_status_success(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=success")
        assert resp.status_code == 200
        runs = resp.json()["result"]
        for run in runs:
            assert run["status"] == "success"

    async def test_trace_list_filter_by_status_error(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=error")
        assert resp.status_code == 200

    async def test_trace_list_filter_invalid_status_ignored(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=invalid_status")
        assert resp.status_code == 200

    async def test_trace_list_filter_by_workflow_id(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?workflow_id=999999")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0

    async def test_trace_list_filter_by_agent_id(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?agent_id=999999")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0

    async def test_trace_list_run_fields(self, client: httpx.AsyncClient):
        runs = (await client.get("/workflow_trace/run/list")).json()["result"]
        if not runs:
            pytest.skip("No workflow runs in DB")
        run = runs[0]
        for field in ("id", "run_uuid", "status", "started_at", "steps_qty", "children_qty"):
            assert field in run, f"Missing field: {field}"

    # --- /workflow_trace/run/{run_uuid} ---

    async def test_trace_detail_nonexistent_returns_404(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_trace_detail_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/workflow_trace/run/00000000-0000-0000-0000-000000000000")
            assert resp.status_code in (401, 403, 404)

    async def test_trace_detail_existing_run(self, client: httpx.AsyncClient):
        runs = (await client.get("/workflow_trace/run/list")).json()["result"]
        if not runs:
            pytest.skip("No workflow runs in DB")
        run_uuid = runs[0]["run_uuid"]
        resp = await client.get(f"/workflow_trace/run/{run_uuid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert "run_uuid" in result
        assert result["run_uuid"] == run_uuid
        assert "steps" in result
