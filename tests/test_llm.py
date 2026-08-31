import os
from tests.constants import TEST_AUTH
"""LLM endpoint tests — /llm/list, /llm/status, /llm/usage/stats."""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.ai

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

    async def _body(self, name, reasoning_disable=1):
        """
        Тело запроса, которое уйдёт провайдеру. Наружу ничего не летит — мок
        подменяет транспорт у уже собранной моделью фабрики.

        Собираем через настоящий `llm_model_get`, а не руками: половина дефектов
        сидела как раз в нём — провайдер `openrouter` подменялся общим, и профиль
        модели приезжал чужой.
        """
        import httpx
        from pydantic_ai import Agent
        from ai.framework.ai_framework import AbstractAiFramework

        model = AbstractAiFramework.llm_model_get(self._model(reasoning_disable, False, name))
        model._provider._client._client._transport = httpx.MockTransport(self._reply)
        await Agent(model).run('привет')

        return TestReasoningDisable.body

    @staticmethod
    def _model(reasoning_disable, step_wants, name='openai/gpt-5.2'):
        from ai.framework.ai_framework_model import AiFrameworkModel

        row = AiFrameworkModel(name='x', prompt_user='', prompt_system='', user_id=1,
                               request_uuid='r', session_uuid='s')
        row.entity_llm_current = {'name': name, 'reasoning_disable': reasoning_disable}
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

    def test_llm_reasoning_disable_is_not_step_default(self):
        """
        «Шаг не просил» и «модели запрещено» — разные вещи, и путать их нельзя.

        `thinking_enable` у шага по умолчанию выключен. Слив два признака, мы
        глушили бы размышления у всех моделей на любом шаге — это уже не настройка
        модели, а смена поведения по умолчанию.
        """
        assert self._model(0, False).thinking_disabled is False, 'без флага запрета нет'
        assert self._model(1, False).thinking_disabled is True

    def test_llm_reasoning_disable_zero_string_is_not_a_ban(self):
        """`bool('0')` — истина: модель молча перестала бы размышлять."""
        for value in (0, '0', '', None, 'false'):
            assert self._model(value, True).thinking_disabled is False, f'{value!r} — это не запрет'

    @OLD_LIB
    async def test_llm_reasoning_disable_turns_model_off(self):
        assert (await self._body('openai/gpt-5.2')).get('reasoning_effort'), \
            'запрет не доехал до тела запроса'

    @OLD_LIB
    async def test_llm_reasoning_disable_reaches_openrouter(self):
        """
        Модель за OpenRouter: запрет обязан доехать и до неё.

        Собранная общим `OpenAIProvider` с подменённым адресом, она для pydantic-ai
        «просто совместимый сервер»: профиль приезжает чужой, `deepseek-v4-flash` в
        нём помечен неразмышляющим, и настройку библиотека молча выбрасывает.
        Поймано живьём — у модели в ноде Blog флаг стоял, а тело уходило пустым.
        """
        body = await self._body('openrouter/deepseek/deepseek-v4-flash-0731')

        assert body.get('reasoning_effort'), 'запрет не доехал до модели за OpenRouter'

    @OLD_LIB
    async def test_llm_reasoning_disable_falls_back_to_minimal(self):
        """
        `False` у моделей, размышляющих всегда, pydantic-ai отбрасывает: выключить
        у них нечего. Без подмены на минимум запрет молча не доезжал бы до запроса.
        """
        body = await self._body('openrouter/openai/gpt-oss-120b')

        assert body.get('reasoning_effort') in ('minimal', 'none')

    @OLD_LIB
    async def test_llm_reasoning_disable_skips_plain_model(self):
        """Лишнее поле — это 400 от провайдера, то есть сорванный ход."""
        for name in ('groq/llama-3.3-70b-versatile', 'cerebras/gpt-oss-120b',
                     'mistral/mistral-large-2512'):
            assert await self._body(name) == {}, f'{name}: лишнее поле в запросе'

    @OLD_LIB
    async def test_llm_reasoning_kept_when_not_disabled(self):
        """Разрешение — умолчание; явное «думай» меняло бы формат ответа и цену хода."""
        assert await self._body('openai/gpt-5.2', reasoning_disable=0) == {}
        assert await self._body('openrouter/deepseek/deepseek-v4-flash-0731',
                                reasoning_disable=0) == {}

    def test_llm_reasoning_local_model_uses_own_key(self):
        """
        llama.cpp переключает размышления аргументом шаблона чата, а не полем
        запроса. Профиля у неё в pydantic-ai нет — единый ключ до неё не доехал бы.
        """
        from ai.framework.ai_framework import AbstractAiFramework

        def flag(reasoning_disable, step_wants):
            model = AbstractAiFramework.llm_model_get(
                self._model(reasoning_disable, step_wants, 'gx10/qwen-medium'))
            body = dict(model.settings or {}).get('extra_body', {})
            return body.get('chat_template_kwargs', {}).get('enable_thinking')

        assert flag(0, True) is True, 'шаг просит, запрета нет — размышления даём'
        assert flag(1, True) is False, 'запрет перевешивает просьбу шага'
        assert flag(0, False) is False, 'шаг не просит — не даём'


