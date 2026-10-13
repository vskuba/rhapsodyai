"""Перенос тем файлом: кнопки «Экспорт» и «Импорт» вкладки «Topic & Action».

## ⚠⚠ Что здесь стережётся и почему именно так

Файл тем — не файл узла. Узловой **заменяет** ноду целиком и кладёт группы с
номерами из файла: он вправе так делать, потому что везёт и шаги, где эти
номера зашиты в `metadata`. Здесь шагов нет, и та же политика оборвала бы живые
шаги принимающей стороны — молча: селектор «Группа тем» пуст, шаг не поднимает
ни одной темы, ошибки нет ни при импорте, ни в прогоне.

Поэтому импорт тем **сливает по коду** (`name`) и **ничего не удаляет**. Ровно
это здесь и проверяется: номер совпавшей группы остаётся прежним, чужая группа
ноды переживает импорт, вопросы пришедшей темы переписываются целиком.

⚠ Тесты ходят по HTTP и трогают только свои одноразовые ноды (`twtt_*`).
Клиент заводится здесь же, как у соседних сюит: общий пул слоя
(`http_pool_transport`) — про живые выходы в бою, тесту нужна своя сессия с
логином и коротким сроком ожидания.
"""
import os
import time

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

RUN = int(time.time())
NODE_FROM = f"twtt_from_{RUN}"
NODE_TO = f"twtt_to_{RUN}"
GROUP_CODE = f"twtt_group_{RUN}"
TOPIC_CODE = f"twtt_topic_{RUN}"
OWN_GROUP_CODE = f"twtt_own_{RUN}"


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


class TestTopicExport:
    """Файл тем: три списка, метка своего формата, отказ там, где тем не бывает."""

    async def test_export_carries_groups_topics_and_questions(
            self, client: httpx.AsyncClient, probe: dict):
        payload = await _export(client, probe["from_id"])

        assert payload["format"] == "rhapsodyai.workflow_topic"
        assert payload["node"]["name"] == NODE_FROM

        assert [g["name"] for g in payload["topic_groups"]] == [GROUP_CODE]
        assert [t["name"] for t in payload["topics"]] == [TOPIC_CODE]
        assert payload["topics"][0]["tags"] == "photo, send"
        assert [q["question"] for q in payload["topic_questions"]] == \
            ["Is she promised to send a photo?"]

    async def test_export_of_a_missing_node_is_refused(self, client: httpx.AsyncClient):
        """⚠ Ноды нет — 404, а не пустой файл: пустой читался бы как «тем нет»."""
        response = await client.get("/workflow_topic/export?node_id=999999")
        assert response.status_code == 404, response.text


