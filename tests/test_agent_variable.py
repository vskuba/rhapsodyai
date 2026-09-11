"""
Переменные агента (`agent.agent_variable`): хранение, рендер системного промпта и
приветствия, приоритет значений.

Проверяем ровно то, ради чего колонка заведена: один агент с шаблоном в промпте
заменяет сотню агентов, у которых промпт отличается одним словом. Значит важны
три вещи — переменная доезжает до записи и обратно, её значение подставляется в
`%плейсхолдер%` промпта, и переменная запроса перекрывает умолчание записи.

HTTP-часть идёт на `BASE_URL` (стенд), рендер проверяется вызовом функций — LLM
для этого не нужна, а лишний прогон workflow стоил бы минуту и токены.
"""

import json
import os

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_AGENT_PREFIX = "test_agent_"

# Имя агента, заведённого миграцией `20260911180558_agent_dating_girl_universal`
AGENT_UNIVERSAL_NAME = 'dating_girl_universal'


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        await client.post("/auth/login", json=TEST_AUTH)
        yield client


def _agent_variable_parse(agent: dict) -> dict:
    """Колонка отдаётся строкой — разбираем её так же, как это делает движок."""
    stored = agent.get("agent_variable")
    return json.loads(stored) if isinstance(stored, str) else (stored or {})


class TestAgentVariableStorage:
    """Колонка: запись, чтение, частичное обновление."""

    async def test_create_with_agent_variable(self, client: httpx.AsyncClient):
        response = await client.post("/agent", json={
            "name": f"{TEST_AGENT_PREFIX}var_create",
            "title": "Переменные при создании",
            "greeting": "",
            "prompt_system": "You are a girl %girl_name%.",
            "node_id": None, "workflow_id": None, "description": "", "role_ids": [],
            "agent_variable": {"girl_name": "Natalia"},
        })
        assert response.status_code == 200

        agent = response.json()["result"]
        assert _agent_variable_parse(agent) == {"girl_name": "Natalia"}

    async def test_agent_variable_is_separate_from_workflow_variable(self, client: httpx.AsyncClient):
        """Две колонки, два смысла: правка одной не задевает другую."""
        create = await client.post("/agent", json={
            "name": f"{TEST_AGENT_PREFIX}var_both",
            "title": "Две колонки",
            "greeting": "", "prompt_system": "",
            "node_id": None, "workflow_id": None, "description": "", "role_ids": [],
            "workflow_variable": {"girl_id": "natalia_1430119"},
            "agent_variable": {"girl_name": "Natalia"},
        })
        agent_id = create.json()["result"]["id"]

        await client.put(f"/agent/{agent_id}", json={"agent_variable": {"girl_name": "Diana"}})

        agent = (await client.get(f"/agent/{agent_id}")).json()["result"]
        assert _agent_variable_parse(agent) == {"girl_name": "Diana"}

        workflow_variable = agent["workflow_variable"]
        if isinstance(workflow_variable, str):
            workflow_variable = json.loads(workflow_variable)
        assert workflow_variable == {"girl_id": "natalia_1430119"}

    async def test_agent_variable_accepts_json_string(self, client: httpx.AsyncClient):
        """Форма админки шлёт колонку строкой (`JSON.stringify`), а не словарём.

        Внешний клиент шлёт словарь — обе формы обязаны лечь в колонку одинаково,
        иначе «сохранил в админке» и «завёл по API» дают разные записи.
        """
        create = await client.post("/agent", json={
            "name": f"{TEST_AGENT_PREFIX}var_string",
            "title": "Строкой из формы",
            "greeting": "", "prompt_system": "",
            "node_id": None, "workflow_id": None, "description": "", "role_ids": [],
            "agent_variable": json.dumps({"girl_name": "Natalia"}, ensure_ascii=False),
        })
        agent_id = create.json()["result"]["id"]
        assert _agent_variable_parse(create.json()["result"]) == {"girl_name": "Natalia"}

        await client.put(f"/agent/{agent_id}", json={
            "agent_variable": json.dumps({"girl_name": "Диана"}, ensure_ascii=False)})

        agent = (await client.get(f"/agent/{agent_id}")).json()["result"]
        assert _agent_variable_parse(agent) == {"girl_name": "Диана"}

    async def test_update_without_agent_variable_keeps_it(self, client: httpx.AsyncClient):
        """Частичное обновление: не прислали поле — значение остаётся.

        Форма админки шлёт все поля разом, а внешний клиент — только то, что
        меняет. Второй не должен стирать переменные, о которых не знает.
        """
        create = await client.post("/agent", json={
            "name": f"{TEST_AGENT_PREFIX}var_keep",
            "title": "Частичное обновление",
            "greeting": "", "prompt_system": "",
            "node_id": None, "workflow_id": None, "description": "", "role_ids": [],
            "agent_variable": {"girl_name": "Natalia"},
        })
        agent_id = create.json()["result"]["id"]

        await client.put(f"/agent/{agent_id}", json={"title": "Новое название"})

        agent = (await client.get(f"/agent/{agent_id}")).json()["result"]
        assert agent["title"] == "Новое название"
        assert _agent_variable_parse(agent) == {"girl_name": "Natalia"}


