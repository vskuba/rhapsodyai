from tests.constants import TEST_AUTH
"""Workflow CRUD tests — /workflow and /workflow_step endpoints."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"
TEST_WF_PREFIX = "test_wf_pytest_"


class TestWorkflowCRUD:

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
            resp = await client.get("/workflow/list")
            if resp.status_code == 200:
                for wf in resp.json().get("result", []):
                    if wf.get("name", "").startswith(TEST_WF_PREFIX):
                        await client.delete(f"/workflow/{wf['id']}")
        except Exception:
            pass

    # --- list ---

    async def test_workflow_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_workflow_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/workflow/list")
            assert resp.status_code in (401, 403)

    async def test_workflow_list_sorted_by_title(self, client: httpx.AsyncClient):
        workflows = (await client.get("/workflow/list")).json()["result"]
        titles = [w["title"] for w in workflows]
        assert titles == sorted(titles)

    # --- create ---

    async def test_create_workflow(self, client: httpx.AsyncClient):
        resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}create",
            "title": "Test Create",
            "description": "desc",
            "position": 0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        wf_id = data["result"]["id"]
        assert isinstance(wf_id, int)

        get_resp = await client.get(f"/workflow/{wf_id}")
        assert get_resp.status_code == 200
        wf = get_resp.json()["result"]
        assert wf["name"] == f"{TEST_WF_PREFIX}create"
        assert wf["title"] == "Test Create"

    async def test_create_workflow_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.post("/workflow", json={"name": "x", "title": "x"})
            assert resp.status_code in (401, 403)

    async def test_create_workflow_with_node_id(self, client: httpx.AsyncClient):
        resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}node",
            "title": "With Node",
            "node_id": 2,
        })
        assert resp.status_code == 200
        wf_id = resp.json()["result"]["id"]
        wf = (await client.get(f"/workflow/{wf_id}")).json()["result"]
        assert wf["node_id"] == 2

    # --- list by node ---

    async def test_workflow_list_by_node(self, client: httpx.AsyncClient):
        resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}by_node",
            "title": "By Node",
            "node_id": 2,
        })
        wf_id = resp.json()["result"]["id"]

        list_resp = await client.get("/workflow/2/list")
        assert list_resp.status_code == 200
        ids = [w["id"] for w in list_resp.json()["result"]]
        assert wf_id in ids

    # --- update ---

    async def test_update_workflow(self, client: httpx.AsyncClient):
        create_resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}upd",
            "title": "Original Title",
        })
        wf_id = create_resp.json()["result"]["id"]

        upd_resp = await client.put(f"/workflow/{wf_id}", json={"title": "Updated Title", "description": "new desc"})
        assert upd_resp.status_code == 200

        wf = (await client.get(f"/workflow/{wf_id}")).json()["result"]
        assert wf["title"] == "Updated Title"
        assert wf["description"] == "new desc"

    async def test_update_workflow_requires_auth(self, client: httpx.AsyncClient):
        create_resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}upd_auth",
            "title": "Auth Test",
        })
        wf_id = create_resp.json()["result"]["id"]

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.put(f"/workflow/{wf_id}", json={"title": "Hacked"})
            assert resp.status_code in (401, 403)

    # --- delete ---

    async def test_delete_workflow(self, client: httpx.AsyncClient):
        create_resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}del",
            "title": "Delete Me",
        })
        wf_id = create_resp.json()["result"]["id"]

        del_resp = await client.delete(f"/workflow/{wf_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "success"

        ids = [w["id"] for w in (await client.get("/workflow/list")).json()["result"]]
        assert wf_id not in ids

    async def test_delete_nonexistent_workflow_returns_404(self, client: httpx.AsyncClient):
        resp = await client.delete("/workflow/999999")
        assert resp.status_code == 404

    async def test_delete_workflow_requires_auth(self, client: httpx.AsyncClient):
        create_resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}del_auth",
            "title": "Del Auth Test",
        })
        wf_id = create_resp.json()["result"]["id"]

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.delete(f"/workflow/{wf_id}")
            assert resp.status_code in (401, 403)

    # --- duplicate ---

    async def test_duplicate_workflow(self, client: httpx.AsyncClient):
        create_resp = await client.post("/workflow", json={
            "name": f"{TEST_WF_PREFIX}orig",
            "title": "Original",
            "description": "to duplicate",
        })
        wf_id = create_resp.json()["result"]["id"]

        dup_resp = await client.post(f"/workflow/{wf_id}/duplicate")
        assert dup_resp.status_code == 200
        dup_data = dup_resp.json()
        assert dup_data["status"] == "success"
        dup_id = dup_data["result"]["id"]
        assert dup_id != wf_id
        assert "_copy" in dup_data["result"]["name"]
        assert "copy" in dup_data["result"]["title"]

        await client.delete(f"/workflow/{dup_id}")

    async def test_duplicate_nonexistent_workflow_returns_404(self, client: httpx.AsyncClient):
        resp = await client.post("/workflow/999999/duplicate")
        assert resp.status_code == 404


class TestWorkflowSteps:

    @pytest.fixture
    async def client_with_workflow(self) -> AsyncGenerator[tuple[httpx.AsyncClient, int], None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            resp = await client.post("/workflow", json={
                "name": f"{TEST_WF_PREFIX}steps",
                "title": "Steps Test WF",
            })
            wf_id = resp.json()["result"]["id"]
            yield client, wf_id
            await client.delete(f"/workflow/{wf_id}")

    # --- step types ---

    async def test_step_type_list(self, client_with_workflow):
        client, _ = client_with_workflow
        resp = await client.get("/workflow_step/list")
        assert resp.status_code == 200
        types = resp.json()["result"]
        assert isinstance(types, list)
        assert len(types) > 0
        assert "id" in types[0]
        assert "name" in types[0]

    # --- steps ---

    async def test_get_workflow_steps_empty(self, client_with_workflow):
        client, wf_id = client_with_workflow
        resp = await client.get(f"/workflow/{wf_id}/steps")
        assert resp.status_code == 200
        assert resp.json()["result"] == []

    async def test_add_step(self, client_with_workflow):
        client, wf_id = client_with_workflow
        types = (await client.get("/workflow_step/list")).json()["result"]
        type_id = types[0]["id"]

        resp = await client.post(f"/workflow/{wf_id}/step", json={"type_id": type_id})
        assert resp.status_code == 200
        step_id = resp.json()["result"]
        assert isinstance(step_id, int)

        steps = (await client.get(f"/workflow/{wf_id}/steps")).json()["result"]
        assert len(steps) == 1
        assert steps[0]["id"] == step_id
        assert steps[0]["type_id"] == type_id

    async def test_step_has_required_fields(self, client_with_workflow):
        client, wf_id = client_with_workflow
        types = (await client.get("/workflow_step/list")).json()["result"]
        await client.post(f"/workflow/{wf_id}/step", json={"type_id": types[0]["id"]})

        steps = (await client.get(f"/workflow/{wf_id}/steps")).json()["result"]
        step = steps[0]
        for field in ("id", "workflow_id", "type_id", "title", "position", "metadata"):
            assert field in step, f"Missing field: {field}"

    async def test_update_step(self, client_with_workflow):
        client, wf_id = client_with_workflow
        types = (await client.get("/workflow_step/list")).json()["result"]
        step_id = (await client.post(f"/workflow/{wf_id}/step", json={"type_id": types[0]["id"]})).json()["result"]

        upd_resp = await client.put(f"/workflow/{wf_id}/step/{step_id}", json={"title": "Updated Step"})
        assert upd_resp.status_code == 200

        steps = (await client.get(f"/workflow/{wf_id}/steps")).json()["result"]
        assert steps[0]["title"] == "Updated Step"

    async def test_add_multiple_steps_increments_position(self, client_with_workflow):
        client, wf_id = client_with_workflow
        types = (await client.get("/workflow_step/list")).json()["result"]
        type_id = types[0]["id"]

        await client.post(f"/workflow/{wf_id}/step", json={"type_id": type_id})
        await client.post(f"/workflow/{wf_id}/step", json={"type_id": type_id})
        await client.post(f"/workflow/{wf_id}/step", json={"type_id": type_id})

        steps = (await client.get(f"/workflow/{wf_id}/steps")).json()["result"]
        assert len(steps) == 3
        positions = [s["position"] for s in steps]
        assert positions == [0, 1, 2]

    async def test_delete_step(self, client_with_workflow):
        client, wf_id = client_with_workflow
        types = (await client.get("/workflow_step/list")).json()["result"]
        step_id = (await client.post(f"/workflow/{wf_id}/step", json={"type_id": types[0]["id"]})).json()["result"]

        del_resp = await client.delete(f"/workflow/{wf_id}/step/{step_id}")
        assert del_resp.status_code == 200

        steps = (await client.get(f"/workflow/{wf_id}/steps")).json()["result"]
        assert all(s["id"] != step_id for s in steps)

    async def test_delete_workflow_cascades_steps(self, client: httpx.AsyncClient = None):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            create_resp = await client.post("/workflow", json={
                "name": f"{TEST_WF_PREFIX}cascade",
                "title": "Cascade Test",
            })
            wf_id = create_resp.json()["result"]["id"]
            types = (await client.get("/workflow_step/list")).json()["result"]
            await client.post(f"/workflow/{wf_id}/step", json={"type_id": types[0]["id"]})
            await client.post(f"/workflow/{wf_id}/step", json={"type_id": types[0]["id"]})

            await client.delete(f"/workflow/{wf_id}")

            get_resp = await client.get(f"/workflow/{wf_id}")
            assert get_resp.json()["result"] is None

    # --- variables ---

    async def test_get_workflow_variables_empty(self, client_with_workflow):
        client, wf_id = client_with_workflow
        resp = await client.get(f"/workflow/{wf_id}/variables")
        assert resp.status_code == 200
        assert isinstance(resp.json()["result"], list)

    async def test_add_workflow_variable(self, client_with_workflow):
        client, wf_id = client_with_workflow
        resp = await client.post(f"/workflow/{wf_id}/variable", json={
            "name": f"test_var_{wf_id}",
            "type": "workflow",
            "default": "default_val",
        })
        assert resp.status_code == 200
        var_id = resp.json()["result"]
        assert isinstance(var_id, int)

        variables = (await client.get(f"/workflow/{wf_id}/variables")).json()["result"]
        names = [v["name"] for v in variables]
        assert f"test_var_{wf_id}" in names

    async def test_add_same_variable_twice_returns_same_id(self, client_with_workflow):
        client, wf_id = client_with_workflow
        var_name = f"test_dup_var_{wf_id}"
        resp1 = await client.post(f"/workflow/{wf_id}/variable", json={"name": var_name, "type": "workflow"})
        resp2 = await client.post(f"/workflow/{wf_id}/variable", json={"name": var_name, "type": "workflow"})
        assert resp1.json()["result"] == resp2.json()["result"]
