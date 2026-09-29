"""
Экспорт/импорт workflow (GET /workflow/export, POST /workflow/import).

Точка HTTP тонкая — домен живёт в `src/ai/ai_workflow_export.py` и
`src/ai/ai_workflow_import.py` (путь к ним уже задан в pyproject.toml:
`pythonpath = [".", "py_modules"]`). Тесты ходят по HTTP и трогают только свои
одноразовые данные (`twei_*`): нода, два workflow с шагами, переменная workflow
и переменная ноды. Настоящие ноды и workflow не читаются для изменения и не
меняются вовсе — чужой id используется лишь как приманка для проверки отказа.
Одна проверка — юнит на слияние дублей переменных, по публичной функции
модуля `ai_workflow_export_variables_merge`: через API дубль не создать
(редактор get-or-create), гонять ради него живую базу бессмысленно.

Проверяется:
- форма экспортного файла и порядок роутов (`GET /workflow/{id}` не перекрыт);
- круговой проход экспорт→импорт в свою же ноду: id workflow и шагов, metadata;
- конфликт: чужой id и занятое имя → 409, битый файл → 400, нет такой ноды → 400;
- откат: падение в середине импорта не трогает ноду;
- предупреждения: цель `workflow_invoke` вне файла не тянется, а видна в warnings;
- одно имя у двух workflow — две записи в файле, дубль внутри workflow сливается.
"""

import json
import os
import time

import httpx
import pytest

from src.ai.ai_workflow_export import ai_workflow_export_variables_merge
from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# Уникальная на запуск наставка: упавший прогон оставляет данные, а повтор с теми
# же именами упёрся бы в дубликат — имена workflow уникальны в таблице.
RUN = int(time.time())
NODE_NAME = f"twei_node_{RUN}"
WF_ONE = f"twei_one_{RUN}"
WF_TWO = f"twei_two_{RUN}"


@pytest.fixture
async def client():
    logged = await _login()
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


