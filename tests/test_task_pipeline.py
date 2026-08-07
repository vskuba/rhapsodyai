"""Task pipeline tests — конвейер агентов: переходы состояний и захват работы."""
import asyncio
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

BASE_URL = "http://localhost:8011"
TEST_TASK_TITLE = "__pytest_pipeline_task__"
CRONJOB_PATH = "src/cronjob/task_orchestrator.py"
# Тик с шагом менеджера — это полный прогон workflow #55 с судьями и итерациями, и в
# минуту он не укладывается. Таймаут здесь про «шаг завис», а не про «шаг долгий».
TICK_TIMEOUT = 300
CLIENT_TIMEOUT = TICK_TIMEOUT + 30


async def _tick(client: httpx.AsyncClient, max_actions: int = 1) -> dict:
    """Один прогон оркестратора через тот же эндпоинт, которым его дёргает Cronicle."""
    resp = await client.post("/cronjob", json={
        "cronjob_path": CRONJOB_PATH,
        "metadata": {"max_actions": max_actions},
        "timeout": TICK_TIMEOUT,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _pipeline(client: httpx.AsyncClient, task_id: int) -> dict:
    resp = await client.get(f"/task/{task_id}/pipeline")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _revisions(client: httpx.AsyncClient, task_id: int) -> list:
    resp = await client.get(f"/task/{task_id}/plan/revisions")
    assert resp.status_code == 200, resp.text
    return resp.json()["revisions"]


async def _tick_until(client: httpx.AsyncClient, task_id: int, states: tuple, ticks: int = 30) -> dict:
    """
    Крутить тики, пока задача не дойдёт до одного из `states`.

    По одному тику на вызов ждать нельзя: план теперь пишется всем задачам без
    плана, и тик может уйти на чужую строку из общей базы.
    """
    for _ in range(ticks):
        data = await _pipeline(client, task_id)
        if data["pipeline_state"] in states:
            return data
        await _tick(client)
    return await _pipeline(client, task_id)


async def _tick_until_planned(client: httpx.AsyncClient, task_id: int) -> dict:
    """
    Довести задачу до готового плана — предусловие тестов, которые проверяют не самого
    менеджера, а что происходит с планом дальше.

    Отдельно от `_tick_until`, где `failed` — законная точка остановки: без этой проверки
    сорвавшийся менеджер всплывал бы позже и не там. Обрыв связи с LLM выглядел бы как
    400 «Плана нет» от `/pipeline/review`, хотя пересмотр тут ни при чём.
    """
    data = await _tick_until(client, task_id, ("pending_approval", "failed"))
    assert data["pipeline_state"] == "pending_approval" and data["plan_text"], (
        f"менеджер не выдал план (состояние: {data['pipeline_state']}, ошибка: {data.get('error')!r}); "
        f"причину смотреть в трассе workflow #55 — обычно это недоступный LLM"
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

        data = await _tick_until(client, task_id, ("pending_approval", "failed"))
        assert data["pipeline_state"] == "pending_approval", data
        assert data["plan_text"]

    async def test_plan_text_edit_keeps_subtasks(self, client: httpx.AsyncClient, task_id: int):
        """Поле «План» правится текстом, подзадачи менеджера при этом не теряются."""
        await _tick_until_planned(client, task_id)
        await client.post(f"/task/{task_id}/pipeline/approve")
        await _tick_until(client, task_id, ("split", "done", "failed"))
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

    async def test_approve_requires_pending_approval(self, client: httpx.AsyncClient, task_id: int):
        await client.post(f"/task/{task_id}/pipeline/start")
        resp = await client.post(f"/task/{task_id}/pipeline/approve")
        assert resp.status_code == 409

    async def test_manager_tick_produces_plan(self, client: httpx.AsyncClient, task_id: int):
        """new -> pending_approval, план записан, подзадач ещё нет."""
        await client.post(f"/task/{task_id}/pipeline/start")

        data = await _tick_until(client, task_id, ("pending_approval", "failed"))
        assert data["pipeline_state"] == "pending_approval"
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

        # split + по два действия на подзадачу + финализация.
        for _ in range(30):
            data = await _pipeline(client, task_id)
            if data["pipeline_state"] in ("done", "failed"):
                break
            await _tick(client)

        data = await _pipeline(client, task_id)
        assert data["pipeline_state"] == "done", data
        assert data["subtasks"], "после split должны появиться подзадачи"
        assert all(s["state"] == "done" for s in data["subtasks"]), data["subtasks"]

        # На каждую подзадачу должен быть след Developer и QA.
        roles = {(a["subtask_id"], a["role"]) for a in data["attempts"]}
        for s in data["subtasks"]:
            assert (s["id"], "developer") in roles
            assert (s["id"], "qa") in roles

    async def test_parallel_ticks_do_not_double_process(self, client: httpx.AsyncClient, task_id: int):
        """Кроновые запуски накладываются — задачу должен забрать ровно один воркер."""
        await client.post(f"/task/{task_id}/pipeline/start")

        # Считаем шаги именно по своей задаче: в общей базе тик может уйти на чужую.
        marker = f"task#{task_id} manager"
        planned = 0
        for _ in range(15):
            results = await asyncio.gather(_tick(client), _tick(client))
            planned += sum(marker in (r.get("result") or "") for r in results)
            if (await _pipeline(client, task_id))["pipeline_state"] == "pending_approval":
                break

        assert (await _pipeline(client, task_id))["pipeline_state"] == "pending_approval"
        assert planned == 1, f"план по задаче написан {planned} раз(а)"


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

    async def test_review_from_pending_approval(self, client: httpx.AsyncClient, task_id: int):
        await _tick_until_planned(client, task_id)

        resp = await client.post(f"/task/{task_id}/pipeline/review")
        assert resp.status_code == 200, resp.text
        assert (await _pipeline(client, task_id))["pipeline_state"] == "review"

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

        for _ in range(40):
            if (await _pipeline(client, task_id))["pipeline_state"] in ("done", "failed"):
                break
            await _tick(client)
        data = await _pipeline(client, task_id)
        if data["pipeline_state"] != "done":
            pytest.skip(f"задача не дошла до done: {data['pipeline_state']}")
        assert data["subtasks"], "после split должны быть подзадачи"

        before = await _revisions(client, task_id)
        assert (await client.post(f"/task/{task_id}/pipeline/review")).status_code == 200
        # Подзадачи принадлежали старому плану и удаляются вместе с отправкой на пересмотр.
        assert (await _pipeline(client, task_id))["subtasks"] == []

        data = await _tick_until_planned(client, task_id)
        assert data["pipeline_state"] == "pending_approval", data

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
