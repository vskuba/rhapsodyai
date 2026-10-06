"""
Ветки: заведение, правка, удаление.

HTTP-часть идёт на стенд — ручки это контракт, и проверять их вызовом функций
значило бы не проверить ни маршрут, ни права.

⚠ Ветки заводятся на ноде, которой нет (`999343`): реестр живой ноды Dating тест
не трогает, а уборка сводится к удалению своих веток.

⚠ Клиент здесь обычный `httpx.AsyncClient`, а не общий транспорт из `http_pool`:
тот нужен боевому коду, где клиент разовый из-за своих cookie, а рукопожатий
сотни. Здесь один клиент на тест против localhost, и закрывать его можно —
клиенту с общим транспортом `aclose()` как раз запрещён.
"""

import os

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_BRANCH_PREFIX = 'test_branch_'
TEST_NODE_ID = 999343


async def _sweep(client: httpx.AsyncClient) -> None:
    listing = await client.get(f"/workflow_branch/list?node_id={TEST_NODE_ID}")
    if listing.status_code != 200:
        return
    for branch in listing.json().get("result", []):
        if str(branch.get("name", "")).startswith(TEST_BRANCH_PREFIX):
            await client.delete(f"/workflow_branch/{branch['id']}")


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=30.0) as client:
        await client.post("/auth/login", json=TEST_AUTH)
        # ⚠ Уборка идёт и ДО прогона: от Ctrl-C и упавшего теста хвост остаётся
        # именно тогда, когда «убрать в конце» не срабатывает
        await _sweep(client)
        yield client
        await _sweep(client)


async def _branch_make(client: httpx.AsyncClient, name: str, **extra) -> dict:
    body = {"node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}{name}",
            "title": name, **extra}
    response = await client.post("/workflow_branch", json=body)
    assert response.status_code == 200, response.text
    return response.json()["result"]


class TestBranchCrud:
    async def test_create_and_read(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'deal', title='Договориться')
        assert branch["title"] == 'Договориться'
        assert branch["node_id"] == TEST_NODE_ID

        listing = await client.get(f"/workflow_branch/list?node_id={TEST_NODE_ID}")
        names = [row["name"] for row in listing.json()["result"]]
        assert f"{TEST_BRANCH_PREFIX}deal" in names

    async def test_match_min_default_is_one(self, client: httpx.AsyncClient):
        """⚠ Умолчание порога — единица: одна совпавшая метка уже что-то значит."""
        branch = await _branch_make(client, 'default_min')
        assert branch["match_min"] == 1

    async def test_subflow_is_optional(self, client: httpx.AsyncClient):
        """Ветка без subflow — основной случай: она «сужает» общий ответ."""
        branch = await _branch_make(client, 'inline')
        assert branch["workflow_id"] is None

    async def test_name_is_unique_in_node(self, client: httpx.AsyncClient):
        await _branch_make(client, 'twice')
        clash = await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}twice", "title": "Дубль",
        })
        assert clash.status_code == 400
        assert 'уже есть' in clash.json()["detail"]

    async def test_update_changes_threshold(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'strict')
        response = await client.put(f"/workflow_branch/{branch['id']}", json={"match_min": 3})
        assert response.status_code == 200
        assert response.json()["result"]["match_min"] == 3

    async def test_update_does_not_touch_node(self, client: httpx.AsyncClient):
        """⚠ `node_id` правит сервер: присланное поле не должно его достать."""
        branch = await _branch_make(client, 'node_guard')
        response = await client.put(f"/workflow_branch/{branch['id']}",
                                    json={"node_id": 1, "title": "Переехала?"})
        assert response.status_code == 200
        assert response.json()["result"]["node_id"] == TEST_NODE_ID

    async def test_delete_removes_branch(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'gone')
        assert (await client.delete(f"/workflow_branch/{branch['id']}")).status_code == 200

        listing = await client.get(f"/workflow_branch/list?node_id={TEST_NODE_ID}")
        names = [row["name"] for row in listing.json()["result"]]
        assert f"{TEST_BRANCH_PREFIX}gone" not in names

    async def test_unknown_branch_is_404(self, client: httpx.AsyncClient):
        assert (await client.put("/workflow_branch/99999343",
                                 json={"title": "нет такой"})).status_code == 404