class TestWorkflowExportImport:
    """Контракт файла, круговой проход и отказы."""

    async def test_export_shape(self, client: httpx.AsyncClient, probe: dict):
        """Файл несёт ноду, оба workflow, шаги с ссылками внутри и предупреждение."""
        payload = await _export(client, probe["node_id"])

        assert payload["format"] == "rhapsodyai.workflow"
        assert payload["version"] == 1
        assert payload["node"]["name"] == NODE_NAME
        assert {w["id"] for w in payload["workflows"]} == {probe["wf_one"], probe["wf_two"]}
        assert len(payload["steps"]) == 2
        assert any(w and str(probe["dangling"]) in w for w in payload["warnings"])

        steps = {s["id"]: s for s in payload["steps"]}
        assert "transitions_after" in steps[probe["invoke_step"]]["metadata"]
        assert f"send_message_{probe['invoke_step']}_result_text" in steps[probe["invoke_step"]]["metadata"]

        assert [v["name"] for v in payload["variables"]] == [f"{WF_ONE}_v"]
        assert [v["name"] for v in payload["node_variables"]] == [f"{WF_ONE}_nv"]
        assert {l["workflow_id"] for l in payload["variable_links"]} == {probe["wf_one"]}
        assert probe["wf_one"] in {l["workflow_id"] for l in payload["node_variable_links"]}

    async def test_export_names_global_variables_once(self, client: httpx.AsyncClient, probe: dict):
        """Глобальные названы поимённо, каждая по разу, и в файл не едут.

        ⚠ Дефект, доживший до прода: счёт шёл `COUNT(*)` по таблице связей, и
        переменная, привязанная к двум workflow ноды, считалась дважды. На ноде
        Dating предупреждение обещало четыре записи там, где их три, — человек
        на принимающей стороне искал четвёртую.

        ⚠⚠ Связки больше нет, и выборка «глобальные этих workflow» тоже: у
        глобальной **нет владельца** — движок отдаёт их все каждому workflow.
        Поэтому предупреждение перечисляет глобальные установки целиком, и
        проверяем то же самое: имена названы, повторов нет, в `variables`
        ни одной.

        Проверяем не только число: имена в тексте избавляют принимающую сторону
        от похода в базу за списком.
        """
        payload = await _export(client, probe["node_id"])

        about_globals = [w for w in payload["warnings"] if "Глобальные" in w]
        assert len(about_globals) == 1, payload["warnings"]

        listed = about_globals[0].split('):', 1)[1].split(' — ')[0]
        names = [one.strip() for one in listed.split(',') if one.strip()]
        assert 'prompt_user' in names, f"системная не названа: {about_globals[0]}"
        assert len(names) == len(set(names)), f"имя посчитано дважды: {about_globals[0]}"
        assert f"({len(names)})" in about_globals[0], f"счёт разошёлся с именами: {about_globals[0]}"

        # Сами они в файл не едут — только предупреждение о них.
        assert not set(names) & {v["name"] for v in payload["variables"]}

    async def test_export_pseudo_node_works(self, client: httpx.AsyncClient):
        """`node_id=none` — файл без ноды собирается, и роут id-а не перекрыт."""
        payload = await _export(client, "none")
        assert payload["format"] == "rhapsodyai.workflow"
        assert payload["node"] is None

        other = (await client.get("/workflow/list")).json()["result"]
        if other:
            response = await client.get(f"/workflow/{other[0]['id']}")
            assert response.status_code == 200, "GET /workflow/{id} перекрыт новым роутом"

    def test_export_keeps_same_name_in_two_workflows(self):
        """Одно имя у двух workflow — две записи в файле, а не одна.

        ⚠⚠ Ровно это и было бедой: слияние шло по паре (имя, тип) **по всей
        базе**, и `girl_name` родителя с `girl_name` подпотока становились одной
        строкой. Теперь у переменной один владелец, и записи независимы.

        Сливается только дубль **внутри одного workflow** — страховка на данные,
        снятые до `UNIQUE (workflow_id, name)`: связь дубля переезжает на
        каноническую строку, иначе файл сослался бы на невыгруженную запись.
        Проверка прямая, по публичному правилу
        `ai_workflow_export_variables_merge`, на подставных строках.
        """
        variables, links = ai_workflow_export_variables_merge(
            [{'id': 24, 'workflow_id': 5, 'name': 'girl_name', 'type': 'input',
              'default': None, 'description': None},
             {'id': 34, 'workflow_id': 6, 'name': 'girl_name', 'type': 'input',
              'default': None, 'description': None},
             {'id': 44, 'workflow_id': 5, 'name': 'girl_name', 'type': 'input',
              'default': None, 'description': None},
             {'id': 40, 'workflow_id': 5, 'name': 'other', 'type': 'input',
              'default': None, 'description': None}],
            [{'variable_id': 24, 'workflow_id': 5}, {'variable_id': 34, 'workflow_id': 6},
             {'variable_id': 44, 'workflow_id': 5}, {'variable_id': 40, 'workflow_id': 5}],
        )

        assert [v['id'] for v in variables] == [24, 34, 40], "тёзка из чужого workflow — своя запись"
        assert sorted((l['variable_id'], l['workflow_id']) for l in links) == \
            [(24, 5), (34, 6), (40, 5)], "дубль внутри workflow переезжает на каноническую строку"

    async def test_roundtrip_keeps_ids(self, client: httpx.AsyncClient, probe: dict):
        """Экспорт→импорт в ту же ноду: те же id workflow и шагов, metadata целая."""
        payload = await _export(client, probe["node_id"])

        response = await client.post("/workflow/import", json=payload)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["workflows_removed"] == 2
        assert result["workflows_imported"] == 2
        assert result["steps_imported"] == 2

        again = await _export(client, probe["node_id"])
        assert {w["id"] for w in again["workflows"]} == {probe["wf_one"], probe["wf_two"]}
        assert {s["id"] for s in again["steps"]} == {probe["invoke_step"], probe["invoke_ref"]}
        before = {s["id"]: s["metadata"] for s in payload["steps"]}
        after = {s["id"]: s["metadata"] for s in again["steps"]}
        assert before == after

        # Живой прогон на Dating поймал, что импорт сливал NULL описания в '' —
        # сравниваем записи переменных целиком, id может переехать на местный.
        def records(payload):
            strip_id = lambda rows: [{k: v for k, v in r.items() if k != "id"} for r in rows]
            return strip_id(payload["variables"]), strip_id(payload["node_variables"])

        assert records(payload) == records(again), "round-trip не должен менять default/description"

    async def test_import_conflict_foreign_id(self, client: httpx.AsyncClient, probe: dict):
        """Workflow с чужим id (не из wipe-набора) → 409, нода цела."""
        payload = await _export(client, probe["node_id"])
        foreign = next((w["id"] for w in (await client.get("/workflow/list")).json()["result"]
                        if w["id"] not in (probe["wf_one"], probe["wf_two"])), None)
        if foreign is None:
            pytest.skip("в базе больше нет чужих workflow")
        # Подмена последовательная: и в записях workflow, и в его шагах —
        # иначе отказ приходит на другой проверке, а не на конфликте id.
        stale = probe["wf_two"]
        for record in payload["workflows"]:
            if record["id"] == stale:
                record["id"] = foreign
        for step in payload["steps"]:
            if step["workflow_id"] == stale:
                step["workflow_id"] = foreign

        response = await client.post("/workflow/import", json=payload)
        assert response.status_code == 409, response.text

        untouched = await _export(client, probe["node_id"])
        assert {w["id"] for w in untouched["workflows"]} == {probe["wf_one"], probe["wf_two"]}

    async def test_import_bad_requests(self, client: httpx.AsyncClient, probe: dict):
        """Битый формат, metadata не-строка и несуществующая нода → 400."""
        payload = await _export(client, probe["node_id"])

        broken = dict(payload, format="not.mine")
        assert (await client.post("/workflow/import", json=broken)).status_code == 400

        bad_meta = {**payload, "steps": [dict(payload["steps"][0], metadata={"text": 1})]}
        assert (await client.post("/workflow/import", json=bad_meta)).status_code == 400

        ghost = {**payload, "node": {"id": 999999, "name": f"twei_ghost_{RUN}"}}
        assert (await client.post("/workflow/import", json=ghost)).status_code == 400

        assert (await client.post("/workflow/import", json={"format": "x"})).status_code == 400

    async def test_import_unknown_step_type_rolls_back(self, client: httpx.AsyncClient, probe: dict):
        """Неизвестный тип шага — отказ, и нода остаётся ровно такой, какой была."""
        payload = await _export(client, probe["node_id"])
        poisoned = {**payload, "steps": [dict(s, type_name="twei_no_such_type") for s in payload["steps"]]}

        response = await client.post("/workflow/import", json=poisoned)
        assert response.status_code == 400, response.text

        untouched = await _export(client, probe["node_id"])
        assert {w["id"] for w in untouched["workflows"]} == {probe["wf_one"], probe["wf_two"]}
        assert len(untouched["steps"]) == 2


