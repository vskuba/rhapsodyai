import os
from tests.constants import TEST_AUTH
"""Workflow trace read-only tests — /workflow_trace/run/list, /run/{uuid}."""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestWorkflowTrace:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    # --- /workflow_trace/run/list ---

    async def test_trace_list_returns_result_and_pagination(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "pagination" in data
        assert isinstance(data["result"], list)

    async def test_trace_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/workflow_trace/run/list")
            assert resp.status_code in (401, 403)

    async def test_trace_list_pagination_fields(self, client: httpx.AsyncClient):
        pagination = (await client.get("/workflow_trace/run/list")).json()["pagination"]
        for field in ("current_page", "total_pages", "total_records"):
            assert field in pagination

    async def test_trace_list_pagination_page_param(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?page=1&limit=5")
        assert resp.status_code == 200
        pagination = resp.json()["pagination"]
        assert pagination["current_page"] == 1

    async def test_trace_list_limit_capped_at_100(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?limit=9999")
        assert resp.status_code == 200
        assert len(resp.json()["result"]) <= 100

    async def test_trace_list_filter_by_status_running(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=running")
        assert resp.status_code == 200
        runs = resp.json()["result"]
        for run in runs:
            assert run["status"] == "running"

    async def test_trace_list_filter_by_status_success(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=success")
        assert resp.status_code == 200
        runs = resp.json()["result"]
        for run in runs:
            assert run["status"] == "success"

    async def test_trace_list_filter_by_status_error(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=error")
        assert resp.status_code == 200

    async def test_trace_list_filter_invalid_status_ignored(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?status=invalid_status")
        assert resp.status_code == 200

    async def test_trace_list_filter_by_workflow_id(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?workflow_id=999999")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0

    async def test_trace_list_filter_by_agent_id(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?agent_id=999999")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0

    async def test_trace_list_filter_by_node_id(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/list?node_id=999999")
        assert resp.status_code == 200
        assert resp.json()["pagination"]["total_records"] == 0

    async def test_trace_list_filter_by_node_id_keeps_agents_of_that_node(self, client: httpx.AsyncClient):
        """Ноды у прогона нет — отбор идёт через агента, поэтому проверяем именно это:
        каждый прогон отбора принадлежит агенту запрошенной ноды."""
        nodes = (await client.get("/node/list")).json()["result"]
        agents = (await client.get("/agent/list")).json()["result"]

        for node in nodes:
            node_agent_ids = {a["id"] for a in agents if a.get("node_id") == node["id"]}
            if not node_agent_ids:
                continue
            resp = await client.get(f"/workflow_trace/run/list?node_id={node['id']}&limit=30")
            assert resp.status_code == 200
            runs = resp.json()["result"]
            if not runs:
                continue
            assert {r["agent_id"] for r in runs} <= node_agent_ids
            return

        pytest.skip("Нет ноды с прогонами в БД")

    async def test_trace_list_run_fields(self, client: httpx.AsyncClient):
        runs = (await client.get("/workflow_trace/run/list")).json()["result"]
        if not runs:
            pytest.skip("No workflow runs in DB")
        run = runs[0]
        for field in ("id", "run_uuid", "status", "started_at", "steps_qty", "children_qty"):
            assert field in run, f"Missing field: {field}"

    # --- /workflow_trace/run/{run_uuid} ---

    async def test_trace_detail_nonexistent_returns_404(self, client: httpx.AsyncClient):
        resp = await client.get("/workflow_trace/run/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_trace_detail_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/workflow_trace/run/00000000-0000-0000-0000-000000000000")
            assert resp.status_code in (401, 403, 404)

    async def test_trace_detail_existing_run(self, client: httpx.AsyncClient):
        runs = (await client.get("/workflow_trace/run/list")).json()["result"]
        if not runs:
            pytest.skip("No workflow runs in DB")
        run_uuid = runs[0]["run_uuid"]
        resp = await client.get(f"/workflow_trace/run/{run_uuid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert "run_uuid" in result
        assert result["run_uuid"] == run_uuid
        assert "steps" in result

    # --- поиск по всем прогонам ---

    async def test_search_shorter_than_three_is_not_a_search(self, client: httpx.AsyncClient):
        """⚠ Два знака — не поиск: отсеивать нечем, а проход был бы полный.

        Порог обязан совпадать с тем, что держит страница (`STEP_SEARCH_ALL_MIN`):
        разойдись они, поле слало бы запрос, который ручка молча считает пустым,
        и человек видел бы обычный список вместо поиска.
        """
        answer = (await client.get("/workflow_trace/run/list?search=ab&limit=5")).json()

        assert "search" not in answer, 'короткий запрос принят за поиск'
        assert answer["pagination"]["total_records"] >= len(answer["result"])

    async def test_search_that_matches_nothing_says_so(self, client: httpx.AsyncClient):
        """Ничего не нашлось — пустой список и честный счёт, а не отказ."""
        answer = (await client.get(
            "/workflow_trace/run/list?search=zzqq_такого_текста_нет&limit=20")).json()

        assert answer["result"] == []
        assert answer["search"]["found"] == 0
        assert answer["search"]["limited"] is False
        assert isinstance(answer["search"]["ms"], int)

    async def test_search_finds_the_run_by_its_own_text(self, client: httpx.AsyncClient):
        """⚠⚠ Главный случай: заводим прогон с неповторимым словом и ищем его.

        Слово уникально, поэтому совпадение может быть только одно — это и
        отличает проверку поиска от проверки «что-нибудь нашлось».

        ⚠ Прогон не обязан удаться: ищется он по своему запросу, а тот ложится
        в журнал при заведении строки (`request_json`, `prompt_user`).
        """
        import uuid as uuid_module

        agents = (await client.get("/agent/list")).json()["result"]
        probe = next((a for a in agents
                      if str(a.get("name", "")).startswith("testing_") and a.get("workflow_id")), None)
        if not probe:
            pytest.skip("на установке нет агентов ноды Testing")

        needle = f"zzprobe{uuid_module.uuid4().hex[:10]}"
        await client.post("/chat/ask", json={
            "question": f"поиск по всем прогонам {needle}", "agent_id": probe["id"],
            "session_uuid": str(uuid_module.uuid4()), "variables": {}}, timeout=60.0)

        answer = (await client.get(
            f"/workflow_trace/run/list?search={needle}&limit=20")).json()

        assert answer["search"]["query"] == needle
        assert answer["search"]["found"] == 1, \
            f'по неповторимому слову нашлось {answer["search"]["found"]} прогонов'
        assert needle in str(answer["result"][0]["prompt_user"])

    async def test_search_reaches_inside_the_steps(self, client: httpx.AsyncClient):
        """⚠⚠ Поиск достаёт до ШАГОВ, а не только до полей прогона.

        Название шага (`step_title`) не встречается ни в запросе прогона, ни в
        ответе — оно есть только в таблице шагов. Поэтому находка по нему и
        доказывает, что рекурсивная часть условия работает; без неё поиск был
        бы поиском по двум строчкам карточки, а не по содержимому прогона.
        """
        runs = (await client.get("/workflow_trace/run/list?limit=5")).json()["result"]
        if not runs:
            pytest.skip("No workflow runs in DB")

        detail = (await client.get(
            f"/workflow_trace/run/{runs[0]['run_uuid']}")).json()["result"]
        steps = detail.get("steps") or []
        title = next((str(s.get("step_title") or '') for s in steps
                      if len(str(s.get("step_title") or '')) >= 4), '')
        if not title:
            pytest.skip("у свежего прогона нет шагов с названием")

        # ⚠ Отбрасываем случай, когда название и так лежит в полях прогона:
        # тогда находка ничего не доказывала бы
        if title.lower() in str(detail.get("prompt_user") or '').lower() \
                or title.lower() in str(detail.get("result") or '').lower():
            pytest.skip("название шага встречается и в полях прогона — случай не чистый")

        found = (await client.get(
            f"/workflow_trace/run/list?search={title}&limit=100")).json()

        assert found["search"]["found"] > 0, f'по названию шага «{title}» не нашлось ничего'
        assert any(r["id"] == detail["id"] for r in found["result"]), \
            f'прогон #{detail["id"]} не нашёлся по названию своего шага «{title}»'

    async def test_search_obeys_the_filters(self, client: httpx.AsyncClient):
        """⚠ Отбор и поиск действуют вместе — на этом держится цена поиска.

        Чужой агент в отборе обязан дать пусто по тому же слову, по которому
        свой даёт находку: иначе отбор не сужает проход, а лишь украшает его.
        """
        import uuid as uuid_module

        agents = (await client.get("/agent/list")).json()["result"]
        probe = next((a for a in agents
                      if str(a.get("name", "")).startswith("testing_") and a.get("workflow_id")), None)
        if not probe:
            pytest.skip("на установке нет агентов ноды Testing")

        needle = f"zzprobe{uuid_module.uuid4().hex[:10]}"
        await client.post("/chat/ask", json={
            "question": f"отбор и поиск {needle}", "agent_id": probe["id"],
            "session_uuid": str(uuid_module.uuid4()), "variables": {}}, timeout=60.0)

        mine = (await client.get(
            f"/workflow_trace/run/list?search={needle}&agent_id={probe['id']}")).json()
        assert mine["search"]["found"] == 1, 'со своим агентом прогон не нашёлся'

        # Любой другой агент — тот же текст не должен находиться
        other = next((a for a in agents if a["id"] != probe["id"]), None)
        if other:
            away = (await client.get(
                f"/workflow_trace/run/list?search={needle}&agent_id={other['id']}")).json()
            assert away["search"]["found"] == 0, 'поиск не послушался отбора по агенту'

    # --- контракт вызова: чем прогон позвали и что ушло зовущему ---

    async def test_trace_detail_carries_the_contract_fields(self, client: httpx.AsyncClient):
        """⚠⚠ Ключи контракта обязаны приезжать всегда, пусть и пустыми.

        Ручка отдаёт прогон целиком (`SELECT r.*`), и правая колонка страницы
        строится ровно по этим двум ключам. Замени кто-нибудь `r.*` на список
        колонок — колонка опустеет **молча**: ни ошибки, ни пустого места, а
        честное «не записан» на каждом прогоне, включая те, где контракт есть.
        """
        runs = (await client.get("/workflow_trace/run/list")).json()["result"]
        if not runs:
            pytest.skip("No workflow runs in DB")

        result = (await client.get(
            f"/workflow_trace/run/{runs[0]['run_uuid']}")).json()["result"]

        for field in ("request_json", "response_json"):
            assert field in result, f"ручка подробностей не отдаёт «{field}»"

    async def test_the_call_records_its_own_contract(self, client: httpx.AsyncClient):
        """⚠⚠ Зовём `/chat/ask` сами и проверяем, что контракт лёг в прогон.

        Читающей пробы тут мало: уборка сюиты сносит прогоны тестовой учётки
        (`TEST_SWEEP_TABLES`), то есть ровно те, у которых контракт бывает. Тест
        «поищем записанный» пропускался бы **всегда** — а это хуже отсутствия
        теста: зелёная сюита с молчаливым пропуском читается как проверенная.

        ⚠ Модель для этого не нужна, и прогон не обязан удаться: запрос ложится
        в журнал при заведении строки, ответ — на любом исходе, включая отказ.
        Нода Testing держит единственную подменную модель (`fake/echo`), наружу
        не уходит ни один запрос; служба подмены может быть не поднята — тогда
        прогон упадёт, и контракт обязан записаться всё равно.

        ⚠⚠ Разбор строгий (`json.loads`), а не мягкий `json_from_string`: тот
        заведён вынимать JSON из болтовни модели и **простит** испорченную
        запись — то есть скроет ровно тот дефект, ради которого тест написан.
        """
        import json
        import uuid as uuid_module

        agents = (await client.get("/agent/list")).json()["result"]
        probe = next((a for a in agents
                      if str(a.get("name", "")).startswith("testing_") and a.get("workflow_id")), None)
        if not probe:
            pytest.skip("на установке нет агентов ноды Testing")

        asked = f"contract probe {uuid_module.uuid4().hex[:8]}"
        body = {"question": asked, "agent_id": probe["id"],
                "session_uuid": str(uuid_module.uuid4()), "variables": {}}

        # Исход не важен: контракт обязан лечь и у упавшего прогона
        await client.post("/chat/ask", json=body, timeout=60.0)

        runs = (await client.get(
            f"/workflow_trace/run/list?agent_id={probe['id']}&limit=100")).json()["result"]
        mine = next((r for r in runs if asked.startswith(str(r.get("prompt_user") or "")[:40])
                     and r.get("prompt_user")), None)
        assert mine, f"прогон по вопросу {asked!r} не нашёлся среди свежих"

        run = (await client.get(f"/workflow_trace/run/{mine['run_uuid']}")).json()["result"]

        assert run.get("request_json"), "запрос контракта не записан"
        request = json.loads(run["request_json"])
        assert request["question"] == asked, 'в контракте не тот вопрос'
        assert request["agent_id"] == probe["id"], 'в контракте не тот агент'
        assert request["session_uuid"] == body["session_uuid"], 'в контракте не та сессия'

        assert run.get("response_json"), "ответ контракта не записан"
        assert isinstance(json.loads(run["response_json"]), dict), \
            'ответ контракта записан не объектом'
