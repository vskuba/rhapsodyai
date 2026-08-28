"""
Telegram Mini App tasks endpoints tests.

Проверяются вкладка «Задачи» мини-приложения и её взаимодействие:
- GET  /telegram-app/tasks            (требует telegram owner)
- GET  /telegram-app/task-types       (требует telegram owner)
- POST /telegram-app/task/{id}/pipeline/{approve|reject|start|retry}
- GET/POST /telegram-app/task/{id}/question
- Unauthorized access (no session → 403)

Тесты конвейерных переходов меняют состояние реальных строк: работают с временной
задачей, созданной и снятой в тесте (approve/reject), а прогон отвечающего на
вопрос теста чисто проверочный — он валидирует fa-поток, не трогая живые подзадачи.
"""
import os

import asyncio
import httpx
import pytest
from typing import AsyncGenerator

from tests.constants import TEST_AUTH

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# Seeded access token for admin user (user_id=1) — inserted in migration 0002.sql
ADMIN_ACCESS_TOKEN = "a0000000-1111-4444-bbbb-000000000001"


@pytest.fixture
async def telegram_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client authenticated via access_token as telegram owner."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        auth_response = await client.post(
            "/telegram-app/auth",
            json={"init_data": "", "access_token": ADMIN_ACCESS_TOKEN},
        )
        assert auth_response.status_code == 200, "Telegram auth failed — seeded token not found"
        yield client


class TestTelegramAppTasksAuth:
    """Эндпоинты вкладки задач закрыты для неавторизованного."""

    @pytest.fixture
    async def anon_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            yield client

    async def test_tasks_list_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/tasks")
        assert response.status_code == 403

    async def test_task_types_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/task-types")
        assert response.status_code == 403

    async def test_pipeline_action_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.post("/telegram-app/task/1/pipeline/approve", json={})
        assert response.status_code == 403

    async def test_question_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.get("/telegram-app/task/1/question")
        assert response.status_code == 403

    async def test_question_answer_requires_auth(self, anon_client: httpx.AsyncClient):
        response = await anon_client.post("/telegram-app/task/1/question", json={"answers": []})
        assert response.status_code == 403


class TestTelegramAppTasksList:
    """Список задач мини-приложения — все строки конвейера с полями для фаз."""

    async def test_tasks_list_fields(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        for task in data["tasks"]:
            assert "id" in task
            assert "title" in task
            assert "status" in task
            assert "task_type_id" in task
            assert "pipeline_state" in task
            assert "goals" in task

    async def test_task_types_fields(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.get("/telegram-app/task-types")
        assert response.status_code == 200
        data = response.json()
        assert "task_types" in data
        assert isinstance(data["task_types"], list)
        for t in data["task_types"]:
            assert "id" in t
            assert "name" in t

    async def test_pipeline_unknown_action(self, telegram_client: httpx.AsyncClient):
        response = await telegram_client.post("/telegram-app/task/1/pipeline/stop", json={})
        assert response.status_code == 400


class TestTelegramAppTasksPipeline:
    """Переходы конвейера из мини-приложения — на временной задаче, без вреда живым."""

    @pytest.fixture
    async def admin_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Клиент админки: CRUD задач открыт AuthChecker-сессией (ход источника)."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
            login = await client.post("/auth/login", json=TEST_AUTH)
            assert login.status_code == 200, f"login failed: {login.status_code} {login.text}"
            yield client

    @pytest.fixture
    async def temp_task(self, admin_client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        """Корневая задача вне проекта (project_id NULL), убранная после теста."""
        created = await admin_client.post(
            "/tasks/0", json={"title": "task/2465 test task", "task_type_id": 5})
        assert created.status_code == 200, f"create failed: {created.status_code} {created.text}"
        task_id = created.json()["task"]["id"]
        try:
            yield task_id
        finally:
            await admin_client.delete(f"/task/{task_id}")

    async def test_approve_moves_plan_approval_to_approved(
            self, telegram_client: httpx.AsyncClient, temp_task: int):
        # Отправить в конвейер: менеджер в прогоне напишет план и поставит
        # `plan_approval` (в тестовом окружении тик может не всегда успеть) — поэтому
        # состояние ставим прямо в `plan_approval` тем же переходом, что конвейер.
        start = await telegram_client.post(
            f"/telegram-app/task/{temp_task}/pipeline/start", json={})
        assert start.status_code == 200
        assert start.json()["task"]["pipeline_state"] == "new"

        await _telegram_app_task_set_state(temp_task, 'plan_approval')

        approve = await telegram_client.post(
            f"/telegram-app/task/{temp_task}/pipeline/approve", json={})
        assert approve.status_code == 200
        assert approve.json()["pipeline_state"] == "approved"

        # approve ожидает `plan_approval`; повторного нажатия быть не может — 409.
        second = await telegram_client.post(
            f"/telegram-app/task/{temp_task}/pipeline/approve", json={})
        assert second.status_code == 409

    async def test_reject_returns_task_from_pipeline(
            self, telegram_client: httpx.AsyncClient, temp_task: int):
        await telegram_client.post(f"/telegram-app/task/{temp_task}/pipeline/start", json={})

        await _telegram_app_task_set_state(temp_task, 'plan_approval')

        reject = await telegram_client.post(
            f"/telegram-app/task/{temp_task}/pipeline/reject", json={})
        assert reject.status_code == 200
        assert reject.json()["task"]["pipeline_state"] is None


class TestTelegramAppTasksQuestion:
    """Чтение вопроса и ответ — тот же механизм, что на админской странице.

    Работаем на временной задаче (создана и снята в тесте): у неё нет вопроса, но
    контракт ответа проверяется, а поток «ответ на вопрос» валидируется на пустом
    ответе (отказ), не трогая живые подзадачи конвейера.
    """

    @pytest.fixture
    async def admin_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Клиент админки: CRUD задач открыт AuthChecker-сессией (ход источника)."""
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
            login = await client.post("/auth/login", json=TEST_AUTH)
            assert login.status_code == 200, f"login failed: {login.status_code} {login.text}"
            yield client

    @pytest.fixture
    async def temp_task(self, admin_client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        created = await admin_client.post(
            "/tasks/0", json={"title": "task/2465 question test"})
        assert created.status_code == 200, f"create failed: {created.status_code} {created.text}"
        task_id = created.json()["task"]["id"]
        try:
            yield task_id
        finally:
            await admin_client.delete(f"/task/{task_id}")

    async def test_question_returns_shape(
            self, telegram_client: httpx.AsyncClient, temp_task: int):
        response = await telegram_client.get(f"/telegram-app/task/{temp_task}/question")
        assert response.status_code == 200
        data = response.json()
        for key in ("question", "decisions", "goals", "attempts", "state", "error", "title"):
            assert key in data

    async def test_question_empty_answer_rejected(
            self, telegram_client: httpx.AsyncClient, temp_task: int):
        # Без выбранного варианта и без текста отвечать нечего: строка не трогается.
        response = await telegram_client.post(
            f"/telegram-app/task/{temp_task}/question", json={"answers": [], "note": ""})
        assert response.status_code in (400, 409)


async def _telegram_app_task_set_state(task_id: int, pipeline_state: str) -> None:
    """Поставить строке конвейерное состояние напрямую, без живого менеджера.

    Вызывается из async-тестов, поэтому работает в текущем цикле pytest-asyncio:
    пул `mysql_` привязан к циклу, в котором создан, и живёт вместе с ним.
    Паттерн для синхронного контекста (фикстуры `conftest.py`) — свой цикл с
    `mysql_pool_close()`; здесь этого не нужно.
    """
    from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

    await _telegram_app_task_db_update(
        "UPDATE project_task SET pipeline_state = %s WHERE id = %s",
        (pipeline_state, task_id))
    # Пул модульный и живёт один на процесс: созданный в цикле этого теста, он
    # переиспользовался бы следующим тестом из своего цикла и падал на release
    # («Event loop is closed»). Закрываем в том же цикле — тогда следующий вызов
    # заведёт пул заново в своём.
    await mysql_pool_close()


async def _telegram_app_task_db_update(statement: str, params) -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(statement, params)
        await db.connection.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])