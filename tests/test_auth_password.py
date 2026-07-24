"""Auth profile and password change tests — PUT /auth/me, PUT /auth/me/password, GET /auth/me/languages."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = "http://localhost:8011"
TEST_USER_PREFIX = "test_pwdchg_"


class TestAuthPassword:

    @pytest.fixture
    async def admin(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
            yield client

    @pytest.fixture
    async def temp_user(self, admin: httpx.AsyncClient):
        """Creates a temporary non-admin user, yields (username, password), cleans up after."""
        username = f"{TEST_USER_PREFIX}user"
        password = "Password123!"

        # Pre-cleanup: remove any leftover from a failed previous run
        try:
            users = (await admin.get("/user/list")).json().get("result", [])
            for u in users:
                if u.get("username") == username:
                    await admin.delete(f"/user/{u['id']}")
        except Exception:
            pass

        resp = await admin.post("/user", json={
            "username": username,
            "email": f"{username}@test.local",
            "password": password,
            "node_ids": [],
        })
        assert resp.status_code == 200
        user_id = resp.json()["result"]["id"]

        yield username, password, user_id

        await admin.delete(f"/user/{user_id}")

    # --- GET /auth/me/languages ---

    async def test_me_languages_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/auth/me/languages")
            assert resp.status_code in (401, 403)

    async def test_me_languages_returns_structure(self, admin: httpx.AsyncClient):
        resp = await admin.get("/auth/me/languages")
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "languages" in result
        assert "current" in result
        assert isinstance(result["languages"], list)

    # --- PUT /auth/me (profile update) ---

    async def test_update_profile_email(self, temp_user):
        username, password, user_id = temp_user
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": username, "password": password})
            resp = await client.put("/auth/me", json={"email": f"new_{username}@test.local"})
            assert resp.status_code == 200
            data = resp.json()
            assert "user" in data
            assert data["user"]["email"] == f"new_{username}@test.local"

    async def test_update_profile_missing_email_rejected(self, temp_user):
        username, password, _ = temp_user
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": username, "password": password})
            resp = await client.put("/auth/me", json={"language": "ru"})
            assert resp.status_code == 400

    async def test_update_profile_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.put("/auth/me", json={"email": "x@x.com"})
            assert resp.status_code in (401, 403)

    # --- PUT /auth/me/password ---

    async def test_change_password_success(self, temp_user):
        username, old_password, _ = temp_user
        new_password = "NewPassword456!"

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": username, "password": old_password})
            resp = await client.put("/auth/me/password", json={
                "password_current": old_password,
                "password_new": new_password,
            })
            assert resp.status_code == 200
            assert "message" in resp.json()

        # Verify login with new password works
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            login_resp = await client.post("/auth/login", json={"username": username, "password": new_password})
            assert login_resp.status_code == 200

        # Verify old password no longer works
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            login_resp = await client.post("/auth/login", json={"username": username, "password": old_password})
            assert login_resp.status_code == 401

    async def test_change_password_wrong_current_rejected(self, temp_user):
        username, password, _ = temp_user
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": username, "password": password})
            resp = await client.put("/auth/me/password", json={
                "password_current": "WrongPassword!",
                "password_new": "NewPassword456!",
            })
            assert resp.status_code == 401

    async def test_change_password_too_short_rejected(self, temp_user):
        username, password, _ = temp_user
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": username, "password": password})
            resp = await client.put("/auth/me/password", json={
                "password_current": password,
                "password_new": "short",
            })
            assert resp.status_code == 400

    async def test_change_password_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.put("/auth/me/password", json={
                "password_current": "old",
                "password_new": "newpassword123",
            })
            assert resp.status_code in (401, 403)

    async def test_change_password_empty_new_rejected(self, temp_user):
        username, password, _ = temp_user
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json={"username": username, "password": password})
            resp = await client.put("/auth/me/password", json={
                "password_current": password,
                "password_new": "",
            })
            assert resp.status_code == 400
