"""Кто зовёт подпоток: `GET /workflow/{id}/parents` знает оба рода вызова.

## ⚠⚠ Что здесь стережётся и какой ценой узнано

Подпоток зовут **два** рода шагов: `workflow_invoke` и `topic_action` (тема
уходит в подпоток со своими вопросами). Номер подпотока у обоих лежит в
`metadata` под ключом, равным имени типа шага.

Ручка «Вызывается из» отбирала шаги строкой `metadata LIKE '%workflow_invoke%'`
— то есть знала только первый род. Подпоток, который зовёт `topic_action`,
честно отвечал «Не используется ни одним workflow»: замерено на
`dating_talk_intention` (#76), которого прямо в тот момент звал шаг #816
«Ветка намерений» workflow `dating_talk`.

⚠ Беда тихая вдвойне: «не используется» — законный ответ для только что
заведённого подпотока, а человек по этому ответу решает, можно ли его удалить.

⚠ Отбор по **типу шага**, а не по подстроке в метаданных: тип лежит колонкой,
и слово `topic_action` внутри чужого текста его больше не подделает.

⚠ Клиент заводится прямо здесь, как у соседних сюит: общий пул слоя
(`http_pool_transport`) — про живые выходы в бою, а тесту нужна своя сессия с
логином и коротким сроком ожидания.
"""
import json
import os
import time

import httpx
import pytest

from src.ai.ai_workflow import WORKFLOW_SUBFLOW_STEP_TYPES
from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

RUN = int(time.time())
NODE_NAME = f"twsc_node_{RUN}"
WF_PARENT = f"twsc_parent_{RUN}"
WF_CHILD = f"twsc_child_{RUN}"
WF_INVOKED = f"twsc_child_inv_{RUN}"


@pytest.fixture
async def client():
    logged = httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0)
    response = await logged.post("/auth/login", json=TEST_AUTH)
    assert response.status_code == 200, response.text
    try:
        yield logged
    finally:
        await logged.aclose()


@pytest.fixture
async def probe(client: httpx.AsyncClient):
    built = await _build_probe(client)
    try:
        yield built
    finally:
        await _drop_probe(client, built)


def test_both_kinds_of_call_are_known():
    """⚠ Список родов вызова — один на весь проект, и в нём оба.

    Ручка, экспорт и сторож неопределённых переменных читают этот список.
    Появится третий род — чинить придётся в одном месте, а не искать по трём.
    """
    assert 'workflow_invoke' in WORKFLOW_SUBFLOW_STEP_TYPES
    assert 'topic_action' in WORKFLOW_SUBFLOW_STEP_TYPES


class TestSubflowCallers:
    """«Вызывается из» для обоих родов вызова."""

    async def test_topic_action_parent_is_found(self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Главный случай: подпоток зовёт `topic_action` — родитель найден.

        Именно здесь ручка отвечала «не используется ни одним workflow».
        """
        response = await client.get(f"/workflow/{probe['wf_child']}/parents")
        assert response.status_code == 200, response.text

        parents = response.json()["result"]
        assert [p["id"] for p in parents] == [probe["wf_parent"]], \
            'подпоток, который зовёт topic_action, остался без родителя'

    async def test_workflow_invoke_parent_still_found(self, client: httpx.AsyncClient, probe: dict):
        """⚠ Прежний род вызова не потерян правкой — он же основной."""
        response = await client.get(f"/workflow/{probe['wf_invoked']}/parents")
        assert response.status_code == 200, response.text

        parents = response.json()["result"]
        assert [p["id"] for p in parents] == [probe["wf_parent"]]

    async def test_a_number_inside_another_number_is_not_a_parent(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠ Хвост шаблона жив: номер 7 не находится внутри 76.

        Проверяем на номере-префиксе настоящего подпотока: родителя среди
        ответов быть не должно.
        """
        prefix = int(str(probe["wf_child"])[:-1] or 0)
        if prefix <= 0 or prefix == probe["wf_child"]:
            pytest.skip("номер подпотока однозначный — префикса для пробы нет")

        response = await client.get(f"/workflow/{prefix}/parents")
        assert response.status_code == 200, response.text
        assert probe["wf_parent"] not in {p["id"] for p in response.json()["result"]}


# ---------------------------------------------------------------------------
# Приватное: одноразовая нода с обоими родами вызова
# ---------------------------------------------------------------------------

async def _build_probe(client: httpx.AsyncClient) -> dict:
    """Нода, родитель с двумя шагами-вызовами и два подпотока."""
    node = await client.post("/node", json={"name": NODE_NAME, "position": 913})
    assert node.status_code == 200, node.text
    created = node.json()["result"]
    node_id = created["id"] if isinstance(created, dict) else created

    for name, position in ((WF_PARENT, 1), (WF_CHILD, 2), (WF_INVOKED, 3)):
        response = await client.post("/workflow", json={
            "name": name, "title": f"Probe {name}", "node_id": node_id, "position": position})
        assert response.status_code == 200, response.text

    names = {row["name"]: row["id"]
             for row in (await client.get("/workflow/list")).json()["result"]
             if row["name"] in (WF_PARENT, WF_CHILD, WF_INVOKED)}

    group = (await client.post("/workflow_topic", json={
        "node_id": node_id, "name": f"twsc_group_{RUN}", "title": "Проба"})).json()["result"]
    group_id = group["id"] if isinstance(group, dict) else group

    type_ids = {t["name"]: t["id"] for t in
                (await client.get("/workflow_step/list")).json()["result"]}

    # Вызов темой: номер подпотока лежит в `topic_action`, как его кладёт редактор.
    await client.post(f"/workflow/{names[WF_PARENT]}/step", json={
        "type_id": type_ids["topic_action"], "position": 1,
        "metadata": json.dumps({"topic_action": {
            "topic_group_id": group_id, "history": "talk_history_topic",
            "workflow_id": names[WF_CHILD], "inputs_map": {}, "outputs_map": {}}})})

    await client.post(f"/workflow/{names[WF_PARENT]}/step", json={
        "type_id": type_ids["workflow_invoke"], "position": 2,
        "metadata": json.dumps({"workflow_invoke": {
            "workflow_id": names[WF_INVOKED], "inputs_map": {}}})})

    return {"node_id": node_id, "group_id": group_id,
            "wf_parent": names[WF_PARENT], "wf_child": names[WF_CHILD],
            "wf_invoked": names[WF_INVOKED]}


async def _drop_probe(client: httpx.AsyncClient, probe: dict) -> None:
    await client.delete(f"/workflow_topic/{probe['group_id']}")
    for key in ("wf_parent", "wf_child", "wf_invoked"):
        await client.delete(f"/workflow/{probe[key]}")
    await client.delete(f"/node/{probe['node_id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
