"""
Session API endpoint tests.

Tests cover:
- POST /session/list (requires authentication)
- POST /session/last (requires authentication)
- POST /session/last/uuid (requires authentication)
- POST /session/messages (requires authentication)
- Unauthorized access handling
"""
import os
import pytest
import httpx
from typing import AsyncGenerator

from tests.constants import TEST_SESSION_UUID, TEST_SESSION_AGENT_ID, TEST_AUTH

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestSessionFlow:
    """Test the complete session API flow."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            # Login as standard user / admin first
            login_response = await client.post(
                "/auth/login",
                json=TEST_AUTH,
            )
            assert login_response.status_code == 200
            yield client

    async def test_session_endpoints_require_auth(self):
        """Test that session endpoints return 401 when unauthenticated."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False) as client:
            # 1. Test /session/list
            list_response = await client.post("/session/list", json={})
            assert list_response.status_code == 401

            # 2. Test /session/last
            last_response = await client.post("/session/last", json={})
            assert last_response.status_code == 401

            # 3. Test /session/last/uuid
            last_uuid_response = await client.post("/session/last/uuid", json={})
            assert last_uuid_response.status_code == 401

            # 4. Test /session/messages
            messages_response = await client.post(
                "/session/messages",
                json={"session_uuid": "097824c7-c3d3-4925-a63f-bd685292a408"},
            )
            assert messages_response.status_code == 401

    async def test_session_list(self, client: httpx.AsyncClient):
        """Test listing sessions with and without filters."""
        # 1. Get all sessions
        response = await client.post("/session/list", json={})
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)
        assert len(data["result"]) > 0

        # Check fields of the session item
        first_session = data["result"][0]
        assert "session_uuid" in first_session
        assert "role" in first_session
        assert "kind_type" in first_session
        assert "last_message_at" in first_session
        assert "msg_count" in first_session

        # 2. Get sessions with filters (matching seeded values)
        filtered_response = await client.post(
            "/session/list",
            json={"agent_id": TEST_SESSION_AGENT_ID, "user_id": 1},
        )
        assert filtered_response.status_code == 200
        filtered_data = filtered_response.json()
        assert len(filtered_data["result"]) > 0

    async def test_session_last(self, client: httpx.AsyncClient):
        """Test retrieving the last session with and without filters."""
        # 1. Get last session without filters
        response = await client.post("/session/last", json={})
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        last_session = data["result"]
        assert last_session is not None
        assert "session_uuid" in last_session
        assert "role" in last_session
        assert "kind_type" in last_session
        assert "last_message_at" in last_session
        assert "msg_count" in last_session

        # 2. Get last session with specific filters
        filtered_response = await client.post(
            "/session/last",
            json={"agent_id": TEST_SESSION_AGENT_ID, "user_id": 1},
        )
        assert filtered_response.status_code == 200
        filtered_data = filtered_response.json()
        assert filtered_data["result"] is not None
        assert filtered_data["result"]["session_uuid"] == TEST_SESSION_UUID

        # 3. Get last session with filters that yield no results
        no_match_response = await client.post(
            "/session/last",
            json={"agent_id": 999999},
        )
        assert no_match_response.status_code == 200
        no_match_data = no_match_response.json()
        assert no_match_data["result"] is None

    async def test_session_last_uuid(self, client: httpx.AsyncClient):
        """Test retrieving only the last session's UUID with and without filters."""
        # 1. Get last session UUID without filters
        response = await client.post("/session/last/uuid", json={})
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], str) or data["result"] is None
        if data["result"]:
            assert len(data["result"]) == 36  # standard UUID string length

        # 2. Get last session UUID with specific filters (matching seeded values)
        filtered_response = await client.post(
            "/session/last/uuid",
            json={"agent_id": TEST_SESSION_AGENT_ID, "user_id": 1},
        )
        assert filtered_response.status_code == 200
        filtered_data = filtered_response.json()
        assert filtered_data["result"] == TEST_SESSION_UUID

        # 3. Get last session UUID with filters that yield no results
        no_match_response = await client.post(
            "/session/last/uuid",
            json={"agent_id": 999999},
        )
        assert no_match_response.status_code == 200
        no_match_data = no_match_response.json()
        assert no_match_data["result"] is None

    async def test_session_messages(self, client: httpx.AsyncClient):
        """Test retrieving messages for a specific session UUID."""
        response = await client.post(
            "/session/messages",
            json={"session_uuid": TEST_SESSION_UUID},
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert isinstance(data["result"], list)
        assert len(data["result"]) > 0

        # Verify message fields
        first_msg = data["result"][0]
        assert first_msg["session_uuid"] == TEST_SESSION_UUID
        assert "role" in first_msg
        assert "content" in first_msg
