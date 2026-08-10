# LLM — архитектура, мониторинг, вызов моделей

> Как запрос доходит до модели: `node_llm` задаёт набор и приоритет LLM для ноды,
> `ai_thread` разбирает очередь и выдаёт слоты, `AiFrameworkAgent` вызывает провайдера и
> при ошибке переключается на следующую LLM. Журнал вызовов — страница `/admin/llm`.

## Ключевые файлы

| Файл | Роль |
|------|------|
| `py_modules/ai/ai_thread.py` | Главный dispatcher: читает очередь `ai_framework_model`, запускает asyncio-таски |
| `py_modules/ai/framework/ai_framework.py` | Базовый класс `AbstractAiFramework`: `llm_model_get()`, `message_history_save()` |
| `py_modules/ai/framework/ai_framework_model.py` | `AiFrameworkModel` — dataclass запроса (name, prompt, entities_llm, entity_llm_current, thinking_enable, llm_parallel_per_agent_max…) |
| `src/ai/framework/agent/ai_framework.py` | `AiFrameworkAgent` — конкретная реализация: `engine_prepare → engine_run → engine_result_handle`, fallback на следующую LLM при ошибке |
| `src/ai/framework/agent/ai_framework_manager.py` | Создаёт `AiFrameworkModel`, загружает `entities_llm` из БД, строит system-prompt |
| `src/ai/ai_llm.py` | `ai_llm_node_get()`, `ai_llm_image_generate()`, `ai_llm_request_log()`, `ai_llm_speed_get()`, `ai_llm_parallel_per_agent_max_get()` |
| `src/uvicorn/routers/llm/llm.py` | REST API страницы /admin/llm (статистика, список моделей, управление) |
| `data/uvicorn/template/admin/llm.html` | Фронт мониторинга LLM |
| `py_modules/queue_/queue_.py` | `queue_get(name)` — простая in-memory `queue.Queue` |
| `migrations/0001.sql` | Схема таблиц `llm`, `node_llm`, `llm_request`, `node` (включая `llm_parallel_per_agent_max`) |

## Схема таблиц

### `llm` — справочник моделей
```sql
id, name (e.g. "openrouter/gpt-4o"), provider, api_key, api_url,
output_type  -- типы вывода через запятую: "text", "image", "text,image"
chunk_size   -- JSON-кеш скорости: {"10": 7000, ...}
chunk_size_refresh_at
```

### `node_llm` — привязка LLM к ноде (M:N с приоритетом)
```sql
node_id, llm_id,
position       -- порядок приоритета (меньше = выше)
rate_limit_at  -- NULL или NOW() при ошибке → опускает модель в конец сортировки
code_error     -- последний код ошибки (429, 401, 503…)
```

### `node` — агентская нода
```sql
id, name, position, migration_file, is_catchall,
llm_parallel_per_agent_max  -- 1–5, DEFAULT 1
```
`is_catchall=1` — фоллбэк-нода для агентов без своей ноды.

### `llm_request` — журнал запросов (TTL = 7 дней)
```sql
id, llm_id, user_id, node_id, status_code, duration_ms, prompt_length, error, created_at
```
Используется для метрик на странице /admin/llm и пересчёта `chunk_size`.

## Цепочка вызова LLM

```
HTTP-запрос / Telegram
       │
       ▼
framework_model_create()          ← AiFrameworkManager
  - загружает entity_agent из БД
  - вызывает ai_llm_node_get(node_id, output_type='text') → entities_llm
  - entity_llm_current = entities_llm[0]  (первая по приоритету)
  - llm_parallel_per_agent_max = ai_llm_parallel_per_agent_max_get(node_id)
  - кладёт AiFrameworkModel в queue_get('ai_framework_model')
       │
       ▼
ai_thread_framework_run()         ← py_modules/ai/ai_thread.py (единственный asyncio-таск)
  - get_nowait() из очереди
  - считает активные слоты агента: async_task_running.get(name, [])
  - если len(running) < parallel_max → берёт следующую свободную LLM → запускает новый слот
  - если все слоты заняты → requeue; TTL=60с, после — дроп с on_complete('')
       │
       ▼
AiFrameworkAgent.framework_run()  ← src/ai/framework/agent/ai_framework.py
  - engine_prepare() → llm_model_get() → строит pydantic-ai Agent с entity_llm_current
  - engine_run()     → agent.run(user_prompt, …)   ← реальный HTTP к LLM API
  - engine_result_handle()
  - ai_llm_request_log(status=200, duration_ms)
  - on_complete(response.text)
       │
       ▼  при ошибке 429/401/402/413/500/503
  - rate_limit_at = NOW() в node_llm для проблемной модели
  - entity_llm_current = entities_llm[current_idx + 1]  (следующая по приоритету)
  - continue (повторный цикл с новой LLM)
```

## Текущая параллельность

`async_task_running: dict[str, list[tuple[asyncio.Task, int]]]`  
Ключ: имя агента. Значение: список `(task, llm_id)` активных слотов.

**Что параллельно:** агенты с разными именами — да.

**Что сериализовано:** один агент ограничен `llm_parallel_per_agent_max` слотами (по умолчанию 1). Каждый параллельный слот уходит на _другую_ LLM по приоритету (перебирает `entities_llm`, исключая уже занятые `llm_id`).

По завершении задачи (`_async_task_done_callback`): убирает конкретный `task` по идентичности (`t is not task`).

**LLM внутри одного слота:** строго последовательно, фоллбэк при 429/503.

## Выбор LLM (приоритет)

```sql
SELECT l.* FROM llm l
JOIN node_llm nl ON l.id = nl.llm_id
WHERE nl.node_id = %s
ORDER BY nl.rate_limit_at ASC, nl.position ASC
```

