# AI Framework — движок агентов

> Абстрактный движок живёт в `py_modules/ai/framework/`, конкретная реализация на
> pydantic-ai — в `src/ai/framework/agent/`. Запросы к агентам идут не напрямую,
> а через очередь `ai_framework_model`, которую разбирает фоновый цикл
> `ai_thread_framework_run()`.

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `py_modules/ai/framework/ai_framework.py` | `AbstractAiFramework`, `AiFrameworkResult`, исключения, выбор LLM-провайдера |
| `py_modules/ai/framework/ai_framework_model.py` | `AiFrameworkModel` — датакласс запроса к агенту |
| `py_modules/ai/framework/ai_framework_manager.py` | `AbstractAiFrameworkManager` (`framework_model_create`, `prompt_system_create`) |
| `py_modules/ai/ai_thread.py` | Фоновый цикл `ai_thread_framework_run()`: очередь, слоты, TTL |
| `py_modules/ai/ai_mcp.py` | `AiMcpManager` — подключение MCP-серверов как инструментов |
| `src/ai/framework/agent/ai_framework.py` | `AiFrameworkAgent` — реализация на pydantic-ai + failover LLM |
| `src/ai/framework/agent/ai_framework_model.py` | `AiFrameworkAgentModel` — модель + состояние workflow |
| `src/ai/framework/agent/ai_framework_manager.py` | Движок workflow: шаги, transitions, вызов инструментов |

Слои: `py_modules/` не знает про `src/` — там только абстракции и инфраструктура.
Всё, что лезет в БД проекта (`node_llm`, `ai_session`, репозитории), лежит в `src/`.

## Цепочка вызова

```
запрос (chat / Telegram / cronjob)
  ↓ AiFrameworkAgentManager.framework_model_create(metadata) → AiFrameworkAgentModel
  ↓ queue_get('ai_framework_model').put(framework_model)
  ↓ ai_thread_framework_run()            # фоновый цикл, разбирает очередь
  ↓ AiFrameworkAgent.framework_run(model) # отдельная asyncio.Task
      ↓ engine_prepare()        → pydantic_ai.Agent(model, system_prompt, output_type)
      ↓ engine_run()            → engine.run(prompt_user), asyncio.wait_for(180 c)
      ↓ ai_llm_request_log()    → журнал вызова для /admin/llm
      ↓ engine_result_handle()  → AiFrameworkResult
      ↓ message_history_save()  → история в ai_session_message
      ↓ model.on_complete(text) # + on_tokens(tokens_input, tokens_output)
```

Цикл `ai_thread_framework_run([AiFrameworkAgent()])` поднимается один раз на процесс:
`main_uvicorn.py` (в `lifespan()`), `main_telegram.py` и каждая cronjob-точка входа,
которая работает с агентами (`src/cronjob/task_orchestrator.py`,
`src/cronjob/fact/fact_verify.py`, `src/project/planning/planning_phase.py`).

## Очередь и параллельность

Слоты считаются **на агента** (`framework_model.name`), лимит —
`llm_parallel_per_agent_max` (настройка ноды, см. `llm.md`).

- все слоты заняты → модель возвращается в очередь; при первом возврате ставится
  `queued_at`;
- ждёт не дольше `AI_FRAMEWORK_QUEUE_TTL = 60.0` с — согласовано с таймаутом чата.
  По истечении TTL запрос **молча** отбрасывается, но `on_complete('')` вызывается
  обязательно, иначе ожидающий future зависнет навсегда;
- свободный слот получает копию модели (`copy.deepcopy`) — параллельные слоты не
  делят mutable-состояние;
- каждому слоту достаётся LLM, не занятая другими слотами того же агента
  (`entities_llm` минус активные `llm_id`).

Ошибку «агент занят» пользователю не показывают никогда — собеседник не должен
понять, что общается с ботом.

## Отказоустойчивость LLM

`framework_run()` ловит исключение и определяет код ошибки: `status_code`
исключения, `500` для `UnexpectedModelBehavior` (некорректный ответ провайдера),
`503` если в тексте ошибки есть `timeout`.

