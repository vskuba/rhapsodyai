# Planning — планирование продуктов

> Нода `Planning` (node_id=9) — AI-ассистированная система для превращения сырой идеи
> в полный пакет документов: анализ → рынок → продукт → техника → GTM → финансы → Blueprint.

## 1. Архитектура

### Фазы и агенты

| Фаза | Workflow id | Агент | Требует фаз |
|------|-------------|-------|-------------|
| `analyze` | 19 | `planning_analyzer` | — |
| `market` | 20 | `planning_market_researcher` | analyze |
| `product` | 21 | `planning_product_planner` | market |
| `tech` | 22 | `planning_tech_architect` | product |
| `gtm` | 23 | `planning_gtm_strategist` | tech |
| `financial` | 24 | `planning_financial_modeler` | gtm |
| `blueprint` | 25 | `planning_blueprint_composer` | все 6 выше |
| `score` | — | — | blueprint |
| `supplement_*` | 26 | `planning_supplement_writer` | blueprint |

**После blueprint:** score запускается параллельно с supplements.  
Supplements выполняются **строго последовательно** (один агент, параллельный запуск даёт busy/TPM-ошибки).  
Supplement типы: `market`, `product`, `tech`, `gtm`, `financial`, `launch`.

### LLM-нода

Planning нода (node_id=9), первичная модель: **openrouter/google/gemini-2.5-flash** (position=1).
Fallback цепочка: openrouter/gpt-oss-120b → cerebras/gpt-oss-120b → ... → mistral-large.
Выбор по `ORDER BY rate_limit_at ASC, position ASC` — rate-limited модели автоматически пропускаются.

### Вспомогательные

| Workflow id | Агент | Назначение |
|-------------|-------|-----------|
| 27 | `planning_bot` | Чат-бот: создать/статус/удалить проект |
| 28 | — | `research_loop` sub-workflow (см. §4) |
| ? | `planning_idea_generator` | Генерирует 7 идей продуктов по нише (вызывается из `/planning/ideas/generate`) |

### UI-фазы (только отображение, не запускаются)

После всех автоматических фаз в интерфейсе показан плейсхолдер следующего этапа разработки:

| Фаза | Описание |
|------|---------|
| `workload` | Фаза workload — запускается вручную после blueprint |

## 2. Таблицы БД

| Таблица | Назначение |
|---------|-----------|
| `planning_project` | Проект: idea, status, phase_current, **position** (порядок в sidebar) |
| `planning_phase` | Результаты фаз: project_id, phase, result (LONGTEXT), status |
| `planning_document` | Финальные документы: Blueprint + Supplements |
| `project_design_prototype_browser_history` | История URL браузера: project_id, url, used_at; max 15 уникальных на проект |

Статусы проекта: `pending → processing → complete | error`.  
Статусы фазы: `pending → running → complete | failed`.

`project_design_prototype_browser_history` — UNIQUE KEY `(project_id, url(512))`, обновляется через `ON DUPLICATE KEY UPDATE used_at = NOW()`, лишние записи после 15 удаляются автоматически.

## 3. Поток выполнения

### planning_worker (job в Redis-очереди, `src/worker/project/planning_worker.py`)

Цепочку фаз выполняет контейнер `worker_planning` (`rq worker-pool … planning`) — очередь своя, не общая с конвейером задач: цепочка идёт до 13 часов и в общей очереди держала бы исполнителя весь день. Кто ставит проект в очередь — тот его не планирует: инструмент, роутер и восстановление в lifespan только зовут `planning_worker_enqueue(project_id)`. Общие правила воркеров — `worker.md`.

`main_uvicorn.py` зовёт `planning_worker_recover()` **после** `ai_tool_sync()`. ВАЖНО: порядок критичен — `ai_tool_sync(force=True)` очищает таблицу `tool` перед ресканом; job, стартовавший раньше, получит пустой `tools` dict и упадёт с "инструмент не найден".

