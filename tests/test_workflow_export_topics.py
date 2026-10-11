"""Темы ноды в файле экспорта: группы, темы, вопросы и ссылка шага на группу.

## ⚠⚠ Что здесь стережётся и какой ценой узнано

Шаг `topic_action` держит группу тем **номером** (`metadata.topic_group_id`), а
сами группы живут на ноде — как переменные ноды. В файл они не попадали вовсе:
экспорт знал workflow, шаги и переменные, и ни слова про темы.

Перенос узла на другую установку давал шаг, чей номер группы там не значит
ничего. Селектор «Группа тем» показывает «-- Выберите группу тем --», шаг не
поднимает ни одной темы, ошибки нет ни при импорте, ни в прогоне. Замерено
переносом `dating_talk`: группа «Намерения» с темой `photo_send` и семью
метками осталась дома.

⚠ Секции тем **необязательны**: файл, снятый до их появления, читается тем же
импортом и темы принимающей стороны не трогает. Иначе старый файл стирал бы
чужую работу молча — и это проверяется здесь же.

⚠ Тесты ходят по HTTP и трогают только свою одноразовую ноду (`twet_*`).
Клиент заводится здесь же, как у соседних сюит: общий пул слоя
(`http_pool_transport`) — про живые выходы в бою, тесту нужна своя сессия с
логином и коротким сроком ожидания.
"""
import json
import os
import time

import httpx
import pytest

from src.ai.ai_workflow import ai_workflow_topic_group_refs_remap
from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

RUN = int(time.time())
NODE_NAME = f"twet_node_{RUN}"
WF_NAME = f"twet_wf_{RUN}"
GROUP_CODE = f"twet_group_{RUN}"
TOPIC_CODE = f"twet_topic_{RUN}"


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


def test_the_group_reference_is_remapped_in_metadata():
    """⚠ Правило переписывания ссылки на группу — по публичной функции.

    Номер бывает числом и строкой; пустой словарь обязан отдавать метаданные
    дословно — так же, как у соседа по ремапу шагов.
    """
    said = ('{"topic_action":{"topic_group_id":2,"workflow_id":76},'
            '"other":{"topic_group_id":"3"}}')

    assert ai_workflow_topic_group_refs_remap(said, {2: 900, 3: 901}) == \
        ('{"topic_action":{"topic_group_id":900,"workflow_id":76},'
         '"other":{"topic_group_id":"901"}}')

    assert ai_workflow_topic_group_refs_remap(said, {}) == said, \
        'пустой словарь обязан отдавать метаданные дословно'


