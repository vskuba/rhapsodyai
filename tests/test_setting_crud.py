import os
from tests.constants import TEST_AUTH
"""Setting CRUD tests — /setting endpoints."""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.core

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_SETTING_KEY = "test_setting_key_pytest"


class TestSettingCRUD:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            await client.delete(f"/api/setting/{TEST_SETTING_KEY}")
            yield client
            await client.delete(f"/api/setting/{TEST_SETTING_KEY}")

    async def test_setting_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/api/setting")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        # ⚠ Список лежит под `settings`: форма общего скелета панели
        # (`panel_setting_api`), одна на все проекты.
        assert isinstance(data["result"]["settings"], list)

    async def test_setting_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/api/setting")
            assert resp.status_code in (401, 403)

    async def test_setting_list_items_have_required_fields(self, client: httpx.AsyncClient):
        resp = await client.get("/api/setting")
        items = resp.json()["result"]["settings"]
        if items:
            item = items[0]
            assert "id" in item
            assert "key" in item
            assert "value" in item

    async def test_setting_save_and_read(self, client: httpx.AsyncClient):
        resp = await client.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": "hello_world"})
        assert resp.status_code == 200
        assert resp.json()["result"] == 'ok'

        # появляется в списке
        list_resp = await client.get("/api/setting")
        keys = [s["key"] for s in list_resp.json()["result"]["settings"]]
        assert TEST_SETTING_KEY in keys

    async def test_setting_update_value(self, client: httpx.AsyncClient):
        await client.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": "first"})
        await client.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": "second"})

        settings = (await client.get("/api/setting")).json()["result"]["settings"]
        match = next((s for s in settings if s["key"] == TEST_SETTING_KEY), None)
        assert match is not None
        assert match["value"] == "second"

    async def test_setting_empty_value_deletes(self, client: httpx.AsyncClient):
        await client.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": "to_delete"})

        resp = await client.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": ""})
        assert resp.status_code == 200

        settings = (await client.get("/api/setting")).json()["result"]["settings"]
        keys = [s["key"] for s in settings]
        assert TEST_SETTING_KEY not in keys

    async def test_setting_delete_key(self, client: httpx.AsyncClient):
        await client.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": "delete_me"})

        del_resp = await client.delete(f"/api/setting/{TEST_SETTING_KEY}")
        assert del_resp.status_code == 200
        assert del_resp.json()["result"] == 'ok'

        settings = (await client.get("/api/setting")).json()["result"]["settings"]
        keys = [s["key"] for s in settings]
        assert TEST_SETTING_KEY not in keys

    async def test_setting_save_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.post("/api/setting", json={"key": TEST_SETTING_KEY, "value": "x"})
            assert resp.status_code in (401, 403)

    async def test_setting_delete_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.delete(f"/api/setting/{TEST_SETTING_KEY}")
            assert resp.status_code in (401, 403)

    async def test_setting_save_empty_key_rejected(self, client: httpx.AsyncClient):
        resp = await client.post("/api/setting", json={"key": "", "value": "val"})
        # ⚠ 422, а не 400: пустой ключ это непрошедшая проверка тела
        # запроса, и общий скелет отвечает на такое кодом разбора.
        assert resp.status_code == 422

    async def test_user_setting_save_and_read(self, client: httpx.AsyncClient):
        # Получаем id admin-пользователя
        me_resp = await client.get("/auth/me")
        assert me_resp.status_code == 200
        user_id = me_resp.json()["user"]["id"]

        save_resp = await client.post(
            f"/api/setting/{TEST_SETTING_KEY}/user/{user_id}",
            json={"value": "user_value"}
        )
        assert save_resp.status_code == 200

        get_resp = await client.get(f"/api/setting/{TEST_SETTING_KEY}/user/{user_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["result"] == "user_value"

    async def test_user_setting_not_in_global_list(self, client: httpx.AsyncClient):
        me_resp = await client.get("/auth/me")
        user_id = me_resp.json()["user"]["id"]
        await client.post(f"/api/setting/{TEST_SETTING_KEY}/user/{user_id}", json={"value": "hidden"})

        settings = (await client.get("/api/setting")).json()["result"]["settings"]
        keys = [s["key"] for s in settings]
        assert TEST_SETTING_KEY not in keys