class TestProviderStrategy:
    """
    Выбор провайдера по имени модели — `py_modules/ai/provider/`.

    Сборка была цепочкой `if` в одной функции, и особенности сервисов стояли там
    вперемешку: адрес локальной модели зависит от её размера, у Gemini свой класс
    модели, у OpenRouter свой провайдер pydantic-ai. Из-за соседства и появился
    дефект — модели за OpenRouter собирались общим провайдером, тот подсовывал
    чужой профиль, и запрет размышлений до запроса не доезжал.
    """

    @staticmethod
    def _framework_model(name):
        from ai.framework.ai_framework_model import AiFrameworkModel

        row = AiFrameworkModel(name='x', prompt_user='', prompt_system='', user_id=1,
                               request_uuid='r', session_uuid='s')
        row.entity_llm_current = {'name': name, 'reasoning_disable': 0}

        return row

    @staticmethod
    def _build(name):
        import httpx
        from ai.provider.ai_provider_registry import ai_provider_registry_model_get

        return ai_provider_registry_model_get(
            name, TestProviderStrategy._framework_model(name), httpx.AsyncClient())

    def test_llm_provider_registry_covers_every_service(self):
        """Реестр — контракт: по нему видно, какие сервисы вообще поддержаны."""
        from ai.provider.ai_provider_registry import AI_PROVIDER_REGISTRY

        assert {'openrouter', 'gx10', 'gemini', 'openai'} <= set(AI_PROVIDER_REGISTRY)

    def test_llm_provider_unknown_service_refused_by_name(self):
        """
        Отказываем сразу и по имени. Без этого вызов уходил бы в никуда и падал
        позже, уже на ответе провайдера, — там причина не видна.
        """
        import pytest as _pytest

        for bad in ('vseti/model-1', 'просто-имя', '', 'openrouter/'):
            with _pytest.raises(ValueError, match='не найден подходящий провайдер'):
                self._build(bad)

    def test_llm_provider_gemini_uses_its_own_model_class(self):
        """Gemini — единственный не по протоколу OpenAI: свой класс, не подмена адреса."""
        from pydantic_ai.models.google import GoogleModel

        assert isinstance(self._build('gemini/gemini-3-flash-preview'), GoogleModel)

    def test_llm_provider_gx10_address_depends_on_model_size(self):
        """
        Локальные модели живут на разных портах одной машины, и какой брать —
        видно из хвоста имени. У остальных сервисов адрес один на все модели.
        """
        large = str(self._build('gx10/qwen-large')._provider.base_url)
        medium = str(self._build('gx10/qwen-medium')._provider.base_url)

        assert large and medium and large != medium, 'размер модели не влияет на адрес'

    def test_llm_provider_openrouter_has_its_own_provider(self):
        """
        Общий провайдер с подменённым адресом даёт чужой профиль модели, и запрет
        размышлений теряется. Проверяем сам класс: именно он приносит правильный.
        """
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        model = self._build('openrouter/deepseek/deepseek-v4-flash-0731')

        assert isinstance(model._provider, OpenRouterProvider)


