"""`/chat/ask`: гость запускает только агентов игровой ноды (находка #2 пентеста).

Точка закрыта правом `chat:ask`, и оно есть у гостя — публичная сессия
`/auth/guest` нужна игре `/play/detective`. Но точка принимала **любой
`agent_id`**: пентест 2026-11-02 показал, что аноним дотягивался до боевого
дейтинг-агента и мог гонять его workflow за наши деньги.

Забор — по праву, не по имени роли: кто не умеет видеть агентов (`agent:view`),
тот и выбирать их свободно не вправе — ему открыта только нода `Detective`
(игра). У панели и у `dating_service` право `agent:view` есть — их не касается.

⚠ Проверяем на агенте **без workflow**: забор стоит до проверки workflow,
поэтому гостю прилетает 403 (забор), а админу — 401 «нет workflow» (забор
пропустил). Так тест ловит само решение забора, не трогая модель. Агент
заводится и убирается здесь (`mysql_query_run`, как `test_browser_site_variable`).
"""
import os
import sys
import uuid

import httpx
import pytest
from dotenv import load_dotenv

sys.path.insert(0, 'py_modules')
from mysql_.mysql_query import mysql_query_run  # noqa: E402

from tests.constants import TEST_AUTH  # noqa: E402

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.auth, pytest.mark.integration]


@pytest.fixture
async def admin():
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=10.0) as client:
        resp = await client.post('/auth/login', json=TEST_AUTH)
        assert resp.status_code == 200, resp.text
        yield client


@pytest.fixture
async def guest(admin: httpx.AsyncClient):
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=10.0) as client:
        resp = await client.post('/auth/guest', json={})
        assert resp.status_code == 200, resp.text
        guest_id = resp.json()['user']['id']

        yield client

    await admin.delete(f'/api/users/{guest_id}')


@pytest.fixture
def production_agent():
    """Временный агент на НЕ-игровой ноде, без workflow. Отдаёт id, потом сносит.

    ⚠ Нода `Dating` (id из базы по имени) — заведомо не `Detective`. Без
    workflow: забор стоит раньше проверки workflow, и этого хватает поймать его
    решение без прогона модели.
    """
    node = mysql_query_run("SELECT id FROM node WHERE name <> 'Detective'"
                           " ORDER BY id LIMIT 1")['rows'][0]['id']
    name = f'fence_probe_{uuid.uuid4().hex[:8]}'
    mysql_query_run(
        "INSERT INTO agent (name, title, description, prompt_system, greeting,"
        " node_id, dynamic, workflow_id)"
        " VALUES (%s, %s, %s, '', '', %s, 0, NULL)",
        (name, name, 'fence probe', node))
    agent_id = mysql_query_run("SELECT id FROM agent WHERE name = %s",
                               (name,))['rows'][0]['id']
    try:
        yield agent_id
    finally:
        mysql_query_run("DELETE FROM agent WHERE id = %s", (agent_id,))


class TestChatAskFence:

    async def test_guest_cannot_run_production_agent(self, guest, production_agent):
        """⚠⚠ Главное: гость не запускает агента вне игровой ноды — 403."""
        resp = await guest.post('/chat/ask',
                                json={'agent_id': production_agent, 'question': 'x'})
        assert resp.status_code == 403, f'{resp.status_code}: {resp.text[:140]}'

    async def test_admin_is_not_fenced(self, admin, production_agent):
        """Админ (`agent:view`) забором не зацеплен: проходит дальше, до проверки
        workflow — и получает 401 «нет workflow», а не 403."""
        resp = await admin.post('/chat/ask',
                                json={'agent_id': production_agent, 'question': 'x'})
        assert resp.status_code != 403, f'забор зацепил админа: {resp.text[:140]}'
        assert resp.status_code == 401, f'ожидали 401 «нет workflow»: {resp.status_code}'

    async def test_unknown_agent_is_404_before_fence(self, guest):
        """Несуществующий агент — 404: забор стоит после проверки существования."""
        resp = await guest.post('/chat/ask',
                                json={'agent_id': 10 ** 8, 'question': 'x'})
        assert resp.status_code == 404, resp.text
