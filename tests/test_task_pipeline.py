"""Task pipeline tests — конвейер агентов: переходы состояний и захват работы."""
import os
import asyncio
import json
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH
from tests.pipeline_mock import pipeline_agents_mocked, pipeline_drive, pipeline_tick

pytestmark = pytest.mark.pipeline

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_TASK_TITLE = "__pytest_pipeline_task__"
# Замечание QA для теста перезапуска: узнаваемая строка, чтобы отличить сохранённое
# значение от пустого и от чужого текста, оставшегося в колонке.
QA_REMARK = "__pytest__ цель 2 не подтверждена: restore не воспроизведён"
CRONJOB_PATH = "src/cronjob/task_orchestrator.py"
# Тик — триггер: сбросил протухшие блокировки, поставил сообщения в Redis-очередь и вышел.
# Работу делает контейнер `worker_task`, поэтому потолок тика — секунды, а не минуты.
TICK_TIMEOUT = 60
CLIENT_TIMEOUT = TICK_TIMEOUT + 30
# Ожидания больше нет: агенты в тестах подменены (`tests/pipeline_mock.py`), и конвейер
# гоняется в процессе теста. Прежние `WAIT_TIMEOUT = 900` и `POLL_INTERVAL` держали
# опрос живой установки — восемнадцать тестов упирались в дедлайн, когда оболочек в
# нужной корзине не было, и давали часы прогона вместо секунд.


@pytest.fixture(autouse=True)
async def _db_pool_release():
    """
    Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой.

    Понадобилось, когда тесты перестали ждать живого воркера и начали гонять конвейер
    сами: до этого файл ходил только по HTTP и своего соединения с базой не открывал.
    Без закрытия второй тест получает соединения, заведённые в чужом, уже закрытом
    цикле — «got Future attached to a different loop».
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


async def _tick(client: httpx.AsyncClient, max_actions: int = 1) -> dict:
    """
    Один прогон оркестратора через тот же эндпоинт, которым его дёргает Cronicle.

    Returns: статистика тика `{"queued": N, "reclaimed": N, "jobs": [...]}`. `/cronjob`
    отдаёт весь stdout подпроцесса строкой в поле `result`, а перед итоговым JSON туда
    попадают строки логгера, поэтому парсим последнюю непустую строку.
    """
    resp = await client.post("/cronjob", json={
        "cronjob_path": CRONJOB_PATH,
        "metadata": {"max_actions": max_actions},
        "timeout": TICK_TIMEOUT,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "success", body
    lines = [line for line in str(body.get("result") or "").splitlines() if line.strip()]

    return json.loads(lines[-1]) if lines else {}


async def _pipeline(client: httpx.AsyncClient, task_id: int) -> dict:
    resp = await client.get(f"/task/{task_id}/pipeline")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _revisions(client: httpx.AsyncClient, task_id: int) -> list:
    resp = await client.get(f"/task/{task_id}/plan/revisions")
    assert resp.status_code == 200, resp.text
    return resp.json()["revisions"]


async def _task_row_read(task_id: int) -> dict:
    """
    Строка `project_task` как есть — минуя API.

    `/task/{id}/pipeline` отдаёт задачу, а проверять надо поля подзадачи: счётчик
    попыток и замечание QA наружу в таком виде не выходят.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT pipeline_state, pipeline_attempt_count, pipeline_error "
            "  FROM project_task WHERE id = %s", (task_id,))
        return await db.fetchone()


async def _tick_until(client: httpx.AsyncClient, task_id: int, states: tuple) -> dict:
    """
    Прогнать конвейер, пока задача не дойдёт до одного из `states`.

    **Агенты подменены, в LLM не ходим.** Проверяется маршрутизация — какое действие
    достанется задаче и куда она перейдёт после него; что именно напишет модель, к
    этому отношения не имеет.

    Раньше здесь был опрос живой установки: HTTP → тик → Redis → контейнер воркера →
    Claude Code → LLM, с потолком `wait_sec` в 900 секунд на тест. Это ловило не
    дефекты, а состояние машины: подними человек оболочки в проекте — и восемнадцать
    тестов, заводящих задачи через `/tasks/0`, ждали в пустой корзине до дедлайна.
    Шесть часов прогона против секунд.

    """
    async with pipeline_agents_mocked():
        await pipeline_drive(task_id, states)

    return await _pipeline(client, task_id)


