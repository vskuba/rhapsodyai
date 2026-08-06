"""Planning CRUD and tool tests.

Covers:
- Project CRUD lifecycle (create / list / get / update / delete)
- Phase list and per-phase retry
- Document endpoints (list, get, download MD/PDF)
- Ideas endpoints (validation, bulk-create)
- Cronicle schedule endpoint
- Auth enforcement on all key endpoints
- Tool functions: planning_project_score_save, project_load,
  planning_phase_save, planning_phase_document_save, planning_phase_blueprint_load
"""
import asyncio
import os
import pytest
import httpx
from typing import AsyncGenerator

from dotenv import load_dotenv

from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = "http://localhost:8011"
_TEST_IDEA = "__pytest_planning_test_idea__"
_TEST_TITLE = "__pytest_planning_test__"
_TEST_USERNAME = TEST_AUTH["username"]
_TEST_PASSWORD = TEST_AUTH["password"]


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _login(client: httpx.AsyncClient) -> None:
    await client.post("/auth/login", json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD})


async def _create_project(client: httpx.AsyncClient) -> int:
    resp = await client.post("/planning/project", json={"title": _TEST_TITLE, "idea": _TEST_IDEA})
    assert resp.status_code == 200
    return int(resp.json()["result"])


async def _delete_project(client: httpx.AsyncClient, project_id: int) -> None:
    await client.delete(f"/planning/project/{project_id}")


# ─── Project CRUD ─────────────────────────────────────────────────────────────