class TestTopicImport:
    """Слияние по коду: номер цел, чужое цело, вопросы — целиком из файла."""

    async def test_import_into_another_node_creates_groups_and_topics(
            self, client: httpx.AsyncClient, probe: dict):
        """Темы приезжают в ноду, выбранную человеком, а не в ноду файла."""
        payload = await _export(client, probe["from_id"])

        result = await _import(client, probe["to_id"], payload)
        assert result["groups_created"] == 1
        assert result["topics_created"] == 1
        assert result["questions_written"] == 1
        assert any(NODE_FROM in note for note in result["notes"]), \
            'расхождение нод обязано приезжать заметкой'

        topics = await _topics(client, probe["to_id"])
        assert [t["name"] for t in topics] == [TOPIC_CODE]
        assert [q["question"] for q in topics[0]["questions"]] == \
            ["Is she promised to send a photo?"]

    async def test_second_import_updates_in_place_and_keeps_the_group_id(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Главный случай: повторный импорт правит на месте, номер группы тот же.

        Заведи он группу заново — шаги принимающей стороны остались бы с
        номером, которого больше нет, и перестали бы поднимать темы молча.
        """
        payload = await _export(client, probe["from_id"])
        await _import(client, probe["to_id"], payload)

        groups_before = await _groups(client, probe["to_id"])
        arrived = next(g for g in groups_before if g["name"] == GROUP_CODE)

        # Меняем тему у себя — второй импорт обязан вернуть её к файлу
        topic_id = (await _topics(client, probe["to_id"]))[0]["id"]
        edited = await client.put(f"/workflow_topic/topic/{topic_id}",
                                  json={"tags": "zzz", "questions": []})
        assert edited.status_code == 200, edited.text

        result = await _import(client, probe["to_id"], payload)
        assert result["groups_created"] == 0 and result["groups_updated"] == 1
        assert result["topics_created"] == 0 and result["topics_updated"] == 1

        groups_after = await _groups(client, probe["to_id"])
        assert next(g["id"] for g in groups_after if g["name"] == GROUP_CODE) == arrived["id"], \
            'номер группы сменился — шаги, смотревшие на неё, осиротели'

        topics = await _topics(client, probe["to_id"])
        assert topics[0]["tags"] == "photo, send", 'правка не вернулась к файлу'
        assert [q["question"] for q in topics[0]["questions"]] == \
            ["Is she promised to send a photo?"], 'вопросы не переписаны из файла'

    async def test_import_leaves_the_groups_the_file_knows_nothing_about(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Импорт ничего не удаляет — и говорит об этом заметкой."""
        own = (await client.post("/workflow_topic", json={
            "node_id": probe["to_id"], "name": OWN_GROUP_CODE,
            "title": "Своя группа"})).json()["result"]
        own_id = own["id"] if isinstance(own, dict) else own

        result = await _import(client, probe["to_id"], await _export(client, probe["from_id"]))
        assert any('оставлены как были' in note for note in result["notes"])

        groups = await _groups(client, probe["to_id"])
        assert own_id in [g["id"] for g in groups], 'своя группа ноды снесена импортом'

    async def test_a_node_file_is_accepted_too(self, client: httpx.AsyncClient, probe: dict):
        """⚠ Узловой файл читается тем же импортом: секции тем в нём те же.

        Workflow из него здесь не читаются — в ответе про них нет ни слова.
        """
        node_file = (await client.get(
            f"/workflow/export?node_id={probe['from_id']}")).json()["result"]

        result = await _import(client, probe["to_id"], node_file)
        assert result["groups_created"] == 1
        assert "workflows_imported" not in result

    async def test_a_file_without_topics_is_refused(self, client: httpx.AsyncClient, probe: dict):
        """⚠ Файл без секции тем — отказ 400: вливать нечего, и молчать нельзя."""
        payload = await _export(client, probe["from_id"])
        payload.pop("topic_groups")

        response = await client.post(
            f"/workflow_topic/import?node_id={probe['to_id']}", json=payload)
        assert response.status_code == 400, response.text

    async def test_a_foreign_file_is_refused(self, client: httpx.AsyncClient, probe: dict):
        """⚠ Чужой JSON — 400 по метке формата, а не падение посреди разбора."""
        response = await client.post(
            f"/workflow_topic/import?node_id={probe['to_id']}", json={"hello": "world"})
        assert response.status_code == 400, response.text

    async def test_two_topics_with_one_code_are_refused(
            self, client: httpx.AsyncClient, probe: dict):
        """⚠⚠ Слияние идёт по коду — значит два одинаковых кода в файле неразличимы.

        Схема такое терпит (ключ у темы — пара «группа + код»), а слияние нет:
        вторая тема молча перетёрла бы первую.
        """
        payload = await _export(client, probe["from_id"])
        twin = dict(payload["topics"][0])
        twin["id"] = twin["id"] + 1000
        payload["topics"].append(twin)

        response = await client.post(
            f"/workflow_topic/import?node_id={probe['to_id']}", json=payload)
        assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# Приватное: две одноразовые ноды, в первой — группа с темой и вопросом
# ---------------------------------------------------------------------------

async def _build_probe(client: httpx.AsyncClient) -> dict:
    from_id = await _node_make(client, NODE_FROM, 915)
    to_id = await _node_make(client, NODE_TO, 916)

    group = (await client.post("/workflow_topic", json={
        "node_id": from_id, "name": GROUP_CODE, "title": "Намерения",
        "description": "проба"})).json()["result"]
    group_id = group["id"] if isinstance(group, dict) else group

    topic = (await client.post(f"/workflow_topic/{group_id}/topic", json={
        "name": TOPIC_CODE, "title": "Отправка фото", "tags": "photo, send",
        "tags_qty_accept": 2, "questions_qty_yes_accept": 1,
        "instructions": "she_promised_send_photo",
        "questions": [{"question": "Is she promised to send a photo?"}]})).json()["result"]

    return {"from_id": from_id, "to_id": to_id, "group_id": group_id,
            "topic_id": topic["id"] if isinstance(topic, dict) else topic}


async def _node_make(client: httpx.AsyncClient, name: str, position: int) -> int:
    response = await client.post("/node", json={"name": name, "position": position})
    assert response.status_code == 200, response.text
    created = response.json()["result"]
    return created["id"] if isinstance(created, dict) else created


async def _drop_probe(client: httpx.AsyncClient, probe: dict) -> None:
    for node_id in (probe["from_id"], probe["to_id"]):
        for group in await _groups(client, node_id):
            await client.delete(f"/workflow_topic/{group['id']}")
        await client.delete(f"/node/{node_id}")


async def _export(client: httpx.AsyncClient, node_id) -> dict:
    response = await client.get(f"/workflow_topic/export?node_id={node_id}")
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def _import(client: httpx.AsyncClient, node_id, payload) -> dict:
    response = await client.post(f"/workflow_topic/import?node_id={node_id}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def _groups(client: httpx.AsyncClient, node_id) -> list:
    response = await client.get(f"/workflow_topic/list?node_id={node_id}")
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def _topics(client: httpx.AsyncClient, node_id) -> list:
    response = await client.get(f"/workflow_topic/topic/list?node_id={node_id}")
    assert response.status_code == 200, response.text
    return response.json()["result"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