Коды `401, 429, 413, 402, 503, 500` → переключение на следующую LLM из
`entities_llm`; проблемной проставляется `node_llm.rate_limit_at = NOW()` и
`code_error`, чтобы она опустилась в конец сортировки. Кэш движка
(`engine_storage[name]`) сбрасывается, чтобы пересоздать `Agent` с новой моделью.

Если следующей LLM нет — вызывающему уходит `AgentRateLimitError` (лимиты) или
`LlmProviderError` (код 500) через `on_complete(..., exception=...)`.
Прочие ошибки → до двух повторных попыток той же моделью.

Провайдеры и порядок выбора — `llm.md`. Остановка агента: очередь `agent_abort`.

## Workflow-движок

`src/ai/framework/agent/ai_framework_manager.py` — `framework_workflow_run()`
последовательно выполняет шаги агента, храня состояние в
`AiFrameworkAgentModel` (`workflow_steps`, `workflow_step_current_index`,
`workflow_variables`) и в метаданных сессии (для `continue_workflow`).

Ограничители: `MAX_WORKFLOW_DEPTH = 5` (рекурсия `workflow_invoke`),
`MAX_WORKFLOW_ITERATIONS = 300` (защита от цикла after-переходов).

### Типы шагов

| Тип шага | Что делает |
|----------|-----------|
| `llm_to_json` | LLM возвращает JSON, поля кладутся в переменные |
| `llm_to_image` | Генерация изображения через LLM |
| `tool_invoke` | Вызов инструмента из `src/tool/` |
| `variable_conversion` | Преобразование переменных без LLM |
| `workflow_invoke` | Вложенный workflow (sub-workflow) |
| `return_response_llm` | Финальный ответ от LLM |
| `return_response_text` | Финальный ответ шаблоном |

Настройка — `/admin/agent_workflow`. Подробности по переменным, transitions,
правилам `inputs_map` и известным граблям — `workflow.md`;
разработка самих инструментов — `tools.md`.

Трассировка выполнения (шаги, токены, ошибки) — `workflow_trace.md`.

## MCP

Один JSON-файл на сервер в `data/mcp/` (`{DATA_DIR}/{MCP_DIR}`), схема —
`McpConfig` в `py_modules/mcp_/mcp_.py`:

```json
{
  "title": "Jira",
  "cmd": "npx",
  "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/mcp"],
  "status": "active",
  "env": ["JIRA_URL", "JIRA_API_TOKEN", "JIRA_EMAIL"],
  "tools": [
    { "name": "atlassianUserInfo", "description": "Get current user info",
      "inputSchema": { "type": "object", "properties": {} } }
  ]
}
```

- `env` — **имена** переменных окружения; значения берутся из `.env` в верхнем
  регистре. Нет значения → сессия MCP не поднимется с явной ошибкой.
- `tools` — закэшированный список инструментов сервера.
- `AiMcpManager.mcp_server_add_tools()` регистрирует через `engine.tool_plain()`
  только те инструменты, чьи имена перечислены в `framework_model.tools`.
- Сессии stdio живут в `AsyncExitStack`; закрытие — `mcp_server_close_all()`.

## Расширение

**Новый тип шага** — добавить ветку `elif step_type == '...'` в
`_workflow_steps_run()` (`src/ai/framework/agent/ai_framework_manager.py`) и UI
конфигурации на `/admin/agent_workflow`.

**Новый инструмент** — файл в `src/tool/<категория>/`, подхватывается
auto-discovery; см. `tools.md`.

**Новая реализация фреймворка** — класс в `src/ai/framework/<name>/`, наследник
`AbstractAiFramework` с методами `engine_prepare()`, `engine_run()`,
`engine_result_handle()`, `framework_run()`, `session_message_add()`. Инстанс
передаётся в `ai_thread_framework_run([...])`, а связь «модель → реализация»
идёт через `framework_model.framework_class` (имя класса).