class TestAgentVariableCreateByName:
    """`POST /agent/create` — дорога внешнего сервиса: переменные приходят с заведением."""

    async def test_create_by_name_stores_agent_variable(self, client: httpx.AsyncClient):
        response = await client.post("/agent/create", json={
            "node": "Telegram",
            # workflow без шага agent_create_or_update: агент заводится записью,
            # без прогона через /chat/ask с LLM
            "workflow": "test",
            "name": f"{TEST_AGENT_PREFIX}var_by_name",
            "site": "support24",
            "prompt_system": "You are a girl %girl_name%.",
            "agent_variable": {"girl_name": "Natalia"},
        })
        assert response.status_code == 201, response.text

        agent_id = response.json()["result"]["id"]
        try:
            agent = (await client.get(f"/agent/{agent_id}")).json()["result"]
            assert _agent_variable_parse(agent) == {"girl_name": "Natalia"}

            prompt = await client.get(f"/agent/{agent_id}/prompt_system/dating_girl")
            assert prompt.json()["result"] == "You are a girl Natalia."
        finally:
            await client.delete(f"/agent/{agent_id}")


class TestAgentVariableRender:
    """Рендер: значение переменной доезжает до текста, который увидит модель."""

    async def test_prompt_system_endpoint_renders_variable(self, client: httpx.AsyncClient):
        """`GET /agent/{id}/prompt_system/{collection}` показывает собранный промпт.

        Точка ходит в движок без scope прогона — переменные агента её единственный
        источник значений, и именно поэтому они подмешиваются в рендер отдельно.
        """
        create = await client.post("/agent", json={
            "name": f"{TEST_AGENT_PREFIX}var_prompt",
            "title": "Рендер промпта",
            "greeting": "", "prompt_system": "You are a girl %girl_name% from %girl_city%.",
            "node_id": None, "workflow_id": None, "description": "", "role_ids": [],
            "agent_variable": {"girl_name": "Natalia", "girl_city": "Kyiv"},
        })
        agent_id = create.json()["result"]["id"]

        response = await client.get(f"/agent/{agent_id}/prompt_system/dating_girl")
        assert response.status_code == 200
        assert response.json()["result"] == "You are a girl Natalia from Kyiv."

    def test_request_variable_overrides_agent_variable(self):
        """Умолчание записи против значения разговора: побеждает разговор.

        Ради этого агент и остаётся один: анкеты различает не запись, а пара
        значений в `variables` запроса `POST /chat/ask`.
        """
        from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager

        entity_agent = {
            'name': 'girl', 'title': 'Девушка',
            'agent_variable': '{"girl_name": "Natalia"}',
            'prompt_system': 'You are a girl %girl_name%.',
        }

        manager = AiFrameworkAgentManager()
        assert manager._prompt_system_render(
            {'entity_agent': entity_agent}
        ) == 'You are a girl Natalia.'
        assert manager._prompt_system_render(
            {'entity_agent': entity_agent, 'workflow_variables': {'girl_name': 'Diana'}}
        ) == 'You are a girl Diana.'

    def test_agent_variable_does_not_shadow_base(self):
        """Переменная агента не подменяет базовое имя.

        Имена `agent_*`, `prompt_user`, `session_uuid` одинаковы во всех workflow,
        и шаги на них рассчитывают. Опечатка в переменной агента не должна
        уводить workflow в сторону.
        """
        from src.ai.ai_workflow import ai_workflow_variables_base

        variables = ai_workflow_variables_base(
            prompt_user='привет', user_id=1, session_uuid='uuid', workflow_id=5,
            entity_agent={'id': 1, 'name': 'girl', 'title': 'Девушка',
                          'agent_variable': '{"agent_title": "подмена", "girl_name": "Natalia"}'},
        )

        assert variables['agent_title'] == 'Девушка'
        assert variables['girl_name'] == 'Natalia'

    def test_broken_json_does_not_break_run(self):
        """Битый JSON в колонке — пустой словарь и запись в журнал, а не 500."""
        from src.ai.ai_workflow import ai_workflow_variables_agent_get

        assert ai_workflow_variables_agent_get({'name': 'girl', 'agent_variable': '{не json'}) == {}
        assert ai_workflow_variables_agent_get({'name': 'girl'}) == {}

    def test_text_render_keeps_string_type(self):
        """Промпт из одного плейсхолдера остаётся строкой.

        У общего рендера переменных есть «умная замена типов»: строка ровно из
        `%имя%` возвращает исходное значение с его типом. Для промпта это ловушка —
        в движок уехал бы список или число.
        """
        from src.ai.ai_workflow import ai_workflow_text_render

        assert ai_workflow_text_render('%facts%', {'facts': ['a', 'b']}) == "['a', 'b']"
        assert ai_workflow_text_render('%missing%', {'missing': None}) == ''


class TestAgentUniversalDatingGirl:
    """Универсальная «Девушка»: та самая запись, ради которой всё это заведено."""

    async def test_universal_agent_prompt_is_template(self, client: httpx.AsyncClient):
        response = await client.request("GET", "/agent/list", json={"find_by": {"name": AGENT_UNIVERSAL_NAME}})
        agents = response.json().get("result") or []
        if not agents:
            pytest.skip(f'агента {AGENT_UNIVERSAL_NAME} нет: узел Dating не заведён на этой установке')

        agent = (await client.get(f"/agent/{agents[0]['id']}")).json()["result"]

        assert '%girl_name%' in agent['prompt_system'], 'промпт должен остаться шаблоном, а не копией имени'
        assert '%girl_title%' not in agent['prompt_system'], (
            '%girl_title% — proxy-переменная узла со значением %prompt_user%: '
            'имя собеседницы подменилось бы текстом входящего сообщения'
        )
        assert _agent_variable_parse(agent).get('girl_name'), 'умолчание имени должно быть задано'