```
uvicorn startup:
  ai_tool_sync(force=True)         # сначала синхронизируем инструменты
  await planning_worker_recover()  # только потом восстановление

planning_worker_recover():
  _startup_reset()   # running → pending, но только для проектов без flight-ключа:
                     #   job переживает рестарт uvicorn, живую фазу отбирать нельзя
  _recover_pending() # ставим в очередь pending/processing проекты

контейнер worker:
  planning_worker_job_run(project_id)   # один job = вся цепочка одного проекта
    → _job_async(): logging_init, queue_init, поток движка, mysql_pool_close в finally
      → _run_project_chain(project_id)

_run_project_chain(project_id):
  # Выполняет PHASE_GROUPS по волнам:
  Wave 1: analyze
  Wave 2: market
  Wave 3: product
  Wave 4: tech + gtm (параллельно — asyncio.gather)
  Wave 5: financial
  Wave 6: blueprint
  # После blueprint:
  asyncio.gather(
    _run_score(project_id),
    _run_supplements_sequential(project_id),  # market→product→tech→gtm→financial→launch
  )
```

**Параллельность проектов:** каждый проект — отдельный job в очереди, поэтому проекты планируются одновременно ровно настолько, насколько хватает воркеров: одна цепочка занимает один воркер целиком (до 13 часов). Больше параллельных проектов — больше контейнеров `worker_task`.

**Дубликаты:** ключ Redis `planning_worker:flight:<project_id>` берётся при постановке в очередь и снимается в `finally` job'а. Планирование зовут из трёх мест, захвата строки у фазы нет — без ключа один проект спланировался бы дважды.

```
planning_bot (чат) → planning_project_create() → planning_project.status=pending
                                                         ↓
planning_worker_enqueue(project_id) → _run_project_chain()
  → planning_phase_run(agent_name, phase, requires, project_id_filter=project_id)
      → AiFrameworkAgentManager.framework_workflow_run()   # прямой asyncio.Task, без TTL-очереди
           → tool_invoke(planning_project_load) → idea, phases_context
           → llm_to_json / research_loop → phase_result
           → tool_invoke(planning_phase_save / planning_document_save)
      → _phase_mark_complete(project_id, phase)
```

## 4. research_loop sub-workflow (id=28)

Универсальный агентный цикл интернет-поиска. Предназначен для вызова через `workflow_invoke`
из phase-workflow вместо одиночного `llm_to_json` с данными из обучения.

### Контракт входа

| Переменная | Тип | Описание |
|-----------|-----|---------|
| `research_goal` | input | Цель: что ищем и что должно быть в результате |
| `initial_query` | input | Первый поисковый запрос |
| `max_iterations` | workflow (default=8) | Мягкий лимит итераций |
| `search_limit` | workflow (default=7) | Результатов на вызов web_search |

### Результат

`research_loop_{step_id}_result_str` — накопленный текст всех поисковых результатов.

### Шаги (граф)

```
[209] Инициализация ──→ [210] Поиск ──→ [211] Счётчик ──→ [212] Накопить
                          ↑                                       │
                          │                                   [213] Судья
                          │              is_complete=yes/лимит │      │
                          │         ┌────────────────────────── ┘      │
                        [214] Обновить запрос ← (is_complete=no)       │
                                                                   [215] Вернуть
```

### Шаги

| ID | Тип | Назначение |
|----|-----|-----------|
| 209 | variable_conversion | Инициализация: `current_query = initial_query`, `accumulated_data = ""`, `search_iteration = 0`, **`search_region = "wt-wt"`** |
| 210 | tool_invoke(web_search) | Поиск по `current_query`, лимит `search_limit`, **регион `search_region`** |
| 211 | tool_invoke(counter_increment) | `search_iteration + 1` |
| 212 | variable_conversion | Append к `accumulated_data`; обновить `search_iteration` |
| 213 | llm_to_json | Судья: `{is_complete, next_query}`; если yes или лимит → 215 |
| 214 | variable_conversion | `current_query = next_query`; всегда прыгает → 210 |
| 215 | return_response_text | Вернуть `accumulated_data` как результат sub-workflow |

**Регион поиска:** по умолчанию `wt-wt` (весь мир). Вызывающий workflow может переопределить через `inputs_map`.

**Судья (шаг 213):** видит заголовки `=== запрос ===` в accumulated_data и явно инструктирован
не повторять уже выполненные запросы — генерировать новый запрос для неисследованного аспекта.