# ---------------------------------------------------------------------------
# Приватное: одноразовые данные и обращения, которыми пользуется всё выше
# ---------------------------------------------------------------------------

async def _login() -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0)
    response = await client.post("/auth/login", json=TEST_AUTH)
    assert response.status_code == 200, response.text
    return client


def _rid(created):
    """Точки возврата щедрые: иногда отдают id числом, иногда — словарём `{"id": …}`."""
    return created["id"] if isinstance(created, dict) else created


async def _build_probe(client: httpx.AsyncClient) -> dict:
    """Заводит одноразовую ноду с двумя workflow, шагами и обеими переменными.

    Returns:
        dict: node_id, wf_one, wf_two, step-ы, id переменных — для утверждений
            и уборки.
    """
    node = await client.post("/node", json={"name": NODE_NAME, "position": 911})
    assert node.status_code == 200, node.text
    created = node.json()["result"]
    node_id = _rid(created)

    for name, position in ((WF_ONE, 1), (WF_TWO, 2)):
        response = await client.post("/workflow", json={
            "name": name, "title": f"Probe {name}", "node_id": node_id, "position": position})
        assert response.status_code == 200, response.text
    wf_one = next(w["id"] for w in (await client.get("/workflow/list")).json()["result"]
                  if w["name"] == WF_ONE)
    wf_two = next(w["id"] for w in (await client.get("/workflow/list")).json()["result"]
                  if w["name"] == WF_TWO)

    step_types = (await client.get("/workflow_step/list")).json()["result"]
    type_ids = {t["name"]: t["id"] for t in step_types}

    # Шаг-«ответ» с текстом и ссылка на шаг вызова — переход и имя результата
    # живут внутри metadata, как в бою. Строкой: так их носит фронтенд.
    invoke_step = (await client.post(f"/workflow/{wf_one}/step", json={
        "type_id": type_ids["return_response_text"], "position": 1,
        "metadata": json.dumps({"text": "готово"})})).json()["result"]
    step_meta = json.dumps({
        "text": "готово",
        "transitions_after": [{"step_id": invoke_step, "condition": "true"}],
        "context_vars": {"answer": f"send_message_{invoke_step}_result_text"}})
    await client.put(f"/workflow/{wf_one}/step/{invoke_step}", json={"metadata": step_meta})

    # Вызов workflow, которого нет в файле: экспорт обязан предупредить, но не тянуть.
    # Форма — как у движка: вызов живёт в ключе `workflow_invoke`.
    dangling = 999999
    invoke_ref = (await client.post(f"/workflow/{wf_two}/step", json={
        "type_id": type_ids["workflow_invoke"], "position": 1,
        "metadata": json.dumps({"workflow_invoke": {"workflow_id": dangling, "inputs_map": {}}})})).json()["result"]

    var = (await client.post(f"/workflow/{wf_one}/variable", json={
        "name": f"{WF_ONE}_v", "default": "да", "type": "workflow"})).json()["result"]
    node_var = (await client.post("/node/workflow_variable", json={
        "name": f"{WF_ONE}_nv", "default": "километр", "node_id": node_id,
        "workflow_ids": [wf_one]})).json()["result"]["id"]

    return {"node_id": node_id, "wf_one": wf_one, "wf_two": wf_two,
            "invoke_step": invoke_step, "invoke_ref": invoke_ref,
            "dangling": dangling, "var": var, "node_var": node_var}


async def _drop_probe(client: httpx.AsyncClient, probe: dict) -> None:
    """Убирает всё, что завёл `_build_probe`, в порядке обратном связям."""
    await client.delete(f"/workflow_variable/public/{probe['node_var']}")
    await client.delete(f"/workflow/{probe['wf_one']}/variable/{probe['var']}")
    for wf in (probe["wf_one"], probe["wf_two"]):
        await client.delete(f"/workflow/{wf}")
    await client.delete(f"/node/{probe['node_id']}")


async def _export(client: httpx.AsyncClient, node_id) -> dict:
    response = await client.get(f"/workflow/export?node_id={node_id}")
    assert response.status_code == 200, response.text
    return response.json()["result"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
