"""
Произвольные данные задачи — project_task.metadata: API и слияние патча.

`task_metadata` импортируется внутри тестов, а не сверху файла: он тянет `mysql_`,
который читает `MYSQL_HOST` один раз при импорте, а подмена хоста на `localhost`
живёт в сессионных фикстурах `conftest.py`. Импорт на уровне модуля случился бы
раньше них — и тесты пошли бы к хосту `mysql`, которого с машины разработчика нет.
"""
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

BASE_URL = "http://localhost:8011"
TEST_TITLE = "__pytest_metadata__"


class TestTaskMetadata:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=90.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture(autouse=True)
    async def db_pool_release(self) -> AsyncGenerator[None, None]:
        """
        Закрыть пул MySQL после каждого теста.

        Пул в `mysql_` — модульный и привязан к тому циклу событий, в котором создан,
        а pytest-asyncio даёт каждому тесту свой цикл. Оставленный пул подхватил бы
        следующий тест — и упал бы на соединении из мёртвого цикла; той же причины
        не переживала бы и сессионная уборка `conftest.py`, у которой цикл свой.
        Та же дисциплина в `tests/test_planning.py`: поработал с БД — закрой пул.
        """
        yield
        from mysql_.mysql_ import mysql_pool_close
        await mysql_pool_close()

    @pytest.fixture
    async def created(self, client: httpx.AsyncClient) -> AsyncGenerator[list, None]:
        """Собирает id созданного, чтобы тест убрал за собой даже упав."""
        ids: list[int] = []
        yield ids
        for task_id in reversed(ids):
            await client.delete(f"/task/{task_id}")

    async def _create(self, client, created, title: str, metadata=None) -> dict:
        payload = {"title": f"{TEST_TITLE}{title}", "description": "временная задача теста metadata"}
        if metadata is not None:
            payload["metadata"] = metadata
        resp = await client.post("/tasks/0", json=payload)
        assert resp.status_code == 200, resp.text
        task = resp.json()["task"]
        created.append(task["id"])
        return task

    async def test_create_with_metadata(self, client, created):
        """Объект уезжает в колонку и возвращается объектом, а не JSON-строкой."""
        task = await self._create(client, created, "create", {"src": "тест", "n": 1})
        assert task["metadata"] == {"src": "тест", "n": 1}

    async def test_default_is_empty_object(self, client, created):
        """Без metadata в колонке NULL, но наружу всегда {} — читателю не надо разбирать два случая."""
        task = await self._create(client, created, "default")
        assert task["metadata"] == {}

    async def test_list_returns_parsed(self, client, created):
        """Список задач отдаёт metadata разобранным — контракт тот же, что у одиночной задачи."""
        task = await self._create(client, created, "list", {"k": "значение"})

        tasks = {t["id"]: t for t in (await client.get("/tasks/0")).json()["tasks"]}
        assert tasks[task["id"]]["metadata"] == {"k": "значение"}

    async def test_update_replaces_whole_object(self, client, created):
        """PUT кладёт то, что прислали: прежние ключи не сохраняются."""
        task = await self._create(client, created, "replace", {"a": 1, "b": 2})

        resp = await client.put(f"/task/{task['id']}", json={"metadata": {"c": 3}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["task"]["metadata"] == {"c": 3}

    async def test_update_null_clears(self, client, created):
        """null очищает поле, а не пишет строку 'null'."""
        task = await self._create(client, created, "clear", {"a": 1})

        resp = await client.put(f"/task/{task['id']}", json={"metadata": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["task"]["metadata"] == {}

    async def test_update_non_object_rejected(self, client, created):
        """Строка вместо объекта — 400, а не 500 от MySQL на CAST."""
        task = await self._create(client, created, "badtype")

        resp = await client.put(f"/task/{task['id']}", json={"metadata": "nope"})
        assert resp.status_code == 400, resp.text

    async def test_helper_merge_keeps_foreign_keys(self, client, created):
        """
        task_metadata_update сливает патч, а не перезаписывает всё.

        Ключевое свойство: над задачей одновременно работают оркестратор, воркеры и
        страница задач, и патч одного не должен уносить ключи другого.
        """
        from src.project.task.task_metadata import task_metadata_get, task_metadata_update

        task = await self._create(client, created, "merge", {"owner": "manager", "deep": {"x": 1}})

        await task_metadata_update(task["id"], {"deep": {"y": 2}, "extra": [1, 2]})
        assert await task_metadata_get(task["id"]) == {
            "owner": "manager", "deep": {"x": 1, "y": 2}, "extra": [1, 2]}

    async def test_helper_merge_none_deletes_key(self, client, created):
        """None в патче удаляет ключ — отдельная функция «удалить» не нужна."""
        from src.project.task.task_metadata import task_metadata_get, task_metadata_update

        task = await self._create(client, created, "delkey", {"a": 1, "b": 2})

        await task_metadata_update(task["id"], {"a": None})
        assert await task_metadata_get(task["id"]) == {"b": 2}

    async def test_helper_set_and_clear(self, client, created):
        """set пишет целиком, пустое значение очищает поле."""
        from src.project.task.task_metadata import task_metadata_get, task_metadata_set

        task = await self._create(client, created, "set")

        await task_metadata_set(task["id"], {"k": "значение"})
        assert await task_metadata_get(task["id"]) == {"k": "значение"}

        await task_metadata_set(task["id"], None)
        assert await task_metadata_get(task["id"]) == {}

    async def test_helper_get_missing_task(self):
        """Нет задачи — {}, а не исключение: читатель metadata никогда не падает."""
        from src.project.task.task_metadata import task_metadata_get

        assert await task_metadata_get(99999999) == {}

    def test_parse_handles_empty_and_broken(self):
        """NULL, пустая строка и не-объект дают {}."""
        from src.project.task.task_metadata import task_metadata_parse

        assert task_metadata_parse(None) == {}
        assert task_metadata_parse("") == {}
        assert task_metadata_parse("[1, 2]") == {}
        assert task_metadata_parse('{"k": 1}') == {"k": 1}
        assert task_metadata_parse({"k": 1}) == {"k": 1}