### Как подключить к phase-workflow

Паттерн с динамической генерацией запроса (используется в market, gtm, financial, supplement):

```
Step A: tool_invoke(planning_project_load)  → idea, phases_context
Step B: llm_to_json → {initial_query, research_goal}  ← домен-специфичные из идеи
Step C: workflow_invoke(research_loop, inputs={research_goal, initial_query})
        → research_loop_{C}_result_str = сырые данные
Step D: llm_to_json(синтез) prompt = "%phases_context%\n\nНайденные данные:\n%research_loop_{C}_result_str%"
        → phase_result
Step E: tool_invoke(planning_phase_save)
```

## 5. Структура workflow-шагов по фазам

### Workflows с internet-поиском (market 20, product 21, tech 22, gtm 23, financial 24)

```
pos 0: tool_invoke(planning_project_load)
pos 1: llm_to_json — генерирует initial_query и research_goal из %project_idea%
pos 2: workflow_invoke(research_loop=28)
pos 3: llm_to_json — синтез из %phases_context% + %research_loop_{pos2_id}_result_str%
pos 4: tool_invoke(planning_phase_save)
```

Шаг на pos 1 — ключевое отличие от старой схемы: вместо статичного `variable_conversion`
со строкой "SaaS market research..." теперь LLM сам формулирует запрос под конкретный домен.

### Workflows без internet-поиска (analyze 19, blueprint 25)

```
pos 0: tool_invoke(planning_project_load)
pos 1: llm_to_json — генерирует phase_result из %idea% + %phases_context%
pos 2: tool_invoke(planning_phase_save / planning_document_save)
```

### Workflows с internet-поиском — product 21, tech 22 (добавлены steps 229-232)

```
pos 0: tool_invoke(planning_project_load)
pos 1: llm_to_json — генерирует initial_query и research_goal из %project_idea% + %phases_context%
pos 2: workflow_invoke(research_loop=28)
pos 3: llm_to_json — синтез из %phases_context% + %research_loop_{pos2_id}_result_str%
pos 4: tool_invoke(planning_phase_save)
```

- product (21): research_loop_230_result_str — ищет боли пользователей, G2/Reddit/ProductHunt отзывы
- tech (22): research_loop_232_result_str — ищет tech stack конкурентов, GitHub open-source аналоги

### Supplement workflow (26)

```
pos 0: tool_invoke(planning_project_load)
pos 1: llm_to_json — генерирует initial_query и research_goal под тип supplement + домен
pos 2: workflow_invoke(research_loop=28)
pos 3: llm_to_json — синтез: %phases_context% + %research_loop_228_result_str% + тип
pos 4: tool_invoke(planning_document_save)
```

Переменная `%planning_supplement_type%` (market/product/tech/gtm/financial/launch) инжектируется
из `extra_variables` при запуске через `phase_supplement.py`.

## 6. Плейбуки (docs/planning/)

Методологические справочники для каждой фазы. **Не встроены в промпты напрямую** —
`research_goal` и `initial_query` генерируются LLM динамически под конкретный продукт.
Плейбуки — эталон для проверки качества и доработки синтез-промптов агентов.

### Автоматизированные фазы

| Файл | Фаза | Ключевые источники |
|------|------|--------------------|
| `planning_research.md` | market | SimilarWeb, G2, Crunchbase, Google Trends |
| `planning_product.md` | product | G2/Capterra отзывы, Reddit, Product Hunt |
| `planning_tech.md` | tech | GitHub, StackOverflow, официальная документация |
| `planning_gtm.md` | gtm | SimilarWeb трафик, Facebook Ads Library, baremetrics |
| `planning_financial.md` | financial | Glassdoor, Baremetrics, Crunchbase, AWS calculator |
| `planning_launch.md` | supplement_launch | Product Hunt топ запуски, useronboard.com |

### Ручные / пост-запуск (не автоматизированы)

| Файл | Назначение |
|------|-----------|
| `planning_experiments.md` | A/B тесты — запускается вручную после появления реальных пользователей |
| `planning_workload.md` | Почасовой список работ — запускается вручную после blueprint |
| `planning_design.md` | Дизайн продукта по реальным примерам — вручную после workload |
| `planning_index.md` | Оглавление плейбуков и общий принцип: искать данные, а не отвечать из знаний |

