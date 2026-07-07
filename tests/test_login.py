"""
Login/logout authentication tests.

Tests cover:
- Accessing protected routes without authentication (redirect to login)
- Login with valid credentials
- Login with invalid credentials
- /auth/me endpoint with valid session
- Logout functionality
- Accessing protected routes after logout
"""
import pytest
import httpx
from typing import AsyncGenerator


BASE_URL = "http://localhost:8011"


class TestLoginFlow:
    """Test the complete login/logout flow."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create an async HTTP client for testing."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            yield client

    async def test_protected_route_redirects_to_login(self, client: httpx.AsyncClient):
        """Test that accessing admin routes without auth redirects to login."""
        response = await client.get("/admin/agent")
        assert response.status_code == 307
        assert response.headers.get("location") == "/login"

    async def test_root_redirects_to_login(self, client: httpx.AsyncClient):
        """Test that accessing root without auth redirects to login."""
        response = await client.get("/")
        assert response.status_code == 307
        assert response.headers.get("location") == "/login"

    async def test_login_page_accessible(self, client: httpx.AsyncClient):
        """Test that login page is accessible without authentication."""
        response = await client.get("/login")
        assert response.status_code == 200
        assert "Авторизация | AI System" in response.text
        assert "Войти" in response.text

    async def test_login_with_valid_credentials(self, client: httpx.AsyncClient):
        """Test login with valid username and password."""
        response = await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Успешный вход! Сессия создана."
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"

        # Verify session cookie is set
        assert "uvicorn_session" in response.cookies

    async def test_login_with_invalid_credentials(self, client: httpx.AsyncClient):
        """Test login with wrong password returns 401."""
        response = await client.post(
            "/auth/login",
            json={"username": "admin", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    async def test_login_with_nonexistent_user(self, client: httpx.AsyncClient):
        """Test login with nonexistent user returns 401."""
        response = await client.post(
            "/auth/login",
            json={"username": "nonexistent", "password": "password"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    async def test_login_missing_credentials(self, client: httpx.AsyncClient):
        """Test login with missing username or password returns 400."""
        # Missing password
        response = await client.post(
            "/auth/login",
            json={"username": "admin"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Username and password required"

        # Missing username
        response = await client.post(
            "/auth/login",
            json={"password": "admin123"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Username and password required"

    async def test_auth_me_with_valid_session(self, client: httpx.AsyncClient):
        """Test /auth/me returns user info with valid session."""
        # First login
        login_response = await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_response.status_code == 200

        # Use the same client (cookies are automatically handled)
        response = await client.get("/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"
        assert isinstance(data["user"]["llm_ids"], list)
        assert len(data["user"]["llm_ids"]) > 0

    async def test_auth_me_without_session(self, client: httpx.AsyncClient):
        """Test /auth/me returns 401 without session."""
        # Create a fresh client without cookies
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as fresh_client:
            response = await fresh_client.get("/auth/me")
            assert response.status_code == 401
            data = response.json()
            assert data["status"] == "error"
            assert data["message"] == "Not authenticated"

    async def test_logout_clears_session(self, client: httpx.AsyncClient):
        """Test logout clears the session."""
        # First login
        login_response = await client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_response.status_code == 200

        # Logout (POST)
        response = await client.post("/auth/logout")
        assert response.status_code == 200
        assert response.json()["message"] == "Сессия успешно завершена."

        # Verify session cookie is cleared in response headers
        # httpx doesn't expose set-cookie in response.cookies for expired cookies
        # Check the Set-Cookie header directly
        set_cookie = response.headers.get("set-cookie", "")
        assert "uvicorn_session=null" in set_cookie or "uvicorn_session=" in set_cookie

    async def test_protected_route_after_logout(self, client: httpx.AsyncClient):
        """Test that accessing admin routes after logout redirects to login."""
        # Login first
        await client.post("/auth/login", json={"username": "admin", "password": "admin123"})

        # Logout (POST)
        await client.post("/auth/logout")

        # Try to access protected route
        response = await client.get("/admin/agent")
        assert response.status_code == 307
        assert response.headers.get("location") == "/login"

    async def test_static_files_accessible(self, client: httpx.AsyncClient):
        """Test that static files are accessible without authentication."""
        response = await client.get("/static/css/common.css")
        assert response.status_code == 200

    async def test_api_endpoint_returns_401_without_auth(self, client: httpx.AsyncClient):
        """Test that API endpoints return 401 without authentication."""
        response = await client.get("/agent/list")
        assert response.status_code == 401
        assert response.json()["message"] == "Not authenticated"


class TestLoginPageUI:
    """Test login page UI elements."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
            yield client

    async def test_login_page_has_form_elements(self, client: httpx.AsyncClient):
        """Test login page contains required form elements."""
        response = await client.get("/login")
        assert response.status_code == 200
        html = response.text

        # Check form elements
        assert 'id="loginForm"' in html
        assert 'id="username"' in html
        assert 'id="password"' in html
        assert 'id="loginBtn"' in html
        assert 'id="errorMessage"' in html

        # Check imports
        assert "/static/js/api.js" in html
        assert "/static/js/notification.js" in html

    async def test_login_page_has_styles(self, client: httpx.AsyncClient):
        """Test login page includes required stylesheets."""
        response = await client.get("/login")
        html = response.text

        assert "/static/css/common.css" in html
        assert "/static/css/menu_top.css" in html
        assert "/static/css/notification.css" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])