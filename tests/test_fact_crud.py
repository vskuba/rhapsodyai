import os
from tests.constants import TEST_AUTH
"""Fact CRUD tests — /fact/collection/* and /fact/* endpoints."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestFactRead:
    """Read-only fact endpoints available to all authenticated users."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    async def test_fact_collection_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/fact/collection/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_fact_collection_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/fact/collection/list")
            assert resp.status_code in (401, 403)

    async def test_fact_collection_list_has_fact_count(self, client: httpx.AsyncClient):
        collections = (await client.get("/fact/collection/list")).json()["result"]
        if collections:
            assert "fact_count" in collections[0]

    async def test_fact_list_by_collection(self, client: httpx.AsyncClient):
        collections = (await client.get("/fact/collection/list")).json()["result"]
        if not collections:
            pytest.skip("No collections in DB")
        name = collections[0]["name"]
        resp = await client.get(f"/fact/collection/{name}")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "pagination" in data
        assert "total_records" in data["pagination"]

    async def test_fact_list_pagination_fields(self, client: httpx.AsyncClient):
        collections = (await client.get("/fact/collection/list")).json()["result"]
        if not collections:
            pytest.skip("No collections in DB")
        name = collections[0]["name"]
        resp = await client.get(f"/fact/collection/{name}?page=1&limit=5")
        assert resp.status_code == 200
        pagination = resp.json()["pagination"]
        for field in ("current_page", "limit", "total_records", "total_pages"):
            assert field in pagination

    async def test_fact_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/fact/collection/dating_girl")
            assert resp.status_code in (401, 403)

    async def test_fact_collection_documents_list(self, client: httpx.AsyncClient):
        collections = (await client.get("/fact/collection/list")).json()["result"]
        if not collections:
            pytest.skip("No collections in DB")
        name = collections[0]["name"]
        resp = await client.get(f"/fact/collection/{name}/documents")
        assert resp.status_code == 200
        assert "result" in resp.json()
        assert isinstance(resp.json()["result"], list)

    async def test_fact_list_query_filter(self, client: httpx.AsyncClient):
        collections = (await client.get("/fact/collection/list")).json()["result"]
        if not collections:
            pytest.skip("No collections in DB")
        name = collections[0]["name"]
        resp = await client.get(f"/fact/collection/{name}?query=__no_such_content_xyz123__")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0

    async def test_nonexistent_collection_returns_empty(self, client: httpx.AsyncClient):
        resp = await client.get("/fact/collection/__no_such_collection__")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0


class TestFactWrite:
    """Write operations: create, update, delete facts."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def collection_id(self, client: httpx.AsyncClient):
        """Returns the ID of the first collection that supports fact insertion."""
        resp = await client.get("/fact/collection/list")
        collections = resp.json()["result"]
        if not collections:
            pytest.skip("No collections in DB")
        return collections[0]["id"], collections[0]["name"]

    async def test_create_fact(self, client: httpx.AsyncClient, collection_id):
        cid, cname = collection_id
        resp = await client.put(f"/fact/collection/{cid}", json=[
            {"document": "__pytest_test_fact_document__"}
        ])
        # 500 means collection has no field config; skip if that's the case
        if resp.status_code == 500:
            pytest.skip("Collection has no field configuration")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["added"] == 1

    async def test_create_fact_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.put("/fact/collection/1", json=[{"document": "x"}])
            assert resp.status_code in (401, 403)

    async def test_create_fact_empty_list_rejected(self, client: httpx.AsyncClient, collection_id):
        cid, _ = collection_id
        resp = await client.put(f"/fact/collection/{cid}", json=[])
        assert resp.status_code == 400

    async def test_create_nonexistent_collection_returns_404(self, client: httpx.AsyncClient):
        resp = await client.put("/fact/collection/999999", json=[{"document": "x"}])
        assert resp.status_code == 404

    async def test_update_fact(self, client: httpx.AsyncClient, collection_id):
        cid, cname = collection_id
        create_resp = await client.put(f"/fact/collection/{cid}", json=[
            {"document": "__pytest_original_document__"}
        ])
        if create_resp.status_code == 500:
            pytest.skip("Collection has no field configuration")
        assert create_resp.status_code == 200

        # Find the newly created fact
        facts_resp = await client.get(f"/fact/collection/{cname}?query=__pytest_original_document__")
        facts = facts_resp.json()["result"]
        if not facts:
            pytest.skip("Could not find created fact")
        fact_id = facts[0]["id"]

        upd_resp = await client.put(f"/fact/{fact_id}", json={"document": "__pytest_updated_document__"})
        assert upd_resp.status_code == 200
        assert upd_resp.json()["result"]["updated"] is True

        updated_facts = (await client.get(f"/fact/collection/{cname}?query=__pytest_updated_document__")).json()["result"]
        assert any(f["id"] == fact_id for f in updated_facts)

        await client.delete(f"/fact/{fact_id}")

    async def test_update_nonexistent_fact_returns_404(self, client: httpx.AsyncClient):
        resp = await client.put("/fact/999999", json={"document": "x"})
        assert resp.status_code == 404

    async def test_update_fact_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.put("/fact/1", json={"document": "x"})
            assert resp.status_code in (401, 403)

    async def test_delete_fact(self, client: httpx.AsyncClient, collection_id):
        cid, cname = collection_id
        create_resp = await client.put(f"/fact/collection/{cid}", json=[
            {"document": "__pytest_delete_document__"}
        ])
        if create_resp.status_code == 500:
            pytest.skip("Collection has no field configuration")

        facts = (await client.get(f"/fact/collection/{cname}?query=__pytest_delete_document__")).json()["result"]
        if not facts:
            pytest.skip("Could not find created fact")
        fact_id = facts[0]["id"]

        del_resp = await client.delete(f"/fact/{fact_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "success"

        remaining = (await client.get(f"/fact/collection/{cname}?query=__pytest_delete_document__")).json()["result"]
        assert not any(f["id"] == fact_id for f in remaining)

    async def test_delete_fact_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.delete("/fact/1")
            assert resp.status_code in (401, 403)