## 7. Инструменты (src/tool/project/planning/)

| Функция | Назначение |
|---------|-----------|
| `planning_project_load(project_id)` | → `{idea, phases_context, project_title}` — идея + markdown завершённых фаз (`supplement_*` исключены). **Tiered:** последние 2 фазы — полный текст; более ранние усечены до 1500 символов (~60K → ~25K для financial) |
| `planning_phase_save(project_id, phase, result)` | Сохранить результат фазы в `project_planning_phase` |
| `planning_phase_blueprint_load(project_id)` | Blueprint-документ для агента оценки |
| `planning_phase_supplement_context_load(project_id, supplement_type)` | Blueprint + одна релевантная фаза для supplement-агента |
| `planning_phase_design_context_load(project_id)` | Blueprint + product + market для дизайн-агента |
| `planning_phase_document_save(project_id, doc_type, title, content)` | Сохранить Blueprint / Supplement в `project_planning_document` |
| `planning_project_status_get(project_id)` | Статус проекта, фазы и документы |
| `planning_project_score_save(project_id, …)` | Оценки проекта после blueprint |
| `planning_project_list(limit)` | Список проектов чипами с прогрессом |
| `planning_project_bot_action(action, …)` | Диспетчер для planning_bot chat |

## 8. Переменные workflow агентов

Каждый агент-фаза передаёт `planning_phase_name` через `agent.workflow_variable` (JSON):

```json
{"planning_phase_name": "market"}
```

Blueprint-агент дополнительно задаёт `planning_doc_type` и `planning_doc_title`:

```json
{"planning_phase_name": "blueprint", "planning_doc_type": "blueprint", "planning_doc_title": "Blueprint"}
```

Supplement-агент передаёт тип через `extra_variables` в `planning_phase_run()`:

```json
{"planning_supplement_type": "market"}
```

## 9. Таймаут фаз

`planning_phase_run()` вычисляет таймаут динамически по формуле:

```
timeout = avg_ms_per_llm_call × 30 × 1.5 / 1000
clamp([PHASE_TIMEOUT_MIN=900s, PHASE_TIMEOUT_MAX=3600s])
```

- `avg_ms` — средняя задержка LLM из `llm_request` для активной модели ноды
- Множитель 30 — верхняя оценка LLM-вызовов в одной фазе (research_loop + синтез + инструменты)
- Запас 1.5× — буфер для пиков нагрузки
- Фаза никогда не будет ждать меньше **15 минут** и больше **1 часа**

Если модель новая и данных об avg_ms ещё нет — применяется минимальный таймаут 900s.

## 10. Retry

### Полный сброс проекта

`POST /planning/project/{id}/retry` — удаляет ВСЕ фазы и документы, сбрасывает score-колонки, статус → `pending`, ставит проект в очередь runner'а. Используется для запуска с нуля.

### Per-phase retry

`POST /planning/project/{id}/phase/{phase}/retry` — сбрасывает одну фазу:
- Удаляет запись `planning_phase` для указанной фазы
- При `phase=supplement` — удаляет ВСЕ `supplement_*` фазы и документы (одним запросом `LIKE 'supplement_%'`)
- Удаляет `planning_document` для этой фазы
- Очищает score-колонки (только при `phase=score`)
- Сбрасывает `planning_project.status = 'pending'`, ставит в очередь runner'а

Допустимые значения `phase`: `analyze`, `market`, `product`, `tech`, `gtm`, `financial`, `blueprint`, `score`, `supplement`, `design`, `prototype`.

Специальная обработка при сбросе:
- `supplement` — удаляет все `supplement_*` (LIKE-шаблон), не только один тип
- `design` — удаляет фазу и документ с `doc_type = 'design'`
- `score` — дополнительно обнуляет все score-колонки проекта

В UI: кнопка ↻ в строке фазы (кроме статуса `running`).

## 11. Структура router'а (`src/uvicorn/routers/project/`)

