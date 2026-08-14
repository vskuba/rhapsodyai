"""Task pipeline tests — конвейер агентов: переходы состояний и захват работы."""
import asyncio
import json
import time
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

BASE_URL = "http://localhost:8011"
TEST_TASK_TITLE = "__pytest_pipeline_task__"
CRONJOB_PATH = "src/cronjob/task_orchestrator.py"
# Тик — триггер: сбросил протухшие блокировки, поставил сообщения в Redis-очередь и вышел.
# Работу делает контейнер `worker_task`, поэтому потолок тика — секунды, а не минуты.
TICK_TIMEOUT = 60
CLIENT_TIMEOUT = TICK_TIMEOUT + 30
# Ждать приходится не тик, а воркера: шаг менеджера — это живая shell-оболочка Claude Code,
# которая читает проект и думает минутами. Потолок здесь про «воркер завис или его нет».
WAIT_TIMEOUT = 900
POLL_INTERVAL = 5


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


async def _tick_until(client: httpx.AsyncClient, task_id: int, states: tuple,
                      wait_sec: int = WAIT_TIMEOUT) -> dict:
    """
    Дёргать тики, пока задача не дойдёт до одного из `states`, но не дольше `wait_sec`.

    Ждём здесь воркера, а не тик: тик только ставит сообщение в очередь и сразу выходит,
    состояние меняется потом и в другом процессе. Тик на каждой итерации безвреден —
    задачу в переходном состоянии он не захватит, а вот следующее её действие поставит
    в очередь сразу, как воркер закончит предыдущее.

    Ограничение по времени, а не по числу тиков: план пишется всем задачам без плана,
    и бюджет действий тика может уйти на чужую строку из общей базы.
    """
    deadline = time.monotonic() + wait_sec
    while True:
        data = await _pipeline(client, task_id)
        if data["pipeline_state"] in states:
            return data
        if time.monotonic() >= deadline:
            return data
        await _tick(client)
        await asyncio.sleep(POLL_INTERVAL)


async def _tick_until_planned(client: httpx.AsyncClient, task_id: int) -> dict:
    """
    Довести задачу до готового плана — предусловие тестов, которые проверяют не самого
    менеджера, а что происходит с планом дальше.

    Отдельно от `_tick_until`, где `failed` — законная точка остановки: без этой проверки
    сорвавшийся менеджер всплывал бы позже и не там. Мёртвая shell-оболочка выглядела бы как
    400 «Плана нет» от `/pipeline/review`, хотя пересмотр тут ни при чём.
    """
    data = await _tick_until(client, task_id, ("plan_approval", "failed"))
    assert data["pipeline_state"] == "plan_approval" and data["plan_text"], (
        f"менеджер не выдал план (состояние: {data['pipeline_state']}, ошибка: {data.get('error')!r}); "
        f"причину смотреть в трассе workflow #55 — обычно это незапущенная shell-оболочка "
        f"менеджера или неразобранная Redis-очередь (нет контейнера worker)"
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
        data = await _tick_until(client, task_id, ("done", "failed"), wait_sec=WAIT_TIMEOUT * 2)
        assert data["pipeline_state"] == "done", data
        assert data["subtasks"], "после разбора плана должны появиться подзадачи"
        assert all(s["state"] == "done" for s in data["subtasks"]), data["subtasks"]

        # На каждую подзадачу должен быть след Developer и QA.
        roles = {(a["subtask_id"], a["role"]) for a in data["attempts"]}
        for s in data["subtasks"]:
            assert (s["id"], "developer") in roles
            assert (s["id"], "qa") in roles

    async def test_parallel_ticks_do_not_double_process(self, client: httpx.AsyncClient, task_id: int):
        """Кроновые запуски накладываются — сообщение в очередь должно уйти ровно одно."""
        await client.post(f"/task/{task_id}/pipeline/start")

        # Считаем job'ы именно по своей задаче: в общей базе тик может уйти на чужую.
        # Дубликат ловится на захвате: строка уже в `planning`, и второй тик её не увидит.
        marker = f"manager_plan task#{task_id} "
        queued = 0
        deadline = time.monotonic() + WAIT_TIMEOUT
        while True:
            stats = await asyncio.gather(_tick(client), _tick(client))
            queued += sum(1 for s in stats for job in s.get("jobs", []) if job.startswith(marker))
            state = (await _pipeline(client, task_id))["pipeline_state"]
            if state == "plan_approval" or time.monotonic() >= deadline:
                break
            await asyncio.sleep(POLL_INTERVAL)

        assert state == "plan_approval"
        assert queued == 1, f"планирование задачи поставлено в очередь {queued} раз(а)"


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

        data = await _tick_until(client, task_id, ("done", "failed"), wait_sec=WAIT_TIMEOUT * 2)
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
