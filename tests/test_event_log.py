"""
Event log endpoint tests.

Tests cover:
- GET  /events          (requires telegram owner session)
- DELETE /events        (requires telegram owner session)
- POST /event-log       (requires X-Claude-Secret header)
- Unauthorized access → 403
- POST /event-log with each event type (system, github, claude_session, agent, llm)
- Response structure validation
"""
import os
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
ADMIN_ACCESS_TOKEN = "a0000000-1111-4444-bbbb-000000000001"


@pytest.fixture
async def telegram_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client authenticated as telegram owner via access_token."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        auth = await client.post(
            "/telegram-app/auth",
            json={"init_data": "", "access_token": ADMIN_ACCESS_TOKEN},
        )
        assert auth.status_code == 200
        yield client


@pytest.fixture
async def anon_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        yield client


class TestEventLogAuth:
    """Auth enforcement for event endpoints."""

    async def test_get_events_requires_telegram_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/events")
        assert response.status_code == 403

    async def test_delete_events_requires_telegram_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.delete("/events")
        assert response.status_code == 403

    async def test_post_event_log_requires_claude_secret(self, anon_client: httpx.AsyncClient):
        payload = {
            "type": "system",
            "payload": {"event_type": "test"},
        }
        response = await anon_client.post("/event-log", json=payload)
        assert response.status_code == 403

    async def test_post_event_log_wrong_secret_rejected(self, anon_client: httpx.AsyncClient):
        payload = {
            "type": "system",
            "payload": {"event_type": "test"},
        }
        response = await anon_client.post(
            "/event-log",
            json=payload,
            headers={"X-Claude-Secret": "wrong-secret-value"},
        )
        assert response.status_code == 403


class TestEventLogRead:
    """Reading event log with telegram owner session."""

    async def test_get_events_returns_list(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_get_events_has_timezone(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert "timezone" in data
        assert isinstance(data["timezone"], str)

    async def test_get_events_max_50_items(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/events")
        assert response.status_code == 200
        events = response.json()["result"]
        assert len(events) <= 50

    async def test_events_have_required_fields(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/events")
        events = response.json()["result"]
        for event in events:
            assert "id" in event
            assert "type" in event
            assert "payload" in event
            assert "created_at" in event


class TestEventLogCreate:
    """Creating event_log entries via X-Claude-Secret.

    These tests call /event-log with the real secret loaded from the running server.
    If the server is started without TELEGRAM_TOKEN_RHAPSODY the tests are skipped.
    """

    # We use a module-level client with the secret injected from the environment.
    # In CI the server and the test process share the same .env, so we read it here.

    @pytest.fixture
    async def secret_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Client with X-Claude-Secret from .env if available."""
        import os
        secret = os.environ.get("TELEGRAM_TOKEN_RHAPSODY", "")
        if not secret:
            # Try to read from .env file in project root
            try:
                env_path = "/home/vasyl/PycharmProjects/RhapsodyAi/.env"
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("TELEGRAM_TOKEN_RHAPSODY="):
                            secret = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except OSError:
                pass

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            client.headers["X-Claude-Secret"] = secret
            client._test_secret = secret
            yield client

    async def test_create_system_event(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "system",
            "payload": {"event_type": "test.login", "user_id": 1, "username": "test_user", "role": "admin"},
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert data["result"]["type"] == "system"
        assert isinstance(data["result"]["id"], int)

    async def test_create_github_deploy_started(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "github",
            "payload": {
                "event": "deploy.started",
                "branch": "master",
                "commit": "abc123def456",
                "actor": "test_actor",
                "run_url": "https://github.com/test/repo/actions/runs/1",
            },
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["type"] == "github"

    async def test_create_github_deploy_finished(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "github",
            "payload": {
                "event": "deploy.finished",
                "branch": "master",
                "commit": "abc123def456",
                "actor": "test_actor",
                "run_url": "https://github.com/test/repo/actions/runs/1",
                "status": "success",
            },
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 200
        assert response.json()["result"]["type"] == "github"

    async def test_create_claude_session_event(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "claude_session",
            "payload": {
                "event_type": "session.start",
                "session_uuid": "test-uuid-1234",
                "project_label": "RhapsodyAi",
                "role": "developer",
            },
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 200
        assert response.json()["result"]["type"] == "claude_session"

    async def test_create_agent_event(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "agent",
            "payload": {
                "event_type": "agent.run",
                "agent_name": "telegram_assistant",
                "node_id": 1,
            },
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 200
        assert response.json()["result"]["type"] == "agent"

    async def test_create_llm_event(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "llm",
            "payload": {
                "event_type": "llm.call",
                "model": "claude-sonnet-4-6",
                "tokens_input": 100,
                "tokens_output": 50,
                "session_uuid": "test-session-uuid",
            },
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 200
        assert response.json()["result"]["type"] == "llm"

    async def test_event_log_invalid_type(self, secret_client: httpx.AsyncClient):
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        payload = {
            "type": "unknown_type",
            "payload": {"event_type": "test"},
        }
        response = await secret_client.post("/event-log", json=payload)
        assert response.status_code == 422

    async def test_created_event_appears_in_list(
        self,
        secret_client: httpx.AsyncClient,
        telegram_client: httpx.AsyncClient,
    ):
        """Created event should be visible in GET /events."""
        if not getattr(secret_client, "_test_secret", ""):
            pytest.skip("TELEGRAM_TOKEN_RHAPSODY not available")

        create_response = await secret_client.post(
            "/event-log",
            json={
                "type": "system",
                "payload": {"event_type": "test.visibility_check"},
            },
        )
        assert create_response.status_code == 200
        created_id = create_response.json()["result"]["id"]

        list_response = await telegram_client.get("/events")
        assert list_response.status_code == 200
        event_ids = [e["id"] for e in list_response.json()["result"]]
        assert created_id in event_ids


class TestEventLogDelete:
    """Clearing event log."""

    async def test_delete_events_returns_ok(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.delete("/events")
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["ok"] is True

    async def test_get_events_empty_after_delete(self, telegram_client: httpx.AsyncClient):
        # Clear first
        await telegram_client.delete("/events")

        response = await telegram_client.get("/events")
        assert response.status_code == 200
        assert response.json()["result"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
