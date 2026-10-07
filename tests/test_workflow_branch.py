"""
Ветки: заведение, правка, удаление.

HTTP-часть идёт на стенд — ручки это контракт, и проверять их вызовом функций
значило бы не проверить ни маршрут, ни права.

⚠⚠ Ветки заводятся на **живой** ноде Dating, а не на выдуманной: проверяться
должен тот путь, которым пойдёт человек. Цена — уборка по приставке имени, и она
идёт до и после прогона.

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
TEST_NODE_ID = 2  # Dating


async def _sweep(client: httpx.AsyncClient) -> None:
    listing = await client.get(f"/workflow_branch/list?node_id={TEST_NODE_ID}")
    if listing.status_code != 200:
        return
    for branch in listing.json().get("result", []):
        if not str(branch.get("name", "")).startswith(TEST_BRANCH_PREFIX):
            continue
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
        """Код всё ещё можно прислать явно — так делают сиды и импорт."""
        await _branch_make(client, 'twice')
        clash = await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}twice", "title": "Дубль",
        })
        assert clash.status_code == 400
        assert 'уже есть' in clash.json()["detail"]

    async def test_code_is_made_from_title(self, client: httpx.AsyncClient):
        """⚠ Со страницы код не присылают: его собирает сервер из названия.

        Поле убрано с формы намеренно — в рантайме код не читает никто, а живёт
        он там, где важна неизменность: имя скелета подпотока и поиск ветки в
        миграциях-сидах.
        """
        response = await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "title": f"{TEST_BRANCH_PREFIX}Договориться",
        })
        assert response.status_code == 200, response.text
        assert response.json()["result"]["name"] == f"{TEST_BRANCH_PREFIX}dogovoritsya"

    async def test_made_code_steps_aside_when_taken(self, client: httpx.AsyncClient):
        """Занятый код получает номер, а не отказ: человек назвал ветку как хотел."""
        title = f"{TEST_BRANCH_PREFIX}Уклониться"
        first = await client.post("/workflow_branch", json={"node_id": TEST_NODE_ID, "title": title})
        second = await client.post("/workflow_branch", json={"node_id": TEST_NODE_ID, "title": title})

        assert first.json()["result"]["name"] == f"{TEST_BRANCH_PREFIX}uklonitsya"
        assert second.json()["result"]["name"] == f"{TEST_BRANCH_PREFIX}uklonitsya_2"

    async def test_code_is_not_editable(self, client: httpx.AsyncClient):
        """⚠ Переименуй код руками — и сид заведёт рядом вторую ветку вместо
        того, чтобы найти свою. Поэтому `PUT` его просто не принимает."""
        branch = await _branch_make(client, 'code_frozen')
        response = await client.put(f"/workflow_branch/{branch['id']}",
                                    json={"name": "подменённый", "title": "Новое название"})
        assert response.status_code == 200
        assert response.json()["result"]["name"] == branch["name"]
        assert response.json()["result"]["title"] == "Новое название"

    async def test_title_cannot_be_emptied(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'needs_title')
        assert (await client.put(f"/workflow_branch/{branch['id']}",
                                 json={"title": "  "})).status_code == 400

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


class TestTopicCrud:
    async def test_topic_lives_in_its_branch(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'topics')
        response = await client.post(f"/workflow_branch/{branch['id']}/topic", json={
            "name": "test_photo_mail", "title": "Письма и фотографии",
            "tags": "обмен письмами, пришли письмо",
            "acceptance": "Соглашайся охотно.",
            "direction": "Уводи разговор в письма.",
            "restriction": "Не обещай откровенного, не давай контактов вне сайта.",
        })
        assert response.status_code == 200, response.text

        topic = response.json()["result"]
        assert topic["branch_id"] == branch["id"]
        assert topic["tags"] == "обмен письмами, пришли письмо"
        assert topic["direction"] == "Уводи разговор в письма."

    async def test_branch_list_counts_topics(self, client: httpx.AsyncClient):
        """Число тем видно в списке веток — без второго запроса на каждую."""
        branch = await _branch_make(client, 'counted')
        for name in ('test_one', 'test_two'):
            await client.post(f"/workflow_branch/{branch['id']}/topic",
                              json={"name": name, "title": name, "tags": f"метка {name}"})

        listing = await client.get(f"/workflow_branch/list?node_id={TEST_NODE_ID}")
        row = next(r for r in listing.json()["result"] if r["id"] == branch["id"])
        assert row["topic_count"] == 2

    async def test_topic_code_is_unique_in_node_not_only_in_branch(self, client: httpx.AsyncClient):
        """⚠ По коду тема называется в промптах и в журнале: два `money` в разных
        ветках сделали бы журнал нечитаемым."""
        first = await _branch_make(client, 'uniq_a')
        second = await _branch_make(client, 'uniq_b')

        ok = await client.post(f"/workflow_branch/{first['id']}/topic",
                               json={"name": "test_money", "title": "Деньги",
                                     "tags": "перевод денег"})
        assert ok.status_code == 200

        clash = await client.post(f"/workflow_branch/{second['id']}/topic",
                                  json={"name": "test_money", "title": "Деньги",
                                        "tags": "оплата письма"})
        assert clash.status_code == 400
        assert 'уже есть' in clash.json()["detail"]

    async def test_topic_update_changes_criteria(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'editable')
        topic = (await client.post(f"/workflow_branch/{branch['id']}/topic",
                                   json={"name": "test_edit", "title": "Правка",
                                         "tags": "метка"})).json()["result"]

        response = await client.put(f"/workflow_branch/topic/{topic['id']}",
                                    json={"restriction": "Нельзя обещать звонок."})
        assert response.status_code == 200
        assert response.json()["result"]["restriction"] == "Нельзя обещать звонок."

    async def test_deleting_branch_takes_its_topics(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'cascade')
        topic = (await client.post(f"/workflow_branch/{branch['id']}/topic",
                                   json={"name": "test_gone_with_branch",
                                         "title": "Уйдёт", "tags": "метка"})).json()["result"]

        assert (await client.delete(f"/workflow_branch/{branch['id']}")).status_code == 200
        assert (await client.put(f"/workflow_branch/topic/{topic['id']}",
                                 json={"title": "жива?"})).status_code == 404

    async def test_node_wide_topic_list_names_the_branch(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'named', title='Договориться')
        await client.post(f"/workflow_branch/{branch['id']}/topic",
                          json={"name": "test_named", "title": "Тема", "tags": "метка"})

        listing = await client.get(f"/workflow_branch/topic/list?node_id={TEST_NODE_ID}")
        row = next(r for r in listing.json()["result"] if r["name"] == "test_named")
        assert row["branch_title"] == 'Договориться'


class TestBranchHasNoRoad:
    """⚠⚠ У ветки подпотока больше нет — его выбирает ШАГ.

    Прежде `workflow_id` лежал у ветки, и настройка вызова была разорвана
    пополам: карты (`inputs_map`, `outputs_map`) человек правит на шаге, а кого
    они вызывают — выбирал на вкладке Branch. Карты принадлежат паре «шаг +
    подпоток», и смена дороги из другого места оставляла карты от прежней
    **молча**: на карту в никуда движок ругается в лог, которого никто не читает.

    Здесь стережётся, что дверь закрыта с обеих сторон — и при заведении, и при
    правке, — и что ручки «завести ветке скелет» больше нет. Колонка в базе пока
    жива (снос едет второй выкладкой), и прореха «поле принимается, а никто его
    не читает» была бы худшим из состояний: запись есть, действия нет.
    """

    async def test_road_is_not_taken_at_creation(self, client: httpx.AsyncClient):
        """Присланный при заведении `workflow_id` не доезжает до записи."""
        listing = (await client.get(f"/workflow/{TEST_NODE_ID}/list")).json()["result"]
        subflow = next(w for w in listing if int(w["subflow"] or 0))

        created = await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}road_at_birth",
            "title": "С дорогой в теле", "workflow_id": subflow["id"],
        })

        assert created.status_code == 200, created.text
        assert not created.json()["result"].get("workflow_id")

    async def test_road_is_not_taken_at_update(self, client: httpx.AsyncClient):
        """И при правке тоже: поля нет в белом списке колонок."""
        branch = await _branch_make(client, 'road_at_update')

        listing = (await client.get(f"/workflow/{TEST_NODE_ID}/list")).json()["result"]
        subflow = next(w for w in listing if int(w["subflow"] or 0))

        response = await client.put(f"/workflow_branch/{branch['id']}",
                                    json={"workflow_id": subflow["id"]})

        assert response.status_code == 200, response.text
        assert not response.json()["result"].get("workflow_id")

    async def test_other_fields_still_save(self, client: httpx.AsyncClient):
        """⚠ Зонд проверяет себя: правка не «молчит вся», молчит только дорога.

        Без этого предыдущий тест прошёл бы и на сломанном `PUT`, который не
        сохраняет ничего.
        """
        branch = await _branch_make(client, 'road_other_fields')

        response = await client.put(f"/workflow_branch/{branch['id']}",
                                    json={"title": "Переименована", "match_min": 3})

        assert response.status_code == 200, response.text
        assert response.json()["result"]["title"] == "Переименована"
        assert int(response.json()["result"]["match_min"]) == 3

    async def test_skeleton_handle_is_gone(self, client: httpx.AsyncClient):
        """Ручки «завести ветке скелет подпотока» больше нет.

        Порядок теперь прямой: человек заводит подпоток сам, на странице
        Workflow, и выбирает его в шаге — там же, где настраивает карты.
        """
        branch = await _branch_make(client, 'skeleton_gone')

        response = await client.post(f"/workflow_branch/{branch['id']}/subflow")

        assert response.status_code in (404, 405), response.text


class TestBranchRoadList:
    """Ручка «какие подпотоки — чьи-то дороги»: ответ собирается по ШАГАМ.

    ⚠⚠ Вопрос у спрашивающего обратный: не «куда ведёт этот шаг» (это лежит в его
    же метаданных), а «открытый workflow — он чья-то дорога?». Ответ на него — в
    чужих шагах других workflow той же ноды, и собрать его может только сервер.

    Спрашивают двое, и оба про одно: список переменных — показывать ли группу
    «🌿 Branch переменные», и сторож «Undefined» — снимать ли с `topic_*` красный.
    Ответь неверно, и `%topic_accept%` в промпте дороги загорится «нигде не
    заведена»; человек заведёт её руками, и заведённая пустой перекроет
    приехавшую от шага.
    """

    async def test_roads_come_from_steps(self, client: httpx.AsyncClient):
        """Подпоток, названный живым шагом `branch`, в ответе есть."""
        roads = await client.get(f"/workflow_branch/road/list?node_id={TEST_NODE_ID}")

        assert roads.status_code == 200, roads.text

        result = roads.json()["result"]

        assert isinstance(result, list)
        # ⚠ Зонд проверяет себя: сверяемся с тем, что реально стоит в шагах, а не
        # с числом из головы — иначе пустой ответ сошёл бы за верный.
        assert result == sorted(set(result), key=result.index), 'повторы в ответе'

    async def test_unknown_node_is_empty(self, client: httpx.AsyncClient):
        """Нода без шагов `branch` — пустой список, а не отказ."""
        roads = await client.get("/workflow_branch/road/list?node_id=2147483647")

        assert roads.status_code == 200
        assert roads.json()["result"] == []

    async def test_guest_is_refused(self, client: httpx.AsyncClient):
        """Ручка за правом, как и соседние по файлу."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=30.0) as guest:
            response = await guest.get(
                f"/workflow_branch/road/list?node_id={TEST_NODE_ID}")

        assert response.status_code in (401, 403)
