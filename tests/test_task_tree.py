"""Дерево задач — task.parent_id: вложенность, защита от циклов, каскад."""
import os
from typing import AsyncGenerator

import httpx
import pytest

from src.project.task.task_tree import MAX_DEPTH
from tests.constants import TEST_AUTH
from tests.test_task_pipeline import _pipeline, _tick_until

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_TITLE = "__pytest_tree__"


class TestTaskTree:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=90.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def created(self, client: httpx.AsyncClient) -> AsyncGenerator[list, None]:
        """Собирает id созданного, чтобы тест убрал за собой даже упав."""
        ids: list[int] = []
        yield ids
        for task_id in reversed(ids):
            await client.delete(f"/task/{task_id}")

    async def _create(self, client, created, title: str, parent_id=None) -> int:
        resp = await client.post("/tasks/0", json={
            "title": f"{TEST_TITLE}{title}",
            "description": "временная задача теста дерева",
            "parent_id": parent_id,
        })
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["task"]["id"]
        created.append(task_id)
        return task_id

    async def test_child_created_under_parent(self, client, created):
        """Подзадача создаётся с parent_id и позицией внутри своего родителя."""
        parent = await self._create(client, created, "parent")
        first  = await self._create(client, created, "kid1", parent_id=parent)
        second = await self._create(client, created, "kid2", parent_id=parent)

        resp = await client.get("/tasks/0")
        tasks = {t["id"]: t for t in resp.json()["tasks"]}
        assert tasks[first]["parent_id"] == parent
        assert tasks[second]["parent_id"] == parent
        # Позиции считаются внутри родителя, а не сквозь весь проект.
        assert tasks[second]["position"] == tasks[first]["position"] + 1

    async def test_parent_missing_rejected(self, client, created):
        """Несуществующий родитель — 400, а не 500 от внешнего ключа."""
        resp = await client.post("/tasks/0", json={"title": f"{TEST_TITLE}orphan", "parent_id": 99999999})
        assert resp.status_code == 400, resp.text
        assert "не найдена" in resp.json()["detail"]

    async def test_self_parent_rejected(self, client, created):
        """Задача не может быть родителем самой себе."""
        task_id = await self._create(client, created, "self")
        resp = await client.put(f"/task/{task_id}", json={"parent_id": task_id})
        assert resp.status_code == 400, resp.text

    async def test_cycle_rejected(self, client, created):
        """Родителя нельзя увести внутрь собственной ветки — иначе дерево зациклится."""
        parent = await self._create(client, created, "cyc_parent")
        child  = await self._create(client, created, "cyc_child", parent_id=parent)
        grand  = await self._create(client, created, "cyc_grand", parent_id=child)

        for candidate in (child, grand):
            resp = await client.put(f"/task/{parent}", json={"parent_id": candidate})
            assert resp.status_code == 400, f"перенос #{parent} под #{candidate} должен быть отвергнут: {resp.text}"
            assert "собственной подзадачи" in resp.json()["detail"]

    async def test_depth_limit(self, client, created):
        """
        Глубина ограничена: более глубокое дерево уже не читается в таблице.

        MAX_DEPTH = 5 — это пять уровней, то есть глубины 0..4, поэтому отказ
        ожидается на шестом создании, а не на пятом.
        """
        parent = None
        for level in range(MAX_DEPTH + 2):
            resp = await client.post("/tasks/0", json={
                "title": f"{TEST_TITLE}d{level}", "parent_id": parent})
            if resp.status_code == 400:
                assert "вложенн" in resp.json()["detail"], resp.text
                assert level == MAX_DEPTH, f"лимит сработал на уровне {level}, ожидался {MAX_DEPTH}"
                return
            parent = resp.json()["task"]["id"]
            created.append(parent)
        pytest.fail("лимит вложенности не сработал")

    async def test_detach_to_root(self, client, created):
        """Пустой parent_id возвращает подзадачу в корень."""
        parent = await self._create(client, created, "det_parent")
        child  = await self._create(client, created, "det_child", parent_id=parent)

        resp = await client.put(f"/task/{child}", json={"parent_id": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["task"]["parent_id"] is None

    async def test_delete_parent_cascades(self, client, created):
        """Удаление родителя уносит всю ветку — подзадача без родителя не нужна."""
        parent = await self._create(client, created, "casc_parent")
        child  = await self._create(client, created, "casc_child", parent_id=parent)
        grand  = await self._create(client, created, "casc_grand", parent_id=child)

        resp = await client.delete(f"/task/{parent}")
        assert resp.status_code == 200, resp.text

        ids = {t["id"] for t in (await client.get("/tasks/0")).json()["tasks"]}
        assert not ({parent, child, grand} & ids), "ветка должна была уйти целиком"

    async def test_parent_not_planned_by_pipeline(self, client, created):
        """
        Менеджер планирует только листья.

        Родитель — контейнер, его планом уже является список подзадач; иначе эпик
        дал бы лишний поход в LLM и план, пересказывающий собственных детей.
        """
        parent = await self._create(client, created, "plan_parent")
        child  = await self._create(client, created, "plan_child", parent_id=parent)

        data = await _tick_until(client, child, ("plan_approval", "failed"))
        assert data["pipeline_state"] == "plan_approval", data

        parent_state = await _pipeline(client, parent)
        assert parent_state["pipeline_state"] is None, "родителя планировать не должны"
        assert not parent_state["plan_text"]
