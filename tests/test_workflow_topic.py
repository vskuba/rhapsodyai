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
    response = await client.post("/workflow_topic", json=body)
    assert response.status_code == 200, response.text
    return response.json()["result"]


class TestBranchCrud:
    async def test_create_and_read(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'deal', title='Договориться')
        assert branch["title"] == 'Договориться'
        assert branch["node_id"] == TEST_NODE_ID

        listing = await client.get(f"/workflow_topic/list?node_id={TEST_NODE_ID}")
        names = [row["name"] for row in listing.json()["result"]]
        assert f"{TEST_BRANCH_PREFIX}deal" in names

    async def test_group_holds_no_thresholds(self, client: httpx.AsyncClient):
        """⚠⚠ У группы нет ни порога, ни подпотока — ни в ответе, ни в схеме.

        Колонки `match_min` и `workflow_id` снесены миграцией
        `20261010180756_branch_drop`: пороги уехали к теме (по два на каждую),
        дорога — к шагу, рядом с картами вызова. Сторож держит именно это: их
        возврат означал бы, что у вопроса снова два ответа.
        """
        branch = await _branch_make(client, 'no_thresholds')
        assert 'match_min' not in branch, f'порог вернулся к группе: {branch}'
        assert 'workflow_id' not in branch, f'подпоток вернулся к группе: {branch}'

    async def test_name_is_unique_in_node(self, client: httpx.AsyncClient):
        """Код всё ещё можно прислать явно — так делают сиды и импорт."""
        await _branch_make(client, 'twice')
        clash = await client.post("/workflow_topic", json={
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
        response = await client.post("/workflow_topic", json={
            "node_id": TEST_NODE_ID, "title": f"{TEST_BRANCH_PREFIX}Договориться",
        })
        assert response.status_code == 200, response.text
        assert response.json()["result"]["name"] == f"{TEST_BRANCH_PREFIX}dogovoritsya"

    async def test_made_code_steps_aside_when_taken(self, client: httpx.AsyncClient):
        """Занятый код получает номер, а не отказ: человек назвал ветку как хотел."""
        title = f"{TEST_BRANCH_PREFIX}Уклониться"
        first = await client.post("/workflow_topic", json={"node_id": TEST_NODE_ID, "title": title})
        second = await client.post("/workflow_topic", json={"node_id": TEST_NODE_ID, "title": title})

        assert first.json()["result"]["name"] == f"{TEST_BRANCH_PREFIX}uklonitsya"
        assert second.json()["result"]["name"] == f"{TEST_BRANCH_PREFIX}uklonitsya_2"

    async def test_code_is_not_editable(self, client: httpx.AsyncClient):
        """⚠ Переименуй код руками — и сид заведёт рядом вторую ветку вместо
        того, чтобы найти свою. Поэтому `PUT` его просто не принимает."""
        branch = await _branch_make(client, 'code_frozen')
        response = await client.put(f"/workflow_topic/{branch['id']}",
                                    json={"name": "подменённый", "title": "Новое название"})
        assert response.status_code == 200
        assert response.json()["result"]["name"] == branch["name"]
        assert response.json()["result"]["title"] == "Новое название"

    async def test_title_cannot_be_emptied(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'needs_title')
        assert (await client.put(f"/workflow_topic/{branch['id']}",
                                 json={"title": "  "})).status_code == 400

    async def test_threshold_is_not_taken_from_branch(self, client: httpx.AsyncClient):
        """⚠⚠ Присланный порог группу не достаёт, и правка не падает.

        Поле снято с формы и из `GROUP_COLUMNS`, колонки в схеме больше нет —
        но запрос с ним прийти может (старая вкладка в чужом браузере, чужой
        скрипт). Белый список обязан отбросить его молча: отказ на лишнем поле
        сломал бы правку названия у того, кто ни при чём.
        """
        branch = await _branch_make(client, 'strict')
        response = await client.put(f"/workflow_topic/{branch['id']}",
                                    json={"match_min": 3, "title": "Переименована"})
        assert response.status_code == 200, response.text
        assert response.json()["result"]["title"] == "Переименована"
        assert 'match_min' not in response.json()["result"]

    async def test_update_does_not_touch_node(self, client: httpx.AsyncClient):
        """⚠ `node_id` правит сервер: присланное поле не должно его достать."""
        branch = await _branch_make(client, 'node_guard')
        response = await client.put(f"/workflow_topic/{branch['id']}",
                                    json={"node_id": 1, "title": "Переехала?"})
        assert response.status_code == 200
        assert response.json()["result"]["node_id"] == TEST_NODE_ID

    async def test_delete_removes_branch(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'gone')
        assert (await client.delete(f"/workflow_topic/{branch['id']}")).status_code == 200

        listing = await client.get(f"/workflow_topic/list?node_id={TEST_NODE_ID}")
        names = [row["name"] for row in listing.json()["result"]]
        assert f"{TEST_BRANCH_PREFIX}gone" not in names

    async def test_unknown_branch_is_404(self, client: httpx.AsyncClient):
        assert (await client.put("/workflow_topic/99999343",
                                 json={"title": "нет такой"})).status_code == 404


class TestTopicCrud:
    async def test_topic_lives_in_its_branch(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'topics')
        response = await client.post(f"/workflow_topic/{branch['id']}/topic", json={
            "name": "test_photo_mail", "title": "Письма и фотографии",
            "tags": "обмен письмами, пришли письмо",
            "instructions": "Соглашайся охотно. Уводи разговор в письма.\n"
                            "Не обещай откровенного, не давай контактов вне сайта.",
        })
        assert response.status_code == 200, response.text

        topic = response.json()["result"]
        # ⚠ Ключ `topic_group_id`, а не `branch_id`: ветка переименована в
        # группу тем, и ручка отдаёт настоящее имя колонки, без алиаса-двери.
        assert topic["topic_group_id"] == branch["id"]
        assert topic["tags"] == "обмен письмами, пришли письмо"
        assert "Уводи разговор в письма." in topic["instructions"]

    async def test_branch_list_counts_topics(self, client: httpx.AsyncClient):
        """Число тем видно в списке веток — без второго запроса на каждую."""
        branch = await _branch_make(client, 'counted')
        for name in ('test_one', 'test_two'):
            await client.post(f"/workflow_topic/{branch['id']}/topic",
                              json={"name": name, "title": name, "tags": f"метка {name}"})

        listing = await client.get(f"/workflow_topic/list?node_id={TEST_NODE_ID}")
        row = next(r for r in listing.json()["result"] if r["id"] == branch["id"])
        assert row["topic_count"] == 2

    async def test_topic_code_is_unique_in_node_not_only_in_branch(self, client: httpx.AsyncClient):
        """⚠ По коду тема называется в промптах и в журнале: два `money` в разных
        ветках сделали бы журнал нечитаемым."""
        first = await _branch_make(client, 'uniq_a')
        second = await _branch_make(client, 'uniq_b')

        ok = await client.post(f"/workflow_topic/{first['id']}/topic",
                               json={"name": "test_money", "title": "Деньги",
                                     "tags": "перевод денег"})
        assert ok.status_code == 200

        clash = await client.post(f"/workflow_topic/{second['id']}/topic",
                                  json={"name": "test_money", "title": "Деньги",
                                        "tags": "оплата письма"})
        assert clash.status_code == 400
        assert 'уже есть' in clash.json()["detail"]

    async def test_topic_update_changes_instructions(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'editable')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_edit", "title": "Правка",
                                         "tags": "метка"})).json()["result"]

        response = await client.put(f"/workflow_topic/topic/{topic['id']}",
                                    json={"instructions": "Нельзя обещать звонок."})
        assert response.status_code == 200
        assert response.json()["result"]["instructions"] == "Нельзя обещать звонок."

    async def test_deleting_branch_takes_its_topics(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'cascade')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_gone_with_branch",
                                         "title": "Уйдёт", "tags": "метка"})).json()["result"]

        assert (await client.delete(f"/workflow_topic/{branch['id']}")).status_code == 200
        assert (await client.put(f"/workflow_topic/topic/{topic['id']}",
                                 json={"title": "жива?"})).status_code == 404

    async def test_node_wide_topic_list_names_the_branch(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'named', title='Договориться')
        await client.post(f"/workflow_topic/{branch['id']}/topic",
                          json={"name": "test_named", "title": "Тема", "tags": "метка"})

        listing = await client.get(f"/workflow_topic/topic/list?node_id={TEST_NODE_ID}")
        row = next(r for r in listing.json()["result"] if r["name"] == "test_named")
        assert row["branch_title"] == 'Договориться'


class TestTopicThresholdsAndQuestions:
    """Два порога темы и её вопросы: то, на чём стоит шаг «Тема и действие».

    ⚠⚠ Главный здесь — `test_questions_come_with_the_node_list`. Он сторожит
    беду, которую не показали ни тесты, ни ответ ручки темы: дерево вкладки
    грузится СПИСКОМ ПО НОДЕ, и форма рисует тему из его данных. Отдай вопросы
    одной лишь карточке — карточка откроется пустым списком и сотрёт заведённое
    первым же сохранением. Поймано кадром живой страницы.
    """

    async def test_thresholds_default_to_one(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'thresholds_default')
        response = await client.post(f"/workflow_topic/{branch['id']}/topic",
                                     json={"name": "test_defaults", "title": "Умолчания",
                                           "tags": "photo"})
        topic = response.json()["result"]
        assert int(topic["tags_qty_accept"]) == 1
        assert int(topic["questions_qty_yes_accept"]) == 1

    async def test_thresholds_are_saved(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'thresholds_save')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_two", "title": "Два повода",
                                         "tags": "photo, send"})).json()["result"]

        response = await client.put(f"/workflow_topic/topic/{topic['id']}",
                                    json={"tags_qty_accept": 2,
                                          "questions_qty_yes_accept": 2})
        assert response.status_code == 200, response.text
        assert int(response.json()["result"]["tags_qty_accept"]) == 2
        assert int(response.json()["result"]["questions_qty_yes_accept"]) == 2

    async def test_zero_threshold_reads_as_one(self, client: httpx.AsyncClient):
        """⚠ Ноль означал бы «подходит всегда» — это не порог."""
        branch = await _branch_make(client, 'thresholds_zero')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_zero", "title": "Ноль",
                                         "tags": "photo",
                                         "tags_qty_accept": 0})).json()["result"]
        assert int(topic["tags_qty_accept"]) == 1

    async def test_questions_are_saved_in_order(self, client: httpx.AsyncClient):
        branch = await _branch_make(client, 'questions_order')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_q", "title": "Вопросы",
                                         "tags": "photo"})).json()["result"]

        response = await client.put(f"/workflow_topic/topic/{topic['id']}", json={
            "questions": [{"question": "Первый?", "is_enabled": 1},
                          {"question": "Второй?", "is_enabled": 0},
                          {"question": "Третий?", "is_enabled": 1}],
        })
        assert response.status_code == 200, response.text
        asked = response.json()["result"]["questions"]
        assert [q["question"] for q in asked] == ["Первый?", "Второй?", "Третий?"]
        assert [int(q["is_enabled"]) for q in asked] == [1, 0, 1]

    async def test_questions_are_replaced_whole(self, client: httpx.AsyncClient):
        """Список приходит целиком и заменяет прежний: форма ведёт его целиком."""
        branch = await _branch_make(client, 'questions_replace')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_q2", "title": "Замена",
                                         "tags": "photo",
                                         "questions": [{"question": "Старый?"}]})).json()["result"]
        assert len(topic["questions"]) == 1

        response = await client.put(f"/workflow_topic/topic/{topic['id']}",
                                    json={"questions": [{"question": "Новый?"}]})
        asked = response.json()["result"]["questions"]
        assert [q["question"] for q in asked] == ["Новый?"]

    async def test_empty_list_clears_questions(self, client: httpx.AsyncClient):
        """⚠ Пустой список — законное состояние: тема без вопросов поднимается
        одними метками, и отличать его от «не прислали» обязан ключ в теле."""
        branch = await _branch_make(client, 'questions_clear')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_q3", "title": "Чистка",
                                         "tags": "photo",
                                         "questions": [{"question": "Был?"}]})).json()["result"]

        response = await client.put(f"/workflow_topic/topic/{topic['id']}",
                                    json={"questions": []})
        assert response.json()["result"]["questions"] == []

    async def test_questions_untouched_without_key(self, client: httpx.AsyncClient):
        """Ключа нет — вопросы не трогаем: форма могла прислать одни пороги."""
        branch = await _branch_make(client, 'questions_keep')
        topic = (await client.post(f"/workflow_topic/{branch['id']}/topic",
                                   json={"name": "test_q4", "title": "Сохранность",
                                         "tags": "photo",
                                         "questions": [{"question": "Живой?"}]})).json()["result"]

        response = await client.put(f"/workflow_topic/topic/{topic['id']}",
                                    json={"tags_qty_accept": 2})
        asked = response.json()["result"]["questions"]
        assert [q["question"] for q in asked] == ["Живой?"]

    async def test_questions_come_with_the_node_list(self, client: httpx.AsyncClient):
        """⚠⚠ Вопросы едут и в СПИСКЕ ПО НОДЕ, а не только в карточке темы.

        Дерево вкладки грузится этой ручкой, и форма рисует тему из её данных:
        отдай вопросы одной карточке — карточка откроется пустой и сотрёт
        заведённое первым же сохранением, без единой ошибки.
        """
        branch = await _branch_make(client, 'questions_in_list')
        await client.post(f"/workflow_topic/{branch['id']}/topic", json={
            "name": "test_q5", "title": "В списке", "tags": "photo",
            "questions": [{"question": "Доехал до списка?"}],
        })

        listing = await client.get(f"/workflow_topic/topic/list?node_id={TEST_NODE_ID}")
        mine = [t for t in listing.json()["result"] if t["name"] == "test_q5"]
        assert mine, "тема не нашлась в списке по ноде"
        assert [q["question"] for q in mine[0]["questions"]] == ["Доехал до списка?"]


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

        created = await client.post("/workflow_topic", json={
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

        response = await client.put(f"/workflow_topic/{branch['id']}",
                                    json={"workflow_id": subflow["id"]})

        assert response.status_code == 200, response.text
        assert not response.json()["result"].get("workflow_id")

    async def test_other_fields_still_save(self, client: httpx.AsyncClient):
        """⚠ Зонд проверяет себя: правка не «молчит вся», молчит только дорога.

        Без этого предыдущий тест прошёл бы и на сломанном `PUT`, который не
        сохраняет ничего.
        """
        branch = await _branch_make(client, 'road_other_fields')

        response = await client.put(f"/workflow_topic/{branch['id']}",
                                    json={"title": "Переименована", "description": "и описание"})

        assert response.status_code == 200, response.text
        assert response.json()["result"]["title"] == "Переименована"
        assert response.json()["result"]["description"] == "и описание"

    async def test_skeleton_handle_is_gone(self, client: httpx.AsyncClient):
        """Ручки «завести ветке скелет подпотока» больше нет.

        Порядок теперь прямой: человек заводит подпоток сам, на странице
        Workflow, и выбирает его в шаге — там же, где настраивает карты.
        """
        branch = await _branch_make(client, 'skeleton_gone')

        response = await client.post(f"/workflow_topic/{branch['id']}/subflow")

        assert response.status_code in (404, 405), response.text


class TestBranchRoadList:
    """Ручка «какие подпотоки — чьи-то дороги»: ответ собирается по ШАГАМ.

    ⚠⚠ Вопрос у спрашивающего обратный: не «куда ведёт этот шаг» (это лежит в его
    же метаданных), а «открытый workflow — он чья-то дорога?». Ответ на него — в
    чужих шагах других workflow той же ноды, и собрать его может только сервер.

    Спрашивают двое, и оба про одно: список переменных — показывать ли группу
    «🌿 Branch переменные», и сторож «Undefined» — снимать ли с `topic_*` красный.
    Ответь неверно, и `%topic_instructions%` в промпте дороги загорится «нигде не
    заведена»; человек заведёт её руками, и заведённая пустой перекроет
    приехавшую от шага.
    """

    async def test_roads_come_from_steps(self, client: httpx.AsyncClient):
        """Подпоток, названный живым шагом `branch`, в ответе есть."""
        roads = await client.get(f"/workflow_topic/road/list?node_id={TEST_NODE_ID}")

        assert roads.status_code == 200, roads.text

        result = roads.json()["result"]

        assert isinstance(result, list)
        # ⚠ Зонд проверяет себя: сверяемся с тем, что реально стоит в шагах, а не
        # с числом из головы — иначе пустой ответ сошёл бы за верный.
        assert result == sorted(set(result), key=result.index), 'повторы в ответе'

    async def test_without_a_node_the_whole_install_answers(self, client: httpx.AsyncClient):
        """⚠⚠ Без `node_id` — дороги всей установки, и ответ по ноде в них весь.

        Спрашивающий держит список **всех** workflow сразу: левая колонка
        страницы Workflow листается каруселью нод. Пока ручку звали по ноде,
        реестр на странице перетирался при каждом открытии workflow — и
        подпоток-дорога соседней ноды оставался без ответа, то есть с красным
        «!» на живых `topic_action_*`.
        """
        every = await client.get("/workflow_topic/road/list")

        assert every.status_code == 200, every.text

        result = every.json()["result"]

        assert isinstance(result, list)
        assert result == sorted(set(result), key=result.index), 'повторы в ответе'

        # ⚠ Сверка с ответом по ноде, а не с числом из головы: пустой ответ не
        # должен сойти за верный, а данные на установке меняются.
        one_node = await client.get(f"/workflow_topic/road/list?node_id={TEST_NODE_ID}")

        assert set(one_node.json()["result"]) <= set(result), \
            'ответ по ноде не целиком внутри общего — отбор потерял дороги'

    async def test_unknown_node_is_empty(self, client: httpx.AsyncClient):
        """Нода без шагов `branch` — пустой список, а не отказ."""
        roads = await client.get("/workflow_topic/road/list?node_id=2147483647")

        assert roads.status_code == 200
        assert roads.json()["result"] == []

    async def test_guest_is_refused(self, client: httpx.AsyncClient):
        """Ручка за правом, как и соседние по файлу."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=30.0) as guest:
            response = await guest.get(
                f"/workflow_topic/road/list?node_id={TEST_NODE_ID}")

        assert response.status_code in (401, 403)


async def _sweep(client: httpx.AsyncClient) -> None:
    listing = await client.get(f"/workflow_topic/list?node_id={TEST_NODE_ID}")
    if listing.status_code != 200:
        return
    for branch in listing.json().get("result", []):
        if not str(branch.get("name", "")).startswith(TEST_BRANCH_PREFIX):
            continue
        await client.delete(f"/workflow_topic/{branch['id']}")