Модели без ошибок (`rate_limit_at IS NULL`) → первыми.  
При ошибке → `rate_limit_at = NOW()` → уходит в конец.

### Фильтрация по типу

`ai_llm_node_get(node_id, output_type='text')` — возвращает только LLM, у которых `output_type` содержит нужный тип (поле `llm.output_type`, значения через запятую: `text`, `image`).

`ai_llm_filter_by_type(entities_llm, output_type='image')` — аналогичная фильтрация уже загруженного списка.

## Провайдеры LLM

Определяются по префиксу имени модели (`name.lower().startswith(provider + '/')`).  
Список провайдеров в `LLM_PROVIDERS` (`src/ai/ai_llm.py`) и в `mapping_providers` (`ai_framework.py`):

| Префикс | Провайдер | Env-переменные | Особенности |
|---------|-----------|----------------|-------------|
| `openrouter/` | OpenRouter | `OPENROUTER_API_URL`, `OPENROUTER_API_KEY` | `OpenAIChatModel` |
| `claude/` | Anthropic | `CLAUDE_API_URL`, `CLAUDE_API_KEY` | `OpenAIChatModel` |
| `ollama/` | Ollama (local) | `OLLAMA_API_URL`, `OLLAMA_API_KEY` | `OpenAIChatModel` |
| `gemini/` | Google Gemini | `GEMINI_API_URL`, `GEMINI_API_KEY` | `GoogleModel` / `GoogleProvider` |
| `groq/` | Groq | `GROQ_API_URL`, `GROQ_API_KEY` | `OpenAIChatModel` |
| `mistral/` | Mistral | `MISTRAL_API_URL`, `MISTRAL_API_KEY` | `OpenAIChatModel` |
| `huggingface/` | HuggingFace | `HUGGINGFACE_API_URL`, `HUGGINGFACE_API_KEY` | `OpenAIChatModel` |
| `cerebras/` | Cerebras | `CEREBRAS_API_URL`, `CEREBRAS_API_KEY` | `OpenAIChatModel` |
| `openai/` | OpenAI | `OPENAI_API_URL`, `OPENAI_API_KEY` | `OpenAIChatModel` |
| `gx10/` | vLLM на GX10 (192.168.1.2:8080) | `GX10_API_URL`, `GX10_API_KEY` | `OpenAIChatModel` + `ModelSettings(extra_body={"chat_template_kwargs": {"enable_thinking": ...}})` |

`gemini` — единственный, кто использует `GoogleProvider`/`GoogleModel`. Остальные — `OpenAIProvider`/`OpenAIChatModel`.

HTTP-клиент: `httpx.AsyncClient(timeout=60s, connect=10s)` с хуками логирования запроса/ответа.

### GX10 и `thinking_enable`

`gx10` поддерживает режим "thinking" через `extra_body`. Флаг `framework_model.thinking_enable: bool = False` (поле `AiFrameworkModel`) передаётся в `ModelSettings`. Включается при создании `AiFrameworkModel` если агент поддерживает thinking.

## Генерация изображений — `ai_llm_image_generate()`

**Файл:** `src/ai/ai_llm.py`

Два пути:
- `gx10/...` → **ComfyUI** (`GX10_COMFYUI_URL`, по умолчанию `http://192.168.1.2:8188`). Использует Flux.1 Dev через workflow. Параметры модели: `GX10_COMFYUI_UNET`, `GX10_COMFYUI_CLIP1`, `GX10_COMFYUI_CLIP2`, `GX10_COMFYUI_VAE`.
- Остальные провайдеры (`openai/`, `openrouter/`) → OpenAI Images API (`/v1/images/generations`), параметр `size`.

## Параллельность LLM (`llm_parallel_per_agent_max`)

### Настройка

- Колонка `node.llm_parallel_per_agent_max` (1–5, DEFAULT 1) — в `migrations/0001.sql`
- UI: select 1–5 в форме редактирования ноды (`/admin/node`)
- `ai_llm_parallel_per_agent_max_get(node_id)` в `src/ai/ai_llm.py` читает значение ноды; если `node_id=None` — берёт is_catchall-ноду

### Как работает

`async_task_running: dict[str, list[tuple[asyncio.Task, int]]]`

При поступлении запроса:
1. `running = [(t, lid) for t, lid in async_task_running.get(name, []) if not t.done()]`
2. Если `len(running) < parallel_max` — берём первую LLM из `entities_llm`, чей `id` не в `used_llm_ids`, делаем `copy.deepcopy(framework_model)`, запускаем `asyncio.Task`
3. Если все слоты заняты → requeue (TTL=60с → дроп с `on_complete('')`)

По завершении: `_async_task_done_callback` удаляет `task` из списка по идентичности объекта.

## Мониторинг (страница /admin/llm)

- **Файл роутера:** `src/uvicorn/routers/llm/llm.py`
- **Шаблон:** `data/uvicorn/template/admin/llm.html`

Что показывает:
- Список LLM с provider, статусом `rate_limit_at`, `code_error`
- Таблица `llm_request` за последние 7 дней: запросов/ошибок/avg_ms по модели
- Метрика `chunk_size` — рассчитанный оптимальный размер блока текста для ~10-секундного ответа

**`ai_llm_speed_get(llm_id, target_seconds=10)`** — возвращает `{chars_per_ms, avg_ms, chunk_size, n}`.  
Кешируется в `llm.chunk_size` (JSON, ключ = `str(target_seconds)`) на 15 минут (`CHUNK_SIZE_REFRESH_MINUTES`).  
При отсутствии данных — дефолт `chars_per_ms=1.5`, `chunk_size=max(5000, 1.5 * target * 1000 * 0.7)`.
