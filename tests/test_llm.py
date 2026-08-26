import os
from tests.constants import TEST_AUTH
"""LLM endpoint tests — /llm/list, /llm/status, /llm/usage/stats."""
import pytest
import httpx
from typing import AsyncGenerator

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestLlm:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    # --- /llm/list ---

    async def test_llm_list_returns_list(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert isinstance(data["result"], list)

    async def test_llm_list_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/llm/list")
            assert resp.status_code in (401, 403)

    async def test_llm_list_items_have_required_fields(self, client: httpx.AsyncClient):
        llms = (await client.get("/llm/list")).json()["result"]
        if llms:
            llm = llms[0]
            for field in ("id", "name"):
                assert field in llm, f"Missing field: {field}"

    async def test_llm_list_sorted_by_name(self, client: httpx.AsyncClient):
        llms = (await client.get("/llm/list")).json()["result"]
        names = [l["name"] for l in llms]
        assert names == sorted(names)

    # --- /llm/status ---

    async def test_llm_status_returns_result(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert "nodes" in result
        # Интервал сброса ошибок теперь в секундах (`reset_seconds`, было `reset_hours`)
        assert "reset_seconds" in result
        assert "llms" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["llms"], list)

    async def test_llm_status_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/llm/status")
            assert resp.status_code in (401, 403)

    async def test_llm_status_with_valid_node_id(self, client: httpx.AsyncClient):
        nodes = (await client.get("/llm/status")).json()["result"]["nodes"]
        if nodes:
            node_id = nodes[0]["id"]
            resp = await client.get(f"/llm/status?node_id={node_id}")
            assert resp.status_code == 200
            assert resp.json()["result"]["node_id"] == node_id

    async def test_llm_status_invalid_reset_seconds_rejected(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/status?reset_seconds=999")
        assert resp.status_code == 400

    async def test_llm_status_valid_reset_seconds(self, client: httpx.AsyncClient):
        # Значение должно быть из LLM_ERROR_RESET_SECONDS, иначе роутер отвечает 400.
        # Параметр сохраняется как настройка системы, поэтому исходное возвращаем.
        before = (await client.get("/llm/status")).json()["result"]["reset_seconds"]
        try:
            resp = await client.get("/llm/status?reset_seconds=45")
            assert resp.status_code == 200
            assert resp.json()["result"]["reset_seconds"] == 45
        finally:
            await client.get(f"/llm/status?reset_seconds={before}")

    async def test_llm_status_llm_fields(self, client: httpx.AsyncClient):
        llms = (await client.get("/llm/status")).json()["result"]["llms"]
        if llms:
            llm = llms[0]
            for field in ("id", "name", "provider", "position", "active", "requests"):
                assert field in llm, f"Missing field: {field}"
            for counter in ("m1", "m5", "m10", "d7"):
                assert counter in llm["requests"]

    # --- /llm/usage/stats ---

    async def test_llm_usage_stats_returns_result(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/usage/stats")
        assert resp.status_code == 200
        assert "result" in resp.json()

    async def test_llm_usage_stats_requires_auth(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as anon:
            resp = await anon.get("/llm/usage/stats")
            assert resp.status_code in (401, 403)

    async def test_llm_usage_stats_with_node_id(self, client: httpx.AsyncClient):
        nodes = (await client.get("/llm/status")).json()["result"]["nodes"]
        if nodes:
            node_id = nodes[0]["id"]
            resp = await client.get(f"/llm/usage/stats?node_id={node_id}")
            assert resp.status_code == 200

    async def test_llm_usage_stats_custom_days(self, client: httpx.AsyncClient):
        resp = await client.get("/llm/usage/stats?days=14")
        assert resp.status_code == 200


class TestReasoningDisable:
    """
    Запрет размышлений (`llm.reasoning_disable`) доезжает до тела запроса.

    Размышления модель тратит на внутренний монолог до ответа. Где они не нужны,
    они обходятся дважды — временем и токенами, — а локальная модель с ними
    вообще съедает бюджет ответа и возвращает пустой текст.

    Проверяем не «настройка проставилась», а что уходит провайдеру: у настройки
    два пути мимо запроса — профиль модели может её отбросить, а у моделей,
    размышляющих всегда, `False` библиотека игнорирует намеренно.
    """

    # Единый ключ размышлений появился в pydantic-ai 2.x. Версия в проекте не
    # закреплена и разъезжается между окружениями (в контейнере одна, в локальном
    # venv другая), поэтому проверки тела запроса пропускаем честным skip: на
    # старой библиотеке запрет не применяется по замыслу, а не из-за поломки.
    OLD_LIB = pytest.mark.skipif(
        'thinking' not in getattr(__import__('pydantic_ai').settings.ModelSettings,
                                  '__annotations__', {}),
        reason='pydantic-ai в этом окружении не знает единый ключ thinking (нужна 2.x)')

    @staticmethod
    def _reply(request):
        import json

        import httpx

        TestReasoningDisable.body = {
            k: v for k, v in json.loads(request.content.decode()).items()
            if k not in ('messages', 'model', 'stream')
        }

        return httpx.Response(200, json={
            'id': 'x', 'object': 'chat.completion', 'created': 0, 'model': 'm',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'ok'}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    async def _body(self, name, thinking):
        """Тело запроса, которое уйдёт провайдеру. Наружу ничего не летит — мок."""
        import httpx
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from ai.framework.ai_framework import _settings_thinking_off

        client = httpx.AsyncClient(transport=httpx.MockTransport(self._reply))
        provider = OpenAIProvider(base_url='http://stub/v1', api_key='k', http_client=client)

        model = OpenAIChatModel(name, provider=provider)
        if not thinking:
            model = OpenAIChatModel(name, provider=provider,
                                    settings=_settings_thinking_off(model))
        await Agent(model).run('привет')

        return TestReasoningDisable.body

    @staticmethod
    def _model(reasoning_disable, step_wants):
        from ai.framework.ai_framework_model import AiFrameworkModel

        row = AiFrameworkModel(name='x', prompt_user='', prompt_system='', user_id=1,
                               request_uuid='r', session_uuid='s')
        row.entity_llm_current = {'reasoning_disable': reasoning_disable}
        row.thinking_enable = step_wants

        return row

    def test_llm_reasoning_disable_beats_step_request(self):
        """
        Шаг просит размышления у всех моделей разом, а запрет ставят у той, где
        они ломают ответ. Иначе настройку пришлось бы дублировать в каждом шаге.
        """
        assert self._model(1, True).thinking is False, 'запрет обязан перевесить шаг'
        assert self._model(0, True).thinking is True
        assert self._model(0, False).thinking is False

    def test_llm_reasoning_disable_zero_string_is_not_a_ban(self):
        """`bool('0')` — истина: модель молча перестала бы размышлять."""
        for value in (0, '0', '', None, 'false'):
            assert self._model(value, True).thinking is True, f'{value!r} — это не запрет'

    @OLD_LIB
    async def test_llm_reasoning_disable_turns_model_off(self):
        body = await self._body('gpt-5.2', thinking=False)

        assert body.get('reasoning_effort'), 'запрет не доехал до тела запроса'

    @OLD_LIB
    async def test_llm_reasoning_disable_falls_back_to_minimal(self):
        """
        `False` у таких моделей pydantic-ai отбрасывает: выключить у них нечего.
        Без подмены на минимум запрет молча не доезжал бы до запроса.
        """
        body = await self._body('openai/gpt-oss-120b', thinking=False)

        assert body.get('reasoning_effort') == 'minimal'

    @OLD_LIB
    async def test_llm_reasoning_disable_skips_plain_model(self):
        """Лишнее поле — это 400 от провайдера, то есть сорванный ход."""
        for name in ('gemma-4-31b', 'llama-3.3-70b-versatile', 'mistral-large-2512'):
            assert await self._body(name, thinking=False) == {}, f'{name}: лишнее поле в запросе'

    @OLD_LIB
    async def test_llm_reasoning_kept_when_not_disabled(self):
        """Разрешение — умолчание; явное «думай» меняло бы формат ответа и цену хода."""
        assert await self._body('gpt-5.2', thinking=True) == {}