class TestExportTopics:
    """Файл несёт темы, круговой проход их возвращает, старый файл их не трогает."""

    async def test_export_carries_groups_topics_and_questions(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Главный случай: три списка в файле, и группа — с тем же номером.

        Номер нужен именно тот: на него ссылается шаг.
        """
        payload = await _export(client, probe["node_id"])

        assert [g["id"] for g in payload["topic_groups"]] == [probe["group_id"]]
        assert payload["topic_groups"][0]["name"] == GROUP_CODE

        assert [t["id"] for t in payload["topics"]] == [probe["topic_id"]]
        assert payload["topics"][0]["topic_group_id"] == probe["group_id"]
        assert payload["topics"][0]["tags"] == "photo, send"
        assert payload["topics"][0]["instructions"] == "she_promised_send_photo"

        assert [q["question"] for q in payload["topic_questions"]] == \
            ["Is she promised to send a photo?"]
        assert payload["topic_questions"][0]["topic_id"] == probe["topic_id"]

    async def test_roundtrip_keeps_the_group_the_step_points_at(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Экспорт→импорт: номер группы тот же, и шаг по-прежнему на неё смотрит.

        Разойдись они — шаг молча перестал бы поднимать темы: ни ошибки, ни
        следа, только пустой селектор на странице.
        """
        payload = await _export(client, probe["node_id"])

        response = await client.post("/workflow/import", json=payload)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["topic_groups_imported"] == 1
        assert result["topics_imported"] == 1
        assert result["topic_questions_imported"] == 1

        again = await _export(client, probe["node_id"])
        assert [g["id"] for g in again["topic_groups"]] == [probe["group_id"]]
        assert [t["name"] for t in again["topics"]] == [TOPIC_CODE]
        assert [q["question"] for q in again["topic_questions"]] == \
            ["Is she promised to send a photo?"]

        before = {s["id"]: s["metadata"] for s in payload["steps"]}
        after = {s["id"]: s["metadata"] for s in again["steps"]}
        assert before == after, 'ссылка шага на группу переписана там, где не нужно'

        groups = (await client.get(
            f"/workflow_topic/list?node_id={probe['node_id']}")).json()["result"]
        assert [g["id"] for g in groups] == [probe["group_id"]], \
            'группа после импорта не та, на которую смотрит шаг'

    async def test_old_file_without_topics_leaves_them_alone(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Файл без секции тем — старый: темы ноды остаются нетронутыми.

        Обратное означало бы, что перенос workflow старым файлом молча стирает
        группы с темами, метками и вопросами, которых в нём нет и быть не может.
        """
        payload = await _export(client, probe["node_id"])
        for section in ("topic_groups", "topics", "topic_questions"):
            payload.pop(section)

        response = await client.post("/workflow/import", json=payload)
        assert response.status_code == 200, response.text
        assert any('секции тем' in note for note in response.json()["result"]["notes"])

        groups = (await client.get(
            f"/workflow_topic/list?node_id={probe['node_id']}")).json()["result"]
        assert [g["id"] for g in groups] == [probe["group_id"]], 'темы ноды снесены старым файлом'

    async def test_a_broken_topics_section_is_refused_at_the_border(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠ Секция не списком — отказ 400, а не падение посреди разбора.

        Необязательность секции не значит «что пришлют, то и съедим»: `null`
        вместо списка — испорченный файл.
        """
        payload = await _export(client, probe["node_id"])

        response = await client.post("/workflow/import",
                                     json={**payload, "topic_groups": None})
        assert response.status_code == 400, response.text

    async def test_step_pointing_at_a_missing_group_is_reported(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠ Ссылка на группу, которой в файле нет, — предупреждением, не молчком.

        Так бывает, когда группу удалили, а шаг остался: на принимающей стороне
        он не поднимет ни одной темы.
        """
        type_ids = {t["name"]: t["id"] for t in
                    (await client.get("/workflow_step/list")).json()["result"]}
        orphan = (await client.post(f"/workflow/{probe['wf_id']}/step", json={
            "type_id": type_ids["topic_action"], "position": 9,
            "metadata": json.dumps({"topic_action": {
                "topic_group_id": 999999, "workflow_id": probe["wf_id"]}})})).json()["result"]

        try:
            payload = await _export(client, probe["node_id"])
            assert any('999999' in w for w in payload["warnings"]), payload["warnings"]
        finally:
            await client.delete(f"/workflow/{probe['wf_id']}/step/{orphan}")


# ---------------------------------------------------------------------------
# Приватное: одноразовая нода с группой, темой, вопросом и шагом на них
# ---------------------------------------------------------------------------

async def _build_probe(client: httpx.AsyncClient) -> dict:
    """Нода, workflow с шагом `topic_action`, группа с темой и вопросом."""
    node = await client.post("/node", json={"name": NODE_NAME, "position": 914})
    assert node.status_code == 200, node.text
    created = node.json()["result"]
    node_id = created["id"] if isinstance(created, dict) else created

    response = await client.post("/workflow", json={
        "name": WF_NAME, "title": f"Probe {WF_NAME}", "node_id": node_id, "position": 1})
    assert response.status_code == 200, response.text
    wf_id = next(w["id"] for w in (await client.get("/workflow/list")).json()["result"]
                 if w["name"] == WF_NAME)

    group = (await client.post("/workflow_topic", json={
        "node_id": node_id, "name": GROUP_CODE, "title": "Намерения",
        "description": "проба"})).json()["result"]
    group_id = group["id"] if isinstance(group, dict) else group

    topic = (await client.post(f"/workflow_topic/{group_id}/topic", json={
        "name": TOPIC_CODE, "title": "Отправка фото", "tags": "photo, send",
        "tags_qty_accept": 2, "questions_qty_yes_accept": 1,
        "instructions": "she_promised_send_photo",
        "questions": [{"question": "Is she promised to send a photo?"}]})).json()["result"]
    topic_id = topic["id"] if isinstance(topic, dict) else topic

    type_ids = {t["name"]: t["id"] for t in
                (await client.get("/workflow_step/list")).json()["result"]}
    step_id = (await client.post(f"/workflow/{wf_id}/step", json={
        "type_id": type_ids["topic_action"], "position": 1,
        "metadata": json.dumps({"topic_action": {
            "topic_group_id": group_id, "history": "talk_history_topic",
            "workflow_id": wf_id, "inputs_map": {}, "outputs_map": {}}})})).json()["result"]

    return {"node_id": node_id, "wf_id": wf_id, "group_id": group_id,
            "topic_id": topic_id, "step_id": step_id}


async def _drop_probe(client: httpx.AsyncClient, probe: dict) -> None:
    await client.delete(f"/workflow_topic/{probe['group_id']}")
    await client.delete(f"/workflow/{probe['wf_id']}")
    await client.delete(f"/node/{probe['node_id']}")


async def _export(client: httpx.AsyncClient, node_id) -> dict:
    response = await client.get(f"/workflow/export?node_id={node_id}")
    assert response.status_code == 200, response.text
    return response.json()["result"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
