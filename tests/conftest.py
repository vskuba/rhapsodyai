"""Pytest configuration for RhapsodyAi tests."""
import pytest
import asyncio
import httpx
import uuid
from typing import AsyncGenerator

from tests.constants import TEST_SESSION_UUID, TEST_SESSION_AGENT_ID


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Configure pytest-asyncio for async fixtures
pytestmark = pytest.mark.asyncio


def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring running services"
    )


BASE_URL = "http://localhost:8011"
TEST_USER_PREFIX = "test_"
TEST_AGENT_PREFIX = "test_agent_"


async def _cleanup_test_users(client: httpx.AsyncClient) -> None:
    """Delete all users with username starting with TEST_USER_PREFIX."""
    try:
        response = await client.get("/user/list")
        if response.status_code != 200:
            return
        users = response.json().get("result", [])
        test_users = [u for u in users if u.get("username", "").startswith(TEST_USER_PREFIX)]
        for user in test_users:
            try:
                await client.delete(f"/user/{user['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


async def _cleanup_test_agents(client: httpx.AsyncClient) -> None:
    """Delete all agents with name starting with TEST_AGENT_PREFIX."""
    try:
        response = await client.get("/agent/list")
        if response.status_code != 200:
            return
        agents = response.json().get("result", [])
        test_agents = [a for a in agents if a.get("name", "").startswith(TEST_AGENT_PREFIX)]
        for agent in test_agents:
            try:
                await client.delete(f"/agent/{agent['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


TEST_ROLE_NAMES = ("test_role", "updated_role")


async def _cleanup_test_roles(client: httpx.AsyncClient) -> None:
    """Delete leftover roles created by test_role_crud.py."""
    try:
        response = await client.get("/role/list")
        if response.status_code != 200:
            return
        roles = response.json().get("result", [])
        test_roles = [r for r in roles if r.get("name") in TEST_ROLE_NAMES]
        for role in test_roles:
            try:
                await client.delete(f"/role/{role['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_users() -> AsyncGenerator[None, None]:
    """Session-scoped fixture to clean up test users before and after all tests."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)
    yield
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)


@pytest.fixture(scope="session", autouse=True)
def seed_test_session():
    """Seed a known agent_session row used by session tests, clean up after."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    # Tests run from host; override Docker service name with localhost port
    os.environ['MYSQL_HOST'] = 'localhost'
    os.environ['MYSQL_PORT'] = '3302'

    from src.ai.ai_session import ai_session_message_add
    from mysql_.mysql_ import mysql_get_db_async

    req_uuid = str(uuid.uuid4())

    async def _seed():
        await ai_session_message_add(TEST_SESSION_UUID, req_uuid, None, 1, None,
                                     'user', TEST_SESSION_AGENT_ID, 'user-prompt', 'test prompt')
        await ai_session_message_add(TEST_SESSION_UUID, req_uuid, None, 1, None,
                                     'assistant', TEST_SESSION_AGENT_ID, 'response-final', 'test response')

    from mysql_.mysql_ import mysql_pool_close

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_seed())
    loop.run_until_complete(mysql_pool_close())
    loop.close()

    yield

    async def _cleanup():
        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM agent_session WHERE session_uuid = %s", (TEST_SESSION_UUID,))
            await db.connection.commit()
        await mysql_pool_close()

    loop2 = asyncio.new_event_loop()
    loop2.run_until_complete(_cleanup())
    loop2.close()