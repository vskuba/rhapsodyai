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
            await client.delete(f"/setting/key/{TEST_SETTING_KEY}")
            yield client
            await client.delete(f"/setting/key/{TEST_SETTING_KEY}")

    async def test_setting_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/setting/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_setting_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/setting/list")
            assert resp.status_code in (401, 403)

    async def test_setting_list_items_have_required_fields(self, client: httpx.AsyncClient):
        resp = await client.get("/setting/list")
        items = resp.json()["result"]
        if items:
            item = items[0]
            assert "id" in item
            assert "key" in item
            assert "value" in item

    async def test_setting_save_and_read(self, client: httpx.AsyncClient):
        resp = await client.post("/setting", json={"key": TEST_SETTING_KEY, "value": "hello_world"})
        assert resp.status_code == 200
        assert resp.json()["result"] is True

        # появляется в списке
        list_resp = await client.get("/setting/list")
        keys = [s["key"] for s in list_resp.json()["result"]]
        assert TEST_SETTING_KEY in keys

    async def test_setting_update_value(self, client: httpx.AsyncClient):
        await client.post("/setting", json={"key": TEST_SETTING_KEY, "value": "first"})
        await client.post("/setting", json={"key": TEST_SETTING_KEY, "value": "second"})

        settings = (await client.get("/setting/list")).json()["result"]
        match = next((s for s in settings if s["key"] == TEST_SETTING_KEY), None)
        assert match is not None
        assert match["value"] == "second"

    async def test_setting_empty_value_deletes(self, client: httpx.AsyncClient):
        await client.post("/setting", json={"key": TEST_SETTING_KEY, "value": "to_delete"})

        resp = await client.post("/setting", json={"key": TEST_SETTING_KEY, "value": ""})
        assert resp.status_code == 200

        settings = (await client.get("/setting/list")).json()["result"]
        keys = [s["key"] for s in settings]
        assert TEST_SETTING_KEY not in keys

    async def test_setting_delete_key(self, client: httpx.AsyncClient):
        await client.post("/setting", json={"key": TEST_SETTING_KEY, "value": "delete_me"})

        del_resp = await client.delete(f"/setting/key/{TEST_SETTING_KEY}")
        assert del_resp.status_code == 200
        assert del_resp.json()["result"] is True

        settings = (await client.get("/setting/list")).json()["result"]
        keys = [s["key"] for s in settings]
        assert TEST_SETTING_KEY not in keys

    async def test_setting_save_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.post("/setting", json={"key": TEST_SETTING_KEY, "value": "x"})
            assert resp.status_code in (401, 403)

    async def test_setting_delete_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.delete(f"/setting/key/{TEST_SETTING_KEY}")
            assert resp.status_code in (401, 403)

    async def test_setting_save_empty_key_rejected(self, client: httpx.AsyncClient):
        resp = await client.post("/setting", json={"key": "", "value": "val"})
        assert resp.status_code == 400

    async def test_user_setting_save_and_read(self, client: httpx.AsyncClient):
        # Получаем id admin-пользователя
        me_resp = await client.get("/auth/me")
        assert me_resp.status_code == 200
        user_id = me_resp.json()["user"]["id"]

        save_resp = await client.post(
            f"/setting/{TEST_SETTING_KEY}/user/{user_id}",
            json={"value": "user_value"}
        )
        assert save_resp.status_code == 200

        get_resp = await client.get(f"/setting/{TEST_SETTING_KEY}/user/{user_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["result"] == "user_value"

    async def test_user_setting_not_in_global_list(self, client: httpx.AsyncClient):
        me_resp = await client.get("/auth/me")
        user_id = me_resp.json()["user"]["id"]
        await client.post(f"/setting/{TEST_SETTING_KEY}/user/{user_id}", json={"value": "hidden"})

        settings = (await client.get("/setting/list")).json()["result"]
        keys = [s["key"] for s in settings]
        assert TEST_SETTING_KEY not in keys