class TestPlanningProjectCRUD:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as c:
            await _login(c)
            yield c

    @pytest.fixture
    async def project_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        pid = await _create_project(client)
        yield pid
        await _delete_project(client, pid)

    async def test_create_project_returns_id(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/project", json={"title": _TEST_TITLE, "idea": _TEST_IDEA})
        assert resp.status_code == 200
        pid = resp.json().get("result")
        assert isinstance(pid, int) and pid > 0
        await _delete_project(client, pid)

    async def test_create_project_without_title_uses_idea(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/project", json={"idea": _TEST_IDEA})
        assert resp.status_code == 200
        pid = resp.json().get("result")
        assert isinstance(pid, int) and pid > 0
        proj = (await client.get(f"/planning/project/{pid}")).json()["result"]
        assert proj["title"] == _TEST_IDEA[:80]
        await _delete_project(client, pid)

    async def test_create_project_missing_idea_returns_error(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/project", json={"title": "no idea"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    async def test_list_projects_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/planning/project/list")
        assert resp.status_code == 200
        assert isinstance(resp.json()["result"], list)

    async def test_created_project_appears_in_list(self, client: httpx.AsyncClient, project_id: int):
        projects = (await client.get("/planning/project/list")).json()["result"]
        ids = [p["id"] for p in projects]
        assert project_id in ids

    async def test_get_project_returns_fields(self, client: httpx.AsyncClient, project_id: int):
        resp = await client.get(f"/planning/project/{project_id}")
        assert resp.status_code == 200
        proj = resp.json()["result"]
        for field in ("id", "title", "idea", "status", "phase_current"):
            assert field in proj
        assert proj["idea"] == _TEST_IDEA
        assert proj["status"] == "pending"

    async def test_update_project_title(self, client: httpx.AsyncClient, project_id: int):
        new_title = _TEST_TITLE + "_upd"
        resp = await client.put(f"/planning/project/{project_id}", json={"title": new_title})
        assert resp.status_code == 200
        proj = (await client.get(f"/planning/project/{project_id}")).json()["result"]
        assert proj["title"] == new_title

    async def test_update_project_idea(self, client: httpx.AsyncClient, project_id: int):
        new_idea = _TEST_IDEA + "_updated"
        await client.put(f"/planning/project/{project_id}", json={"idea": new_idea})
        proj = (await client.get(f"/planning/project/{project_id}")).json()["result"]
        assert proj["idea"] == new_idea

    async def test_delete_project_removes_it(self, client: httpx.AsyncClient):
        pid = await _create_project(client)
        resp = await client.delete(f"/planning/project/{pid}")
        assert resp.status_code == 200
        # After delete the project should not appear in list
        projects = (await client.get("/planning/project/list")).json()["result"]
        assert not any(p["id"] == pid for p in projects)

    async def test_full_retry_resets_project(self, client: httpx.AsyncClient, project_id: int):
        # Set status to error manually via update
        await client.put(f"/planning/project/{project_id}", json={"status": "error"})
        resp = await client.post(f"/planning/project/{project_id}/retry")
        assert resp.status_code == 200
        proj = (await client.get(f"/planning/project/{project_id}")).json()["result"]
        # `retry` ставит `pending` и тут же кладёт проект в очередь, поэтому живой
        # воркер успевает перевести его в `processing` раньше, чем мы прочитаем статус.
        # Проверяем суть сброса: из `error` вышли и скоринг прошлого прогона стёрт.
        assert proj["status"] in ("pending", "processing")
        assert proj["score_total"] is None
        assert proj["score_verdict"] in (None, "")


# ─── Auth enforcement ─────────────────────────────────────────────────────────

class TestPlanningAuth:

    @pytest.fixture
    async def anon(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
            yield c

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as c:
            await _login(c)
            yield c

    @pytest.fixture
    async def project_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        pid = await _create_project(client)
        yield pid
        await _delete_project(client, pid)

    async def test_list_requires_auth(self, anon: httpx.AsyncClient):
        assert (await anon.get("/planning/project/list")).status_code in (401, 403)

    async def test_create_requires_auth(self, anon: httpx.AsyncClient):
        assert (await anon.post("/planning/project", json={"idea": "x"})).status_code in (401, 403)

    async def test_get_requires_auth(self, anon: httpx.AsyncClient, project_id: int):
        assert (await anon.get(f"/planning/project/{project_id}")).status_code in (401, 403)

    async def test_delete_requires_auth(self, anon: httpx.AsyncClient, project_id: int):
        assert (await anon.delete(f"/planning/project/{project_id}")).status_code in (401, 403)

    async def test_phases_requires_auth(self, anon: httpx.AsyncClient, project_id: int):
        assert (await anon.get(f"/planning/project/{project_id}/phases")).status_code in (401, 403)

    async def test_documents_requires_auth(self, anon: httpx.AsyncClient, project_id: int):
        assert (await anon.get(f"/planning/project/{project_id}/documents")).status_code in (401, 403)

    async def test_ideas_generate_requires_auth(self, anon: httpx.AsyncClient):
        assert (await anon.post("/planning/ideas/generate", json={"niche": "SaaS"})).status_code in (401, 403)

    async def test_ideas_bulk_create_requires_auth(self, anon: httpx.AsyncClient):
        assert (await anon.post("/planning/ideas/bulk-create", json={"ideas": []})).status_code in (401, 403)


# ─── Phase endpoints ──────────────────────────────────────────────────────────

class TestPlanningPhases:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as c:
            await _login(c)
            yield c

    @pytest.fixture
    async def project_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        pid = await _create_project(client)
        yield pid
        await _delete_project(client, pid)

    async def test_phases_list_returns_list(self, client: httpx.AsyncClient, project_id: int):
        resp = await client.get(f"/planning/project/{project_id}/phases")
        assert resp.status_code == 200
        assert isinstance(resp.json()["result"], list)

    async def test_phases_list_empty_for_new_project(self, client: httpx.AsyncClient, project_id: int):
        phases = (await client.get(f"/planning/project/{project_id}/phases")).json()["result"]
        assert phases == []

    async def test_phase_retry_valid_phase(self, client: httpx.AsyncClient, project_id: int):
        resp = await client.post(f"/planning/project/{project_id}/phase/analyze/retry")
        assert resp.status_code == 200
        assert resp.json()["result"] == project_id

    async def test_phase_retry_invalid_phase_returns_400(self, client: httpx.AsyncClient, project_id: int):
        resp = await client.post(f"/planning/project/{project_id}/phase/nonexistent_phase/retry")
        assert resp.status_code == 400

    async def test_phase_retry_all_valid_phases(self, client: httpx.AsyncClient, project_id: int):
        valid = ["analyze", "market", "product", "tech", "gtm", "financial", "blueprint", "score"]
        for phase in valid:
            resp = await client.post(f"/planning/project/{project_id}/phase/{phase}/retry")
            assert resp.status_code == 200, f"phase={phase} returned {resp.status_code}"

    async def test_phase_retry_supplement(self, client: httpx.AsyncClient, project_id: int):
        resp = await client.post(f"/planning/project/{project_id}/phase/supplement/retry")
        assert resp.status_code == 200

    async def test_phase_retry_resets_project_to_pending(self, client: httpx.AsyncClient, project_id: int):
        await client.put(f"/planning/project/{project_id}", json={"status": "error"})
        await client.post(f"/planning/project/{project_id}/phase/analyze/retry")
        proj = (await client.get(f"/planning/project/{project_id}")).json()["result"]
        assert proj["status"] == "pending"


# ─── Document endpoints ───────────────────────────────────────────────────────

class TestPlanningDocuments:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as c:
            await _login(c)
            yield c

    @pytest.fixture
    async def project_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        pid = await _create_project(client)
        yield pid
        await _delete_project(client, pid)

    async def test_documents_list_empty_for_new_project(self, client: httpx.AsyncClient, project_id: int):
        resp = await client.get(f"/planning/project/{project_id}/documents")
        assert resp.status_code == 200
        assert resp.json()["result"] == []

    async def test_document_get_nonexistent_returns_none(self, client: httpx.AsyncClient):
        resp = await client.get("/planning/document/999999")
        assert resp.status_code == 200
        assert resp.json()["result"] is None

    async def test_document_download_nonexistent_returns_404(self, client: httpx.AsyncClient):
        resp = await client.get("/planning/document/999999/download")
        assert resp.status_code == 404

    async def test_document_download_pdf_nonexistent_returns_404(self, client: httpx.AsyncClient):
        resp = await client.get("/planning/document/999999/download/pdf")
        assert resp.status_code == 404


# ─── Ideas endpoints ──────────────────────────────────────────────────────────

class TestPlanningIdeas:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as c:
            await _login(c)
            yield c

    async def test_generate_missing_niche_returns_error(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/ideas/generate", json={})
        assert resp.status_code == 200
        assert "error" in resp.json()

    async def test_generate_empty_niche_returns_error(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/ideas/generate", json={"niche": ""})
        assert resp.status_code == 200
        assert "error" in resp.json()

    async def test_bulk_create_empty_ideas_returns_error(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/ideas/bulk-create", json={"ideas": []})
        assert resp.status_code == 200
        assert "error" in resp.json()

    async def test_bulk_create_ideas_without_idea_field_skipped(self, client: httpx.AsyncClient):
        resp = await client.post("/planning/ideas/bulk-create", json={
            "ideas": [{"title": "No idea here"}]
        })
        assert resp.status_code == 200
        assert resp.json()["result"] == []

    async def test_bulk_create_creates_projects(self, client: httpx.AsyncClient):
        items = [
            {"title": "__pytest_bulk_1__", "idea": "__pytest_bulk_idea_1__"},
            {"title": "__pytest_bulk_2__", "idea": "__pytest_bulk_idea_2__"},
        ]
        resp = await client.post("/planning/ideas/bulk-create", json={"ideas": items})
        assert resp.status_code == 200
        created = resp.json()["result"]
        assert len(created) == 2
        assert all("id" in c for c in created)
        # cleanup
        for c in created:
            await client.delete(f"/planning/project/{c['id']}")


# ─── Cronicle schedule ────────────────────────────────────────────────────────

class TestPlanningCronicleSchedule:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as c:
            await _login(c)
            yield c

    async def test_schedule_returns_dict(self, client: httpx.AsyncClient):
        resp = await client.get("/planning/cronicle/schedule")
        assert resp.status_code == 200
        assert isinstance(resp.json()["result"], dict)


# ─── Tool unit tests ──────────────────────────────────────────────────────────

class TestPlanningTools:
    """Direct tests of planning tool functions via DB (no HTTP)."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ.setdefault("MYSQL_HOST", "localhost")
        os.environ.setdefault("MYSQL_PORT", "3302")

    @pytest.fixture
    def project_id(self) -> int:
        """Create a real project row and return its id; delete after test."""
        from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

        async def _create():
            async with mysql_get_db_async() as db:
                await db.execute(
                    "INSERT INTO project (node_id, user_id, title, idea, status, phase_current) "
                    "VALUES (9, 1, %s, %s, 'pending', '')",
                    (_TEST_TITLE, _TEST_IDEA)
                )
                pid = db.lastrowid
                await db.connection.commit()
            await mysql_pool_close()
            return pid

        async def _delete(pid):
            async with mysql_get_db_async() as db:
                await db.execute("DELETE FROM project_planning_phase    WHERE project_id = %s", (pid,))
                await db.execute("DELETE FROM project_planning_document WHERE project_id = %s", (pid,))
                await db.execute("DELETE FROM project  WHERE id = %s", (pid,))
                await db.connection.commit()
            await mysql_pool_close()

        loop = asyncio.new_event_loop()
        pid = loop.run_until_complete(_create())
        loop.close()

        yield pid

        loop2 = asyncio.new_event_loop()
        loop2.run_until_complete(_delete(pid))
        loop2.close()

    def _run(self, coro):
        from mysql_.mysql_ import mysql_pool_close
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(coro)
        finally:
            loop.run_until_complete(mysql_pool_close())
            loop.close()
        return result

    def test_project_load_returns_idea(self, project_id: int):
        from src.tool.project.project import project_load
        result = self._run(project_load(project_id))
        assert result["idea"] == _TEST_IDEA
        assert result["phases_context"] == ""

    def test_project_load_nonexistent_returns_empty(self):
        from src.tool.project.project import project_load
        result = self._run(project_load(999999))
        assert result["idea"] == ""
        assert result["phases_context"] == ""

    def test_phase_save_and_load(self, project_id: int):
        from src.tool.project.project import project_load
        from src.tool.project.planning.planning_phase import planning_phase_save
        phase_content = "## Test\n\nSome markdown content."

        async def _run():
            saved = await planning_phase_save(project_id, "analyze", phase_content)
            assert saved["saved"] == 1
            loaded = await project_load(project_id)
            assert "analyze" in loaded["phases_context"]
            assert phase_content in loaded["phases_context"]

        self._run(_run())

    def test_document_save_and_blueprint_load(self, project_id: int):
        from src.tool.project.planning.planning_phase import planning_phase_document_save, planning_phase_blueprint_load
        bp_content = "# Blueprint\n\nTest blueprint content."

        async def _run():
            saved = await planning_phase_document_save(project_id, "blueprint", "Blueprint", bp_content)
            assert saved["saved"] == 1
            assert isinstance(saved["doc_id"], int)
            loaded = await planning_phase_blueprint_load(project_id)
            assert loaded["blueprint_content"] == bp_content
            assert loaded["project_title"] == _TEST_TITLE

        self._run(_run())

    def test_blueprint_load_no_document_returns_empty(self, project_id: int):
        from src.tool.project.planning.planning_phase import planning_phase_blueprint_load
        result = self._run(planning_phase_blueprint_load(project_id))
        assert result["blueprint_content"] == ""
        assert result["project_title"] == _TEST_TITLE

    def test_score_save_stores_values(self, project_id: int):
        from src.tool.project.planning.planning_project import planning_project_score_save
        from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

        async def _run():
            saved = await planning_project_score_save(
                project_id, 8, 7, 6, "go", "50K-200K", "6-9 months", "Strong market, execution risk."
            )
            assert saved["saved"] == 1
            async with mysql_get_db_async() as db:
                await db.execute(
                    "SELECT score_market, score_feasibility, score_financial, score_total, score_verdict "
                    "FROM project WHERE id = %s", (project_id,)
                )
                row = await db.fetchone()
            assert row["score_market"] == 8
            assert row["score_feasibility"] == 7
            assert row["score_financial"] == 6
            assert row["score_total"] == 7  # round((8+7+6)/3)
            assert row["score_verdict"] == "go"
            await mysql_pool_close()

        self._run(_run())

    def test_score_save_clamps_values(self, project_id: int):
        from src.tool.project.planning.planning_project import planning_project_score_save
        from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

        async def _run():
            await planning_project_score_save(project_id, 15, -3, 11, "go", "", "", "")
            async with mysql_get_db_async() as db:
                await db.execute(
                    "SELECT score_market, score_feasibility, score_financial FROM project WHERE id = %s",
                    (project_id,)
                )
                row = await db.fetchone()
            await mysql_pool_close()
            assert row["score_market"] == 10
            assert row["score_feasibility"] == 1
            assert row["score_financial"] == 10

        self._run(_run())

    def test_score_save_invalid_verdict_defaults_to_maybe(self, project_id: int):
        from src.tool.project.planning.planning_project import planning_project_score_save
        from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

        async def _run():
            await planning_project_score_save(project_id, 5, 5, 5, "unknown_verdict", "", "", "")
            async with mysql_get_db_async() as db:
                await db.execute(
                    "SELECT score_verdict FROM project WHERE id = %s", (project_id,)
                )
                row = await db.fetchone()
            await mysql_pool_close()
            assert row["score_verdict"] == "maybe"

        self._run(_run())

    def test_phases_context_multiple_phases(self, project_id: int):
        from src.tool.project.project import project_load
        from src.tool.project.planning.planning_phase import planning_phase_save

        async def _run():
            await planning_phase_save(project_id, "analyze", "Analyze content")
            await planning_phase_save(project_id, "market", "Market content")
            loaded = await project_load(project_id)
            ctx = loaded["phases_context"]
            assert "analyze" in ctx
            assert "market" in ctx
            assert "Analyze content" in ctx
            assert "Market content" in ctx

        self._run(_run())