Роутер планирования разбит на подфайлы. Каталога `routers/planning/` **нет**: файлы
живут в `routers/project/` с префиксом `project_`, а пути эндпоинтов остались
прежними — `/planning/...`. Соседний `routers/plan/plan.py` к планированию отношения
не имеет: это справочник планов под правом `PLAN_VIEW`.

| Файл | Ручек | Назначение |
|------|-------|-----------|
| `project.py` | 5 | Проекты: список, чтение, создание, правка, удаление (`/project/*`) |
| `project_common.py` | — | Общие константы и утилиты, своих эндпоинтов не имеет |
| `project_planning.py` | 11 | Фазы, запуск и перезапуск, cronicle-расписание (`/planning/project/*`) |
| `project_document.py` | 8 | Документы: разделы фаз, просмотр, скачивание, preview статики |
| `project_prototype.py` | 2 | Прототипы: refine (LLM), patch (прямое сохранение) |
| `project_idea.py` | 2 | Генерация идей (`/planning/ideas/*`) |
| `project_phase_source.py` | 5 | Источники фазы: список, добавление, удаление, чтение документа |

Каждый подфайл регистрируется в `main_uvicorn.py` отдельно — общего агрегатора нет.

> Прежняя редакция описывала каталог `routers/planning/` и шесть файлов `planning_*.py`,
> включая `planning_browser.py`. Ни каталога, ни файлов давно нет: работа с браузером
> уехала в отдельный контейнер (`browser.md`), остальное переименовано при переезде.

## 12. API Endpoints

### Проекты (`project_planning.py`)

| Метод | Путь | Назначение |
|-------|------|-----------|
| `GET`  | `/planning/project/list` | Список всех проектов, сортировка `position ASC, id DESC` |
| `GET`  | `/planning/project/{id}` | Один проект |
| `POST` | `/planning/project` | Создать проект (`{title, idea}`), `position = MAX+1` |
| `PUT`  | `/planning/project/reorder` | Переставить проекты (`{ids: [...]}`), обновляет `position` по индексу |
| `PUT`  | `/planning/project/{id}` | Обновить (`title`, `idea`, `status`) |
| `DELETE` | `/planning/project/{id}` | Удалить проект + все фазы + документы |
| `POST` | `/planning/project/{id}/retry` | Полный сброс (см. §10) |
| `POST` | `/planning/project/{id}/phase/{phase}/retry` | Per-phase reset (см. §10) |
| `GET`  | `/planning/project/{id}/phases` | Список фаз с `cronicle_last_run` |
| `GET`  | `/planning/project/{id}/documents` | Список документов |
| `GET`  | `/planning/cronicle/schedule` | Минуты запуска фаз из файла расписания Cronicle |

### Генерация идей (`project_idea.py`)

| Метод | Путь | Назначение |
|-------|------|-----------|
| `POST` | `/planning/ideas/generate` | Генерирует 7 идей по нише (`{niche}`), агент `planning_idea_generator`, таймаут 90s |
| `POST` | `/planning/ideas/bulk-create` | Создаёт проекты из списка (`{ideas: [{title, idea}]}`), ставит все в очередь |

### Документы (`project_document.py`)

| Метод | Путь | Назначение |
|-------|------|-----------|
| `GET` | `/planning/document/{doc_id}` | Один документ (JSON) |
| `GET` | `/planning/document/{doc_id}/view` | Открыть как HTML-страницу (prototype → redirect на preview) |
| `GET` | `/planning/document/{doc_id}/download` | Скачать `.md` |
| `GET` | `/planning/document/{doc_id}/download/pdf` | Скачать `.pdf` (fpdf2, рендер таблиц и code blocks) |
| `GET` | `/planning/preview/{project_id}/{path}` | Статика прототипа из `/app/data/planning/{id}/`; для `.html` инжектирует `prototype-editor-widget.js` |

### Прототипы (`project_prototype.py`)

| Метод | Путь | Назначение |
|-------|------|-----------|
| `POST` | `/planning/prototype/{id}/refine` | Доработка HTML через LLM (`{page_name, request, reference_url, reference_html, reference_css, target_html}`), агент `planning_prototype_refiner`, таймаут 120s |
| `POST` | `/planning/prototype/{id}/patch` | Прямое сохранение HTML (`{page_name, html}`), без LLM |

