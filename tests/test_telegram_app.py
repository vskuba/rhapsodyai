"""
Telegram Mini App endpoint tests.

Tests cover:
- GET  /telegram-app/ping           (public, no auth)
- POST /telegram-app/auth           (access_token flow)
- GET  /telegram-app/agents         (requires telegram owner session)
- GET  /telegram-app/plans          (requires telegram owner session)
- GET  /telegram-app/plans/{id}     (requires telegram owner session)
- DELETE /telegram-app/plans/{id}   (requires telegram owner session)
- GET  /telegram-app/claude/sessions/active  (requires telegram owner session)
- GET  /telegram-app/claude/messages         (requires telegram owner session)
- POST /telegram-app/claude/ask              (bad input validation)
- Unauthorized access (no session → 403)
"""
import os
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# Seeded access token for admin user (user_id=1) — inserted in migration 0002.sql
ADMIN_ACCESS_TOKEN = "a0000000-1111-4444-bbbb-000000000001"


class TestTelegramAppPing:
    """Ping is public — no auth required."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
            yield client

    async def test_ping_returns_ok(self, client: httpx.AsyncClient):
        response = await client.get("/telegram-app/ping")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_ping_is_fast(self, client: httpx.AsyncClient):
        import time
        start = time.monotonic()
        response = await client.get("/telegram-app/ping")
        elapsed = time.monotonic() - start
        assert response.status_code == 200
        assert elapsed < 1.0


class TestTelegramAppAuth:
    """Auth via access_token (Telegram initData path is skipped — no real bot token in tests)."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            yield client

    async def test_auth_with_valid_access_token(self, client: httpx.AsyncClient):
        response = await client.post(
            "/telegram-app/auth",
            json={"init_data": "", "access_token": ADMIN_ACCESS_TOKEN},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["ok"] is True

    async def test_auth_with_invalid_access_token(self, client: httpx.AsyncClient):
        response = await client.post(
            "/telegram-app/auth",
            json={"init_data": "", "access_token": "00000000-0000-0000-0000-000000000000"},
        )
        assert response.status_code == 403

    async def test_auth_without_any_credentials(self, client: httpx.AsyncClient):
        response = await client.post(
            "/telegram-app/auth",
            json={"init_data": "", "access_token": ""},
        )
        assert response.status_code == 403


class TestTelegramAppProtectedEndpoints:
    """Protected endpoints must return 403 without telegram_owner_id session."""

    @pytest.fixture
    async def anon_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            yield client

    async def test_agents_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/agents")
        assert response.status_code == 403

    async def test_plans_list_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/plans")
        assert response.status_code == 403

    async def test_plans_detail_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/plans/1")
        assert response.status_code == 403

    async def test_plans_delete_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.delete("/telegram-app/plans/1")
        assert response.status_code == 403

    async def test_claude_sessions_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/claude/sessions/active")
        assert response.status_code == 403

    async def test_claude_messages_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/claude/messages?session_uuid=test")
        assert response.status_code == 403

    async def test_claude_ask_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.post(
            "/telegram-app/claude/ask",
            json={"session_uuid": "abc", "message": "hello"},
        )
        assert response.status_code == 403


@pytest.fixture
async def telegram_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client authenticated via access_token as telegram owner."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        auth_response = await client.post(
            "/telegram-app/auth",
            json={"init_data": "", "access_token": ADMIN_ACCESS_TOKEN},
        )
        assert auth_response.status_code == 200, "Telegram auth failed — seeded token not found"
        yield client


class TestTelegramAppAgents:
    """Agents list available through Mini App."""

    async def test_get_agents_list(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/agents")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_agents_have_required_fields(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/agents")
        assert response.status_code == 200
        agents = response.json()["result"]
        for agent in agents:
            assert "id" in agent
            assert "name" in agent
            assert "title" in agent


class TestTelegramAppPlans:
    """Plans CRUD through Mini App — skips AI-dependent create/edit."""

    async def test_get_plans_list(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/plans")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_plans_list_fields(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/plans")
        plans = response.json()["result"]
        for plan in plans:
            assert "id" in plan
            assert "title" in plan
            assert "status" in plan

    async def test_get_nonexistent_plan(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/plans/999999")
        assert response.status_code == 404

    async def test_delete_nonexistent_plan(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.delete("/telegram-app/plans/999999")
        assert response.status_code == 404

    async def test_plan_create_requires_instruction(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.post(
            "/telegram-app/plans",
            json={"instruction": ""},
        )
        assert response.status_code == 400
        assert "Instruction is required" in response.json()["detail"]

    async def test_plan_edit_requires_instruction(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.post(
            "/telegram-app/plans/999999/edit",
            json={"instruction": ""},
        )
        # 400 (bad instruction) or 404 (plan not found) — both are correct
        assert response.status_code in (400, 404)


class TestTelegramAppClaude:
    """Claude session endpoints through Mini App."""

    async def test_get_active_sessions(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/claude/sessions/active")
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_get_claude_messages_empty_session(self, telegram_client: httpx.AsyncClient):
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = await telegram_client.get(
            f"/telegram-app/claude/messages?session_uuid={fake_uuid}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert data["result"] == []

    async def test_claude_ask_requires_session_uuid(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.post(
            "/telegram-app/claude/ask",
            json={"session_uuid": "", "message": "hello"},
        )
        assert response.status_code == 400
        assert "session_uuid" in response.json()["detail"].lower()

    async def test_claude_ask_requires_message(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.post(
            "/telegram-app/claude/ask",
            json={"session_uuid": "00000000-0000-0000-0000-000000000000", "message": ""},
        )
        assert response.status_code == 400
        assert "message" in response.json()["detail"].lower()

    async def test_active_sessions_fields(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/claude/sessions/active")
        sessions = response.json()["result"]
        for session in sessions:
            assert "session_uuid" in session
            assert "role" in session
            assert "project_label" in session


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