class TestProviderRawCall:
    """
    Сырой путь стратегии: адрес и тело для запроса **мимо pydantic-ai**.

    Зачем он есть. Пинг моделей пула (`team_llm_ping`) не собирает модель — ему нужно
    одно: постучаться и посмотреть код ответа. Но особенности сервисов от этого никуда
    не деваются, и знать их обязана стратегия, а не вызывающий: разбирай пинг `.env`
    и способы гасить размышления сам, у проекта появилось бы второе место, знающее про
    сервисы, — и разошлось бы оно на первой же новой модели.

    Главное здесь — **запрет размышлений**. Модель, ушедшая в рассуждение, тратит на
    него весь бюджет ответа: `qwen3.7-flash` с `max_tokens: 1` не уложился в 45 секунд
    и вернул `content: null` при полном `reasoning`. Проверка объявила бы мёртвой
    прекрасно работающую модель — и отобрала бы её у конвейера.
    """

    @staticmethod
    def _provider(name):
        from ai.provider.ai_provider_registry import ai_provider_registry_get

        return ai_provider_registry_get(name)

    def test_llm_provider_raw_unknown_service_is_none_not_raise(self):
        """
        Незнакомый сервис — `None`, а не исключение, в отличие от сборки модели.

        Решение принимает вызывающий: пинг помечает такую модель «проверить не
        смогли», а не «мертва», — и она продолжает получать круги.
        """
        for bad in ('vseti/model-1', 'просто-имя', '', 'openrouter/'):
            assert self._provider(bad) is None

    def test_llm_provider_raw_gx10_disables_thinking_by_template(self):
        """
        У llama.cpp размышления гасит аргумент шаблона чата, а не поле запроса, и
        передавать его нужно явно: у шаблона своё умолчание, «не передали» означает
        не «выключено», а «как решит модель».
        """
        body = self._provider('gx10/qwen-large').raw_body_no_thinking()

        assert body == {'chat_template_kwargs': {'enable_thinking': False}}

    def test_llm_provider_raw_openrouter_disables_thinking_by_field(self):
        """
        У маршрутизатора своё поле `reasoning`. Не `reasoning_effort`: в него единый
        ключ переводит pydantic-ai, а сырой запрос идёт мимо неё.
        """
        body = self._provider('openrouter/deepseek/deepseek-v4-flash-0731').raw_body_no_thinking()

        assert body == {'reasoning': {'enabled': False}}

    def test_llm_provider_raw_unknown_way_stays_empty(self):
        """
        Сервис, чей способ нам неизвестен, не получает выдуманного поля.

        Оно хуже отсутствующего: сервис ответит 400, и живая модель попадёт в мёртвые
        по вине самой проверки.
        """
        assert self._provider('gemini/gemini-3-flash-preview').raw_body_no_thinking() == {}

    def test_llm_provider_local_flag_marks_own_hardware(self):
        """
        Локальность — свойство сервиса, и объявляет его стратегия.

        Признак нельзя держать в атрибутах строки `llm`: моделей пула там попросту
        нет — из четырёх в справочнике заведена одна, остальные живут только в
        каталоге оболочки. А ставь мы флаг руками на каждую модель, забытая галочка
        означала бы, что пинг снова отбирает карту у работающей модели.
        """
        assert self._provider('gx10/qwen-large').local is True
        assert self._provider('ollama/qwen2.5:14b').local is True

    def test_llm_provider_network_services_are_not_local(self):
        """
        Обратная половина: у сетевых наш запрос один из многих, и проверять их можно
        свободно. Пометь мы локальными всех — пинг не проверял бы никого.
        """
        for name in ('openrouter/deepseek/deepseek-v4-flash-0731',
                     'gemini/gemini-3-flash-preview', 'openai/gpt-5'):
            assert self._provider(name).local is False, name

    def test_llm_provider_raw_gx10_address_depends_on_size(self):
        """
        Тем же правилом, что и при сборке модели: у локальной адрес свой на каждый
        размер. Сырому вызову он нужен не меньше — он идёт обычным HTTP.
        """
        large, key = self._provider('gx10/qwen-large').raw_endpoint('qwen-large')
        medium, _ = self._provider('gx10/qwen-medium').raw_endpoint('qwen-medium')

        assert large and medium and large != medium, 'размер модели не влияет на адрес'
        assert key, 'ключ один на все размеры — машина одна'