Оба endpoint'а удаляют инжектированный `__PROTO_WIDGET__` скрипт из HTML перед записью.

### Браузер — уехал в design

Ручек `/planning/browser/*` больше нет. Тот же браузер референсов живёт под
`/design/browser/*` (`routers/project/design/design_browser.py`) и описан в
`project_design.md`; механика прежняя — один Playwright Chromium на `user_id`, TTL
300 с, скриншоты через CDP `Page.captureScreenshot`.

Не путать с контейнером-браузером (`browser.md`): тот отдельный сервис на своём порту
с пулом сессий, а этот — Chromium внутри uvicorn под один экран сбора референсов.

**История URL** сохраняется при успешном `navigate` через `asyncio.ensure_future(_browser_history_save(...))` — не блокирует ответ. Trim до 15 записей выполняется в той же транзакции.

## 13. Качество промптов: почему структура идёт в prompt_user

### Проблема: LLM игнорирует структуру в var_text

`llm_to_json_variable[0].text` — это описание выходной переменной ("`phase_result` — Markdown с разделами...").
LLM воспринимает это как мягкую рекомендацию и часто генерирует свои разделы вместо заданных.

**Следствие:** секции `## 🔴 Devil's Advocate`, `## Phase Summary`, `## 🔴 Sanity Check` не появлялись
в выводе, даже если были прописаны в var_text.

### Решение: явная структура в prompt_user (шаги 163, 178, 181)

Для фаз с обязательными разделами вся структура выведена **в prompt_user**:

```
=== ИДЕЯ ПРОДУКТА ===
%project_idea%

Создай X. Верни JSON с ключом phase_result содержащим Markdown.

Структура документа (строго соблюдать все разделы):
## Раздел 1
## Раздел 2
...
## 🔴 Критический раздел (ОБЯЗАТЕЛЬНЫЙ раздел)
  - пункт 1
  - пункт 2
## Phase Summary (ОБЯЗАТЕЛЬНЫЙ раздел в конце документа)
  - KEY_INSIGHT: ...
  - MAIN_RISK: ...
...

Отвечай на языке: %user_language%.
```

### Обязательные разделы по фазам

| Фаза | Шаг | Обязательные разделы |
|------|-----|---------------------|
| `analyze` (wf 19, step 163) | llm_to_json | `## 🔴 Devil's Advocate`, `## Phase Summary` |
| `financial` (wf 24, step 178) | llm_to_json | `## 🔴 Sanity Check`, `## Phase Summary` |
| `blueprint` (wf 25, step 181) | llm_to_json | вся компактная структура 1000-1500 слов |

**Blueprint структура** (компактная, 1000-1500 слов): Executive Summary → The Bet → Ключевые решения → Go/No-Go условия → 30-дневный план → Минимальные ресурсы → Red Flags → Verdict.

**Sanity Check** (financial): LTV/CAC > 10 требует ⚠️ WARNING; Year 1 Revenue сравнивается с реальным конкурентом; break-even с учётом рампы.

**Devil's Advocate** (analyze): 3 причины провала + что закрывает потребность бесплатно + 3 условия для успеха.

## 14. Известные ограничения

1. **accumulated_data размер** — 8 итераций × 7 результатов × ~300 символов ≈ 17 КБ.
   При синтезе проверить, укладывается ли в контекст LLM.
2. **Зависимость фаз** — если одна фаза упала (status=failed), все последующие не запустятся.
   Механизм retry реализован (см. §10).
3. **Восстановление после tool_sync** — race condition: если `planning_worker_recover()` ставит
   проекты в очередь до завершения `ai_tool_sync(force=True)`, job получит пустой `tools` dict
   во время очистки таблицы `tool`. В `main_uvicorn.py` восстановление идёт строго после sync.
4. ~~**phases_context растёт с каждой фазой**~~ — **Исправлено** в `planning_project_load`:
   последние 2 фазы передаются полным текстом, остальные усечены до 1500 символов.
   Размер financial-промпта сократился с ~60K до ~25K, blueprint — с ~60K до ~19K.
   Константы: `_PHASES_CONTEXT_RECENT_COUNT = 2`, `_PHASES_CONTEXT_OLDER_MAX_CHARS = 1500`.
