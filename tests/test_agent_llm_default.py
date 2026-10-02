"""
Модель по умолчанию (`agent.llm_id`): хранение колонки и пин в выборе LLM агента.

Проверяем ровно то, ради чего колонка заведена: запрос к агенту берёт первой
запиненную модель, остальные модели ноды остаются подстраховкой, а без пина
движок берёт порядок ноды как раньше. HTTP-часть — колонка при создании и
частичном обновлении; выбор — прямым вызовом `framework_model_create`: живая
модель для этого не нужна, а лишний прогон workflow стоил бы минуту и токены.
"""

import os
import uuid

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_AGENT_PREFIX = "test_agent_llm_"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        await client.post("/auth/login", json=TEST_AUTH)
        yield client


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def llms(client: httpx.AsyncClient):
    """Две модели из справочника: пин виден на фоне порядка ноды только когда их больше одной."""
    rows = (await client.get("/llm/list")).json()["result"]
    if len(rows) < 2:
        pytest.skip('моделей в справочнике меньше двух — пин неотличим от порядка ноды')
    return rows


async def _agent_create(client: httpx.AsyncClient, **extra) -> dict:
    """Агент с уникальным именем: повторный прогон не спотыкается о u_agent_name."""
    response = await client.post("/agent", json={
        "name": f"{TEST_AGENT_PREFIX}{uuid.uuid4().hex[:8]}",
        "title": "Модель по умолчанию",
        "greeting": "",
        "prompt_system": "You are a test agent.",
        "node_id": None, "workflow_id": None, "description": "", "role_ids": [],
        **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()["result"]


class TestAgentLlmDefaultStorage:
    """Колонка: запись при создании, частичное обновление, очистка."""

    async def test_create_with_llm_id(self, client: httpx.AsyncClient, llms):
        agent = await _agent_create(client, llm_id=llms[1]["id"])
        try:
            assert agent["llm_id"] == llms[1]["id"]
        finally:
            await client.delete(f"/agent/{agent['id']}")

    async def test_partial_update_keeps_and_null_clears(self, client: httpx.AsyncClient, llms):
        agent = await _agent_create(client, llm_id=llms[0]["id"])
        try:
            # поле не прислали — значение осталось
            await client.put(f"/agent/{agent['id']}", json={"title": "Без поля в запросе"})
            kept = (await client.get(f"/agent/{agent['id']}")).json()["result"]
            assert kept["llm_id"] == llms[0]["id"]

            # прислали null — пишем: агент вернулся к порядку ноды
            await client.put(f"/agent/{agent['id']}", json={"llm_id": None})
            cleared = (await client.get(f"/agent/{agent['id']}")).json()["result"]
            assert cleared["llm_id"] is None
        finally:
            await client.delete(f"/agent/{agent['id']}")


class TestAgentLlmDefaultEngine:
    """Пин поверх порядка ноды: выбранная модель первой, подстраховка за ней."""

    async def test_pinned_llm_becomes_current(self, llms):
        """Пин первой — даже когда по порядку ноды модель была не первой."""
        from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager

        entity_agent = {
            'name': 'test', 'title': '', 'description': '',
            'node_id': 1, 'llm_id': llms[1]['id'],
        }
        model = await AiFrameworkAgentManager().framework_model_create({
            'entity_agent': entity_agent,
            'entities_llm': [dict(llms[0]), dict(llms[1])],
        })

        assert model.entity_llm_current['id'] == llms[1]['id']
        # подстраховка цела: вторая в списке — прежняя первая по ноде
        assert model.entities_llm[1]['id'] == llms[0]['id']

    async def test_without_llm_id_order_unchanged(self, llms):
        """Нет пина — порядок ноды как сейчас: текущая — первая из списка."""
        from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager

        entity_agent = {'name': 'test', 'title': '', 'description': '', 'node_id': 1}
        model = await AiFrameworkAgentManager().framework_model_create({
            'entity_agent': entity_agent,
            'entities_llm': [dict(llms[0]), dict(llms[1])],
        })

        assert model.entity_llm_current['id'] == llms[0]['id']

    async def test_pin_outside_node_list_keeps_order(self, llms):
        """Пина нет в списке ноды (отфильтрован типом, снят с ноды) — поведение как сейчас."""
        from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager

        entity_agent = {
            'name': 'test', 'title': '', 'description': '',
            'node_id': 1, 'llm_id': 2 ** 30,
        }
        model = await AiFrameworkAgentManager().framework_model_create({
            'entity_agent': entity_agent,
            'entities_llm': [dict(llms[0]), dict(llms[1])],
        })

        assert model.entity_llm_current['id'] == llms[0]['id']
        assert model.entities_llm[1]['id'] == llms[1]['id']