async def _tick_until_planned(client: httpx.AsyncClient, task_id: int) -> dict:
    """
    Довести задачу до готового плана — предусловие тестов, которые проверяют не самого
    менеджера, а что происходит с планом дальше.

    Отдельно от `_tick_until`, где `failed` — законная точка остановки: без этой проверки
    сорвавшийся круг всплывал бы позже и не там.
    """
    data = await _tick_until(client, task_id, ("plan_approval", "failed"))
    assert data["pipeline_state"] == "plan_approval" and data["plan_text"], (
        f"план не записан (состояние: {data['pipeline_state']}, ошибка: {data.get('error')!r}); "
        f"агент подменён, значит дело в самом конвейере — смотреть переходы "
        f"`task_state_plan_save` и отбор `_action_claim`"
    )
    return data


class TestTaskPipeline:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=CLIENT_TIMEOUT) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def task_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        resp = await client.post("/tasks/0", json={
            "title": TEST_TASK_TITLE,
            "description": "временная задача для теста конвейера",
        })
        assert resp.status_code == 200, resp.text
        tid = resp.json()["task"]["id"]
        yield tid
        await client.delete(f"/task/{tid}")

    async def test_task_without_plan_gets_planned(self, client: httpx.AsyncClient, task_id: int):
        """Задача без плана уходит к менеджеру сама — явный запуск не нужен."""
        assert (await _pipeline(client, task_id))["pipeline_state"] is None

        data = await _tick_until(client, task_id, ("plan_approval", "failed"))
        assert data["pipeline_state"] == "plan_approval", data
        assert data["plan_text"]

    async def test_plan_text_edit_keeps_subtasks(self, client: httpx.AsyncClient, task_id: int):
        """Поле «План» правится текстом, подзадачи менеджера при этом не теряются."""
        await _tick_until_planned(client, task_id)
        await client.post(f"/task/{task_id}/pipeline/approve")
        await _tick_until(client, task_id, ("processing", "done", "failed"))
        assert (await _pipeline(client, task_id))["subtasks"], "подзадачи должны быть до правки"

        resp = await client.put(f"/task/{task_id}", json={"plan_text": "Ручной план\n1. шаг"})
        assert resp.status_code == 200, resp.text

        data = await _pipeline(client, task_id)
        assert data["plan_text"] == "Ручной план\n1. шаг"
        assert data["subtasks"], "правка текста плана не должна сносить подзадачи"

    async def test_start_moves_to_new(self, client: httpx.AsyncClient, task_id: int):
        resp = await client.post(f"/task/{task_id}/pipeline/start")
        assert resp.status_code == 200
        assert (await _pipeline(client, task_id))["pipeline_state"] == "new"

    async def test_start_twice_conflicts(self, client: httpx.AsyncClient, task_id: int):
        """Повторный запуск не должен молча сбрасывать уже идущий конвейер."""
        await client.post(f"/task/{task_id}/pipeline/start")
        resp = await client.post(f"/task/{task_id}/pipeline/start")
        assert resp.status_code == 409

    async def test_approve_requires_plan_approval(self, client: httpx.AsyncClient, task_id: int):
        await client.post(f"/task/{task_id}/pipeline/start")
        resp = await client.post(f"/task/{task_id}/pipeline/approve")
        assert resp.status_code == 409

    async def test_manager_tick_produces_plan(self, client: httpx.AsyncClient, task_id: int):
        """new -> plan_approval, план записан, подзадач ещё нет."""
        await client.post(f"/task/{task_id}/pipeline/start")

        data = await _tick_until(client, task_id, ("plan_approval", "failed"))
        assert data["pipeline_state"] == "plan_approval"
        assert data["plan_text"]
        assert data["subtasks"] == [], "подзадачи не должны появляться до утверждения человеком"

    async def test_reject_leaves_pipeline(self, client: httpx.AsyncClient, task_id: int):
        await client.post(f"/task/{task_id}/pipeline/start")
        await _tick_until_planned(client, task_id)
        resp = await client.post(f"/task/{task_id}/pipeline/reject")
        assert resp.status_code == 200
        assert (await _pipeline(client, task_id))["pipeline_state"] is None

    async def test_full_run_to_done(self, client: httpx.AsyncClient, task_id: int):
        """Полный проход: план -> утверждение -> подзадачи -> Developer/QA -> done."""
        await client.post(f"/task/{task_id}/pipeline/start")
        await _tick_until_planned(client, task_id)   # manager
        await client.post(f"/task/{task_id}/pipeline/approve")

        # processing + по два действия на подзадачу + финализация — каждое отдельным job'ом.
        data = await _tick_until(client, task_id, ("done", "failed"))
        assert data["pipeline_state"] == "done", data
        assert data["subtasks"], "после разбора плана должны появиться подзадачи"
        assert all(s["state"] == "done" for s in data["subtasks"]), data["subtasks"]

        # На каждую подзадачу должен быть след Developer и QA.
        roles = {(a["subtask_id"], a["role"]) for a in data["attempts"]}
        for s in data["subtasks"]:
            assert (s["id"], "developer") in roles
            assert (s["id"], "qa") in roles

    async def test_parallel_ticks_do_not_double_process(self, client: httpx.AsyncClient, task_id: int):
        """
        Кроновые запуски накладываются — сообщение в очередь должно уйти ровно одно.

        Дубликат ловится захватом: первый тик переводит строку в `planning`, и второй
        её уже не видит. Проверяем именно это, а не итоговое состояние: дойдёт ли
        задача до плана — предмет соседних тестов, а здесь важно, сколько раз работа
        поставлена в очередь.

        Тики настоящие, в этом же процессе. Через HTTP они ушли бы в живой Redis, и
        задачу забрал бы контейнер воркера — с настоящим агентом, мимо заглушек.
        """
        await client.post(f"/task/{task_id}/pipeline/start")

        marker = f"manager_plan task#{task_id} "
        async with pipeline_agents_mocked():
            stats = await asyncio.gather(pipeline_tick(), pipeline_tick())

        queued = sum(1 for s in stats for job in s.get("jobs", []) if job.startswith(marker))

        assert queued == 1, f"планирование задачи поставлено в очередь {queued} раз(а)"
        assert (await _pipeline(client, task_id))["pipeline_state"] == "planning", \
            "захват обязан отметить строку, иначе второй тик возьмёт её снова"


class TestTaskPlanRevision:
    """Ревизии плана и пересмотр по кнопке «Обновить план»."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=CLIENT_TIMEOUT) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def task_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        resp = await client.post("/tasks/0", json={
            "title": TEST_TASK_TITLE,
            "description": "временная задача для теста ревизий",
        })
        assert resp.status_code == 200, resp.text
        tid = resp.json()["task"]["id"]
        yield tid
        await client.delete(f"/task/{tid}")

    async def test_manual_edit_creates_user_revision(self, client: httpx.AsyncClient, task_id: int):
        resp = await client.put(f"/task/{task_id}", json={"plan_text": "Ручной план\n1. шаг"})
        assert resp.status_code == 200, resp.text

        revisions = await _revisions(client, task_id)
        assert revisions, "правка плана человеком должна оставить ревизию"
        assert revisions[0]["author_kind"] == "user"
        assert revisions[0]["plan_text"] == "Ручной план\n1. шаг"

    async def test_repeated_save_adds_no_revision(self, client: httpx.AsyncClient, task_id: int):
        """Страница шлёт plan_text при каждом «Сохранить» — дублей в истории быть не должно."""
        await client.put(f"/task/{task_id}", json={"plan_text": "Ручной план"})
        before = await _revisions(client, task_id)

        await client.put(f"/task/{task_id}", json={"plan_text": "Ручной план", "title": TEST_TASK_TITLE})
        assert len(await _revisions(client, task_id)) == len(before)

    async def test_plan_edit_keeps_goals(self, client: httpx.AsyncClient, task_id: int):
        """Регресс: правка текста плана вытирала цели менеджера из pipeline_plan."""
        await _tick_until_planned(client, task_id)
        goals_before = (await _pipeline(client, task_id))["goals"]
        if not goals_before:
            pytest.skip("менеджер не вернул цели — проверять нечего")

        await client.put(f"/task/{task_id}", json={"plan_text": "Ручной план"})
        assert (await _pipeline(client, task_id))["goals"] == goals_before

    async def test_review_rejected_while_pipeline_busy(self, client: httpx.AsyncClient, task_id: int):
        """В approved план уже раскладывается — подменять его на ходу нельзя."""
        await _tick_until_planned(client, task_id)
        await client.post(f"/task/{task_id}/pipeline/approve")

        resp = await client.post(f"/task/{task_id}/pipeline/review")
        assert resp.status_code == 409, resp.text

    async def test_review_from_plan_approval(self, client: httpx.AsyncClient, task_id: int):
        await _tick_until_planned(client, task_id)

        resp = await client.post(f"/task/{task_id}/pipeline/review")
        assert resp.status_code == 200, resp.text
        assert (await _pipeline(client, task_id))["pipeline_state"] == "reviewing"

    async def test_review_twice_conflicts(self, client: httpx.AsyncClient, task_id: int):
        """Двойной клик по кнопке не должен отправлять план на пересмотр дважды."""
        await _tick_until_planned(client, task_id)
        assert (await client.post(f"/task/{task_id}/pipeline/review")).status_code == 200

        resp = await client.post(f"/task/{task_id}/pipeline/review")
        assert resp.status_code == 409, resp.text

    async def test_review_run_rewrites_plan(self, client: httpx.AsyncClient, task_id: int):
        """Полный круг: план -> подзадачи -> done -> пересмотр -> новый план от менеджера."""
        await _tick_until_planned(client, task_id)
        await client.post(f"/task/{task_id}/pipeline/approve")

        data = await _tick_until(client, task_id, ("done", "failed"))
        if data["pipeline_state"] != "done":
            pytest.skip(f"задача не дошла до done: {data['pipeline_state']}")
        assert data["subtasks"], "после разбора плана должны быть подзадачи"

        before = await _revisions(client, task_id)
        assert (await client.post(f"/task/{task_id}/pipeline/review")).status_code == 200
        # Подзадачи принадлежали старому плану и удаляются вместе с отправкой на пересмотр.
        assert (await _pipeline(client, task_id))["subtasks"] == []

        data = await _tick_until_planned(client, task_id)
        assert data["pipeline_state"] == "plan_approval", data

        after = await _revisions(client, task_id)
        assert len(after) == len(before) + 1, "пересмотр должен добавить ровно одну ревизию"
        assert after[0]["author_kind"] == "manager"

    async def test_restore_writes_plan_and_new_revision(self, client: httpx.AsyncClient, task_id: int):
        await client.put(f"/task/{task_id}", json={"plan_text": "Первый план"})
        await client.put(f"/task/{task_id}", json={"plan_text": "Второй план"})
        revisions = await _revisions(client, task_id)
        assert len(revisions) == 2, revisions
        first = revisions[-1]

        resp = await client.post(f"/task/{task_id}/plan/revision/{first['n']}/restore")
        assert resp.status_code == 200, resp.text

        assert (await _pipeline(client, task_id))["plan_text"] == first["plan_text"]
        # Откат дописывает историю, а не подменяет её.
        after = await _revisions(client, task_id)
        assert len(after) == 3
        assert after[0]["plan_text"] == first["plan_text"]
        assert after[0]["author_kind"] == "user"

    async def test_revision_of_other_task_not_found(self, client: httpx.AsyncClient, task_id: int):
        """Ревизия ищется по паре (задача, номер) — чужая не должна подменить план."""
        await client.put(f"/task/{task_id}", json={"plan_text": "Первый план"})

        resp = await client.post("/tasks/0", json={"title": TEST_TASK_TITLE, "description": "вторая"})
        other_id = resp.json()["task"]["id"]
        try:
            resp = await client.get(f"/task/{other_id}/plan/revision/1")
            assert resp.status_code == 404, resp.text
            resp = await client.post(f"/task/{other_id}/plan/revision/1/restore")
            assert resp.status_code in (400, 404), resp.text
        finally:
            await client.delete(f"/task/{other_id}")


class TestTaskPipelineBug:
    """
    Баг идёт своим путём: его берёт багфиксер, а менеджерский шаг обходит стороной.

    Живой оболочки багфиксера в тестовой среде может не быть, и это не делает тест
    бесполезным: отсутствие захвата менеджером проверяется независимо от неё, а сам
    захват — только когда карточка жива (иначе `task_role_shell_live_by_project` роли
    не увидит, и это законное поведение, а не сбой).
    """

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=CLIENT_TIMEOUT) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture(autouse=True)
    async def db_pool_release(self) -> AsyncGenerator[None, None]:
        yield
        from mysql_.mysql_ import mysql_pool_close
        await mysql_pool_close()

    @pytest.fixture
    async def bug_task(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        """
        Баг без проекта — его берёт только оболочка вне проектов, чужие не тронут.

        Типы задач отдаёт карточка команды (`GET /api/team/types`) плоским списком, без
        обёртки `result`; создание задачи возвращает `{'task': {...}}`.
        """
        resp = await client.get("/api/team/types")
        assert resp.status_code == 200, resp.text
        bug_type = next(t for t in resp.json() if t["name"] == "bug")

        resp = await client.post("/tasks/0", json={
            "title": f"{TEST_TASK_TITLE}_bug",
            "description": "Тестовый баг: воспроизведение падает на пустом входе",
            "task_type_id": bug_type["id"],
        })
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["task"]["id"]
        yield task_id
        await client.delete(f"/task/{task_id}")

    async def test_bug_is_not_taken_by_manager(self, client: httpx.AsyncClient, bug_task: int):
        """
        Менеджерский шаг баг не забирает: план у бага не пишут.

        Проверяем состоянием, а не списком jobs: тик мог поставить в очередь чужую
        работу, и её присутствие ничего про наш баг не говорит. `bugfixing` в списке
        допустимых — законный исход, если карточка багфиксера в этой среде жива.
        """
        await _tick(client, max_actions=3)
        state = (await _pipeline(client, bug_task))["pipeline_state"]
        assert state in (None, "", "new", "bugfixing", "done", "failed"), \
            f"баг ушёл в чужое состояние: {state}"

        # План — то, чего у бага быть не должно ни при каком исходе.
        assert not (await _pipeline(client, bug_task))["plan_text"], \
            "багу написали план, хотя писать его некому"

    async def test_bug_flag_off_keeps_it_out_of_work(self, client: httpx.AsyncClient, bug_task: int):
        """Снятый флажок «в багфикс» убирает баг из отбора."""
        resp = await client.post(f"/task/{bug_task}/metadata",
                                 json={"patch": {"to_bugfix": False}})
        assert resp.status_code == 200, resp.text

        await _tick(client, max_actions=3)
        state = (await _pipeline(client, bug_task))["pipeline_state"]
        assert state in (None, "", "new"), f"баг взяли в работу вопреки снятому флажку: {state}"

    async def test_start_button_clears_bugfix_flag(self, client: httpx.AsyncClient, bug_task: int):
        """
        «В конвейер» снимает флажок «в багфикс», а не только остановку.

        Без этого кнопка вела в тихий тупик: состояние менялось на `new`, а захват
        (`task_metadata_bugfix_free_sql`) баг всё равно не видел, и он оставался там
        навсегда. Ровно та же защита, что у `to_planning` для обычной задачи.
        """
        resp = await client.post(f"/task/{bug_task}/metadata",
                                 json={"patch": {"to_bugfix": False}})
        assert resp.status_code == 200, resp.text

        resp = await client.post(f"/task/{bug_task}/pipeline/start")
        assert resp.status_code == 200, resp.text

        # Отдельной ручки «прочитать одну задачу» нет — берём её из списка проекта.
        resp = await client.get("/tasks/0")
        assert resp.status_code == 200, resp.text
        task = next(t for t in resp.json()["tasks"] if t["id"] == bug_task)
        metadata = task.get("metadata") or {}
        assert metadata.get("to_bugfix") is not False, \
            f"флажок «в багфикс» остался снятым — баг не заберут: {metadata}"

    async def test_cancelled_bug_is_not_taken(self, client: httpx.AsyncClient, bug_task: int):
        """Отменённый баг в работу не уходит — у него нет ни одного шага с человеком."""
        resp = await client.put(f"/task/{bug_task}", json={"status": "cancelled"})
        assert resp.status_code == 200, resp.text

        await _tick(client, max_actions=3)
        state = (await _pipeline(client, bug_task))["pipeline_state"]
        assert state in (None, "", "new"), f"отменённый баг взяли в работу: {state}"


class TestTaskPipelineRetry:
    """
    Кнопка «Перезапустить» на задаче с заблокированными подзадачами.

    Состояния конвейера ставим прямо в БД, а не гоняем настоящий круг агентов:
    проверяется одна ручка `/pipeline/retry`, и живой Developer с QA ради этого
    не нужны — их прогон занял бы десятки минут и зависел бы от поднятых оболочек.
    """

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=CLIENT_TIMEOUT) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture(autouse=True)
    async def db_pool_release(self) -> AsyncGenerator[None, None]:
        """Пул MySQL привязан к циклу событий теста — закрываем, см. test_task_metadata."""
        yield
        from mysql_.mysql_ import mysql_pool_close
        await mysql_pool_close()

    @pytest.fixture
    async def blocked_pair(self, client: httpx.AsyncClient) -> AsyncGenerator[tuple, None]:
        """Родитель в `failed` и его подзадача из плана в `blocked` с замечанием QA."""
        from mysql_.mysql_ import mysql_get_db_async

        resp = await client.post("/tasks/0", json={
            "title": f"{TEST_TASK_TITLE}_retry", "description": "родитель для теста перезапуска"})
        assert resp.status_code == 200, resp.text
        parent = resp.json()["task"]["id"]

        resp = await client.post("/tasks/0", json={
            "title": f"{TEST_TASK_TITLE}_retry_kid", "description": "подзадача плана",
            "parent_id": parent})
        assert resp.status_code == 200, resp.text
        kid = resp.json()["task"]["id"]

        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE project_task SET pipeline_state = 'failed', pipeline_plan = %s WHERE id = %s",
                ('{"subtasks": [{"title": "подзадача плана"}]}', parent))
            await db.execute(
                "UPDATE project_task SET pipeline_from_plan = 1, pipeline_state = 'blocked', "
                "       status = 'blocked', pipeline_attempt_count = 3, pipeline_error = %s "
                " WHERE id = %s",
                (QA_REMARK, kid))
            await db.connection.commit()

        yield parent, kid

        await client.delete(f"/task/{kid}")
        await client.delete(f"/task/{parent}")

    async def test_retry_keeps_qa_remark(self, client: httpx.AsyncClient, blocked_pair: tuple):
        """
        Замечание QA переживает перезапуск — иначе следующий круг идёт с нуля.

        `_run_developer` отдаёт `pipeline_error` подзадачи агенту как `task_last_error`,
        и по нему в промптах #56 раскрывается блок «предыдущая попытка не прошла
        проверку QA — разбирайся с ошибкой, а не начинай подзадачу заново». Пока
        `retry` чистил колонку, ручной перезапуск лишал агента и текста замечания,
        и указания не переделывать сделанное.
        """
        parent, kid = blocked_pair
        resp = await client.post(f"/task/{parent}/pipeline/retry")
        assert resp.status_code == 200, resp.text

        row = await _task_row_read(kid)
        assert row["pipeline_error"] == QA_REMARK, \
            f"замечание QA стёрлось перезапуском: {row['pipeline_error']!r}"

    async def test_retry_unblocks_subtask_and_resets_attempts(
            self, client: httpx.AsyncClient, blocked_pair: tuple):
        """
        Подзадача возвращается в работу с нулём попыток.

        Без обнуления `task_claim_subtask_developable` захватит её и тут же вернёт
        в `blocked` по исчерпанному лимиту — кнопка не сделала бы ничего.
        """
        parent, kid = blocked_pair
        resp = await client.post(f"/task/{parent}/pipeline/retry")
        assert resp.status_code == 200, resp.text
        assert resp.json()["pipeline_state"] == "processing"

        row = await _task_row_read(kid)
        assert row["pipeline_state"] == "planned"
        assert row["pipeline_attempt_count"] == 0


class TestGoalsAllDone:
    """
    Пропуск круга разработчика, когда закрывать уже нечего.

    Цели проставляет сам QA, разобрав доказательство. Если закрыты все, работы для
    разработчика не осталось — он прочитает журнал, увидит сделанное и ответит
    «остаток вне моей подзадачи», потратив на это полный круг. Живьём это стоило
    подзадаче #1028 нескольких кругов подряд.
    """

    def test_task_pipeline_goals_all_done(self):
        from src.project.task.task_pipeline import _goals_all_done

        subtask = {'goals': '[{"text": "раз", "done": true}, {"text": "два", "done": true}]'}

        assert _goals_all_done(subtask) is True

    def test_task_pipeline_goals_one_left_open(self):
        from src.project.task.task_pipeline import _goals_all_done

        subtask = {'goals': '[{"text": "раз", "done": true}, {"text": "два", "done": false}]'}

        assert _goals_all_done(subtask) is False

    def test_task_pipeline_goals_empty_still_needs_round(self):
        """Пустой список — это «принимать не по чему», а не «всё сделано»."""
        from src.project.task.task_pipeline import _goals_all_done

        assert _goals_all_done({'goals': '[]'}) is False
        assert _goals_all_done({'goals': ''}) is False
        assert _goals_all_done({}) is False

    def test_task_pipeline_goals_accept_parsed_list(self):
        """Из БД приходит строкой, из кода — уже разобранным списком."""
        from src.project.task.task_pipeline import _goals_all_done

        assert _goals_all_done({'goals': [{'text': 'раз', 'done': True}]}) is True
        assert _goals_all_done({'goals': [{'text': 'раз'}]}) is False


class TestStaleTracesClosed:
    """
    Брошенные трассы закрываются тиком, а не только рестартом сервера.

    Прогон умирает вместе с процессом — воркер убили, контейнер пересоздали, —
    и запись остаётся в `running` навсегда: закрыть её больше некому. Функция для
    этого была, но звалась только на старте `main_uvicorn`, поэтому между
    рестартами записи копились.

    Проверяем именно границу: живой прогон, который просто долго молчит (шаг
    «реализация» ждёт агента до получаса), тик закрывать не должен.
    """

    def test_threshold_outlives_the_longest_step(self):
        """
        Порог молчания обязан быть больше самого долгого шага конвейера.

        Иначе тик гасил бы работу, которая идёт: у шага реализации между записями
        в трассу проходят десятки минут, и по молчанию он неотличим от мёртвого.
        """
        from src.ai.ai_workflow_trace import TRACE_RUN_STALE_SECONDS

        # Самый долгий замеренный шаг — реализация, 2517 с (подзадача #1623).
        assert TRACE_RUN_STALE_SECONDS > 2517, \
            'порог ниже реального шага — тик начнёт убивать живые прогоны'

    def test_tick_calls_the_closer(self):
        """Уборка должна быть в тике: рестарта сервера можно ждать сутками."""
        import inspect

        from src.project.task import task_pipeline

        source = inspect.getsource(task_pipeline.task_pipeline_tick)

        assert 'ai_workflow_trace_runs_stale_close' in source


class TestPlanSubtasksShown:
    """
    Разбиение из плана видно до утверждения.

    Кнопка «Утвердить» — это решение именно про разбиение, а строк подзадач до
    нажатия ещё нет: панель показывала «подзадачи появятся после «Утвердить»», и
    человек соглашался вслепую. Поймано на #1628: план предлагал две подзадачи,
    на экране не было ни одной.
    """

    def test_task_pipeline_plan_subtasks_in_response(self):
        from src.uvicorn.routers.project.project_task_pipeline import _plan_subtasks

        rows = _plan_subtasks([{'title': 'первая', 'description': 'что делать',
                                'context_lines': 1627},
                               {'title': 'вторая', 'context_lines': 1359}])

        assert [r['title'] for r in rows] == ['первая', 'вторая']
        assert [r['context_lines'] for r in rows] == [1627, 1359]

    def test_task_pipeline_plan_subtasks_keep_marks(self):
        """`split_more` и `final` решают, когда подзадача пойдёт в работу и пойдёт ли."""
        from src.uvicorn.routers.project.project_task_pipeline import _plan_subtasks

        rows = _plan_subtasks([{'title': 'крупная', 'split_more': True},
                               {'title': 'приёмка', 'final': True}])

        assert rows[0]['split_more'] is True and rows[0]['final'] is False
        assert rows[1]['final'] is True and rows[1]['split_more'] is False

    def test_task_pipeline_plan_subtasks_survive_garbage(self):
        """Планировщик — LLM: вместо числа приходит «много», вместо словаря строка."""
        from src.uvicorn.routers.project.project_task_pipeline import _plan_subtasks

        assert _plan_subtasks(None) == []
        assert _plan_subtasks(['строка', 42]) == []
        assert _plan_subtasks([{'title': 'x', 'context_lines': 'много'}])[0]['context_lines'] == 0
        assert _plan_subtasks([{'title': 'x', 'context_lines': -5}])[0]['context_lines'] == 0

    def test_task_pipeline_plan_lines_limit_matches_measurement(self):
        """
        Панель красит объём за порогом сжатия. Порог зашит в шаблоне, и разойдись он
        с тем, о чём говорит инструкция менеджера, — подсветка врала бы.
        """
        import re
        from pathlib import Path

        page = Path('data/uvicorn/template/admin/project/task.html').read_text(encoding='utf-8')
        found = re.search(r'PLAN_LINES_LIMIT\s*=\s*(\d+)', page)

        assert found, 'порог подсветки объёма пропал из панели плана'
        assert 2000 <= int(found.group(1)) <= 2600, \
            'порог разошёлся с замером ~2300 строк из role_manager.md'
