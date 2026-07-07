"""Pytest configuration for RhapsodyAi tests."""
import pytest
import asyncio
import httpx
from typing import AsyncGenerator


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
    # Clean up before tests
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)
    yield
    # Clean up after tests
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)