"""Pytest configuration for RhapsodyAi tests."""
import os
import pytest
import asyncio
import httpx
import uuid
from typing import AsyncGenerator

from tests.constants import TEST_SESSION_UUID, TEST_SESSION_AGENT_ID, TEST_AUTH, TEST_AUTH_ROLE

# Тесты идут с хоста, а `MYSQL_HOST=mysql` — имя сервиса внутри compose-сети.
#
# Правкой одного `os.environ` тут не обойтись: `mysql_.mysql_` читает адрес
# один раз, на импорте модуля, а `config.config` вдобавок накатывает `.env.local`
# с `override=True` — то есть любое значение, выставленное до импорта, вернётся
# обратно в `mysql`. Поэтому переопределяем и окружение (для всего, что читает
# конфиг позже), и уже связанные атрибуты модуля.
#
# Делается на импорте conftest — раньше, чем pytest импортирует модули тестов, и
# значит раньше любого их `from mysql_.mysql_ import ...`.
MYSQL_TEST_HOST = 'localhost'
MYSQL_TEST_PORT = '3302'

os.environ['MYSQL_HOST'] = MYSQL_TEST_HOST
os.environ['MYSQL_PORT'] = MYSQL_TEST_PORT

import mysql_.mysql_ as _mysql_module  # noqa: E402  импорт после правки окружения — намеренно

_mysql_module.host = MYSQL_TEST_HOST
_mysql_module.port = int(MYSQL_TEST_PORT)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Configure pytest-asyncio for async fixtures
pytestmark = pytest.mark.asyncio


def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring running services"
    )


# Адрес сервера, который проверяет сюита.
#
# По умолчанию это основной `uvicorn` установки — так сюиту запускает человек.
# Но QA конвейера проверяет не его, а сервер ветки подзадачи (`uvicorn_task`,
# свой порт): на общем `:8011` работает код основного чекаута, и сюита там
# зелёная независимо от того, что сделал разработчик.
#
# Поэтому адрес можно подменить окружением на один прогон:
#   BASE_URL=http://localhost:8013 .venv/bin/python3 -m pytest tests/
#
# Имя переменной то же, что уже читают `test_team_task_pages.py` и
# `manual_test_team_task.py`, — одна команда должна переключать всю сюиту.
BASE_URL = os.getenv('BASE_URL', '').strip().rstrip('/') or "http://localhost:8011"
TEST_USER_PREFIX = "test_"
TEST_AGENT_PREFIX = "test_agent_"


async def _cleanup_test_users(client: httpx.AsyncClient) -> None:
    """Delete all users with username starting with TEST_USER_PREFIX."""
    try:
        response = await client.get("/user/list")
        if response.status_code != 200:
            return
        users = response.json().get("result", [])
        test_users = [u for u in users if u.get("username", "").startswith(TEST_USER_PREFIX)]
        for user in test_users:
            try:
                await client.delete(f"/user/{user['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


async def _cleanup_test_agents(client: httpx.AsyncClient) -> None:
    """Delete all agents with name starting with TEST_AGENT_PREFIX."""
    try:
        response = await client.get("/agent/list")
        if response.status_code != 200:
            return
        agents = response.json().get("result", [])
        test_agents = [a for a in agents if a.get("name", "").startswith(TEST_AGENT_PREFIX)]
        for agent in test_agents:
            try:
                await client.delete(f"/agent/{agent['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


TEST_ROLE_NAMES = ("test_role", "updated_role")


async def _cleanup_test_roles(client: httpx.AsyncClient) -> None:
    """Delete leftover roles created by test_role_crud.py."""
    try:
        response = await client.get("/role/list")
        if response.status_code != 200:
            return
        roles = response.json().get("result", [])
        test_roles = [r for r in roles if r.get("name") in TEST_ROLE_NAMES]
        for role in test_roles:
            try:
                await client.delete(f"/role/{role['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_users() -> AsyncGenerator[None, None]:
    """Session-scoped fixture to clean up test users before and after all tests."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json=TEST_AUTH,
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)
    yield
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json=TEST_AUTH,
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)


# Все задачи сюиты называются с этого префикса (`test_task_pipeline`, `test_task_tree`,
# `test_task_metadata`, `test_planning`). Подчёркивания экранированы: в LIKE `_` — это
# любой один символ, и без экранирования шаблон подошёл бы к чужому заголовку.
TEST_TASK_TITLE_LIKE = r'\_\_pytest%'


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_tasks():
    """
    Снести задачи сюиты до и после прогона.

    Фикстуры тестов убирают за собой сами, но прерванный прогон (Ctrl-C, таймаут,
    упавший сервер) оставляет строки в рабочей БД — а конвейер их подхватывает
    всерьёз. Задача без плана уходит живому Менеджеру независимо от статуса
    (`task_claim_task_unplanned`), и агентское время тратится на пустышку в общей
    очереди с настоящими задачами. Найдено на живой установке: 57 брошенных строк,
    15 из них ждали Менеджера, трём план был уже написан.

    Одним DELETE и по всем проектам: подзадачи, попытки и ревизии уходят каскадом
    (`fk_pt_parent`, `fk_pta_task`, `fk_ptpr_task` в `migrations/0001.sql`), а
    тестовые задачи заводятся и без проекта, и внутри него.

    Свой цикл событий и `mysql_pool_close()` — по той же причине, что у
    `create_test_user`: пул модульный и привязан к циклу, в котором создан.
    """
    from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

    async def _sweep() -> None:
        async with mysql_get_db_async() as db:
            await db.execute(
                "DELETE FROM project_task WHERE title LIKE %s", (TEST_TASK_TITLE_LIKE,))
            await db.connection.commit()

    def _run() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_sweep())
            loop.run_until_complete(mysql_pool_close())
        finally:
            loop.close()

    _run()
    yield
    _run()


@pytest.fixture(scope="session", autouse=True)
def create_test_user():
    """
    Убедиться, что QA-учётка из `TEST_AUTH` существует, и починить ей пароль.

    Пользователя (`vova.tkachenko`, роль `qa`) заводит человек, а не тесты, поэтому
    после прогона он **не удаляется** — снести чужую учётку сюита не вправе. Раньше
    фикстура создавала `test_runner` и удаляла его в конце; вдобавок его сносил
    `_cleanup_test_users()` по префиксу `test_`, и следующий прогон падал на 401.

    Пароль перезаписываем: он живёт в `.env`, и расхождение с БД — единственная
    причина, по которой вся сюита валится на логине, а выглядит это как
    «сломалась авторизация».
    """
    test_username = TEST_AUTH['username']
    test_password = TEST_AUTH['password']
    if not test_username or not test_password:
        yield
        return

    import bcrypt
    from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

    password_hash = bcrypt.hashpw(test_password.encode(), bcrypt.gensalt()).decode()

    async def _ensure():
        async with mysql_get_db_async() as db:
            await db.execute("SELECT id FROM `user` WHERE username = %s", (test_username,))
            row = await db.fetchone()
            if row:
                await db.execute(
                    "UPDATE `user` SET password_hash = %s WHERE id = %s", (password_hash, row['id']))
            else:
                # Роль ищем по имени: id роли `qa` на разных инсталляциях разный.
                await db.execute("SELECT id FROM `role` WHERE name = %s", (TEST_AUTH_ROLE,))
                role = await db.fetchone()
                await db.execute(
                    "INSERT INTO `user` (username, email, password_hash, role_id, dynamic) "
                    "VALUES (%s, %s, %s, %s, 0)",
                    (test_username, f"{test_username}@test.local", password_hash,
                     role['id'] if role else None)
                )
            await db.connection.commit()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_ensure())
    loop.run_until_complete(mysql_pool_close())
    loop.close()

    yield


@pytest.fixture(scope="session", autouse=True)
def seed_test_session():
    """Seed a known agent_session row used by session tests, clean up after."""
    from src.ai.ai_session import ai_session_message_add
    from mysql_.mysql_ import mysql_get_db_async

    req_uuid = str(uuid.uuid4())

    async def _seed():
        await ai_session_message_add(TEST_SESSION_UUID, req_uuid, None, 1, None,
                                     'user', TEST_SESSION_AGENT_ID, 'user-prompt', 'test prompt')
        await ai_session_message_add(TEST_SESSION_UUID, req_uuid, None, 1, None,
                                     'assistant', TEST_SESSION_AGENT_ID, 'response-final', 'test response')

    from mysql_.mysql_ import mysql_pool_close

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_seed())
    loop.run_until_complete(mysql_pool_close())
    loop.close()

    yield

    async def _cleanup():
        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM agent_session WHERE session_uuid = %s", (TEST_SESSION_UUID,))
            await db.connection.commit()
        await mysql_pool_close()

    loop2 = asyncio.new_event_loop()
    loop2.run_until_complete(_cleanup())
    loop2.close()