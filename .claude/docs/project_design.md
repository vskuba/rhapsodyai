# Design — дизайн-модуль проекта

> Страница `/admin/design` с четырьмя вкладками: прототип (токены, стейты, чипы),
> UI-компоненты, библиотека блоков/виджетов и карта страниц. Бэкенд разбит на четыре
> роутера в `src/uvicorn/routers/project/design/`, вся фронтенд-логика — в одном
> `design.js`. Часть кнопок ведёт на несуществующие endpoint-ы, см. «Ограничения».

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `src/uvicorn/routers/project/design/design.py` | UI-компоненты, стейты, design tokens, чипы проекта, wireframe-compose, UI-блоки (450 строк) |
| `src/uvicorn/routers/project/design/design_block.py` | Блоки, виджеты, wireframe-страницы, регенерация блоков (450 строк) |
| `src/uvicorn/routers/project/design/design_prototype.py` | Страницы прототипа: список, правка, рендер, авто-расстановка блоков (184 строки) |
| `src/uvicorn/routers/project/design/design_browser.py` | Playwright-браузер для сбора референсов (271 строка) |
| `data/uvicorn/template/admin/project/design.html` | Разметка страницы и вкладок (507 строк) |
| `data/uvicorn/public/js/project/design.js` | Вся логика фронтенда (2466 строк) |
| `data/uvicorn/public/css/design.css` | Стили страницы (~52 KB) |
| `src/uvicorn/routers/dashboard.py` | Роут `/admin/design` (`dashboard.py:209`) |
| `migrations/0001.sql` | Схема — секция дизайна, строки 723-870 |

Все четыре роутера подключены в `main_uvicorn.py` без префикса и с
`include_in_schema=False` — в `/docs` эндпоинтов дизайна нет.

## Вкладки

Порядок в шаблоне (`design.html:50-54`), активна по умолчанию **Блоки/Виджеты**:

| Таб | `data-tab` | Панель | Содержимое |
|-----|-----------|--------|-----------|
| Prototype | `prototype` | `#tab-prototype` | Design Tokens, Стейты, чипы «Функциональность» и «Сущности» |
| Блоки/Виджеты | `blocks-widgets` | `#tab-blocks-widgets` | Библиотека блоков, генерация, превью с токенами |
| Страницы | `pages` | `#tab-pages` | Дерево страниц, wireframe-редактор, расстановка блоков |
| UI-компоненты | `ui-components` | `#tab-ui-components` | CRUD справочника `project_design_ui_component` |

Над табами — шапка с выбором проекта (`#globalProjectSel`) и четырьмя действиями:
«Сгенерировать UI-блоки», «Сгенерировать страницы», «Создать прототип»
и индикатор статуса `#protoProtoStatus`.

Кнопка прототипа подписана в шаблоне и в JS как **«Создать прototип»** —
опечатка со смешанным алфавитом (кириллическое `пр` + латинское `ototip`)
присутствует в самом коде (`design.html:44`, `design.js:1831`, `design.js:2195`),
поэтому здесь приводится дословно.

### Вкладка Prototype

Тулбар — три чипа: набор токенов (`#protoChipTokens`), стейты (`#protoChipStates`)
и вьюпорт (`#protoChipViewport`) с выпадающим списком 1440×900 / 1200×750 / 768×432 / 375×211.

Ниже — таблица `#protoConfigRow` из четырёх ячеек, разделённых перетаскиваемыми
делителями (ширина колонок сохраняется в `localStorage`):

1. **Design Tokens** — список наборов, поле имени, кнопка генерации, палитра-превью;
2. **Стейты** — список `project_state`, выбранные уходят в запуск прототипа;
3. **Функциональность** — чипы `project.cloud_tags`;
4. **Сущности** — чипы `project.entities`.

Чипы редактируются через `_addChip('cloud_tags')` / `_addChip('entities')` и пишутся
`PATCH /design/project/{project_id}/chips`.

## REST API

### `design.py`

| Метод | Путь | Права | Назначение |
|-------|------|-------|-----------|
| GET | `/design/ui-components` | `design:view` | Список UI-компонентов |
| GET | `/design/ui-components/{component_id}` | `design:view` | Один компонент |
| POST | `/design/ui-components` | `design:create` | Создать |
| PUT | `/design/ui-components/{component_id}` | `design:update` | Обновить |
| DELETE | `/design/ui-components/{component_id}` | `design:delete` | Удалить |
| GET | `/design/states` | `design:view` | `project_state`, сортировка по id |
| GET | `/design/tokens` | `design:view` | Наборы токенов, `tokens` распаковывается из JSON |
| POST | `/design/tokens` | `design:create` | Создать набор, вернёт id |
| DELETE | `/design/tokens/{token_id}` | `design:delete` | Удалить набор |
| POST | `/design/tokens/generate` | `design:create` | Запуск агента `design_tokens_manager` |
| GET | `/design/project/{project_id}/chips` | `design:view` | `{cloud_tags, entities}` из таблицы `project` |
| PATCH | `/design/project/{project_id}/chips` | `design:update` | Обновить чипы (только массивы, иначе 422) |
| POST | `/design/wireframe/compose/{project_id}` | `design:create` | Агент `planning_wireframe_composer` на проект или страницу (`page_id` в теле) |
| GET | `/design/ui-block-types` | `design:view` | `project_design_ui_block_type` |
| GET | `/design/ui-blocks` | `design:view` | Блоки + `type_name` через LEFT JOIN |
| GET | `/design/ui-blocks/{block_id}` | `design:view` | Блок с `html`, `css`, `vars` |
| DELETE | `/design/ui-blocks/{block_id}` | `design:delete` | Удалить блок |

### `design_prototype.py`

| Метод | Путь | Права | Назначение |
|-------|------|-------|-----------|
| GET | `/design/prototype/pages/{project_id}` | `design:view` | Страницы проекта, сортировка `state_id, order_index, id` |
| PUT | `/design/prototype/page/{page_id}` | `design:create` | Правка `name`, `description`, `page_type`, `tags`, `roles` (обрезка до 500 символов) |
| GET | `/design/prototype/page/{page_id}/render` | `design:view` | Сборка HTML страницы для iframe |
| POST | `/design/prototype/page/{page_id}/auto-blocks` | `design:create` | Агент `planning_wireframe_composer` расставляет блоки по секциям, таймаут 120 с |

### `design_block.py`

Все эндпоинты этого файла используют **`planning:view` / `planning:update`**, а функции
названы `planning_*` — исторический след того, что блоки жили в модуле планирования.
При изменении прав это надо учитывать.

| Метод | Путь | Права | Назначение |
|-------|------|-------|-----------|
| GET | `/design/{project_id}/blocks` | `planning:view` | Блоки проекта |
| POST | `/design/{project_id}/block` | `planning:update` | Создать блок вручную |
| POST | `/design/{project_id}/block/generate` | `planning:update` | Сгенерировать блок агентом |
| PUT | `/design/block/{block_id}` | `planning:update` | Обновить блок |
| PUT | `/design/block/{block_id}/title` | `planning:update` | Переименовать |
| DELETE | `/design/block/{block_id}` | `planning:update` | Удалить блок |
| POST | `/design/block/{block_id}/regenerate` | `planning:update` | Перегенерировать HTML/CSS |
| GET | `/design/block/{block_id}/widgets` | `planning:view` | Виджеты блока |
| POST | `/design/block/{block_id}/widget` | `planning:update` | Создать виджет |
| PUT | `/design/widget/{widget_id}` | `planning:update` | Обновить виджет |
| DELETE | `/design/widget/{widget_id}` | `planning:update` | Удалить виджет |
| GET | `/design/{project_id}/wireframe-pages` | `planning:view` | Страницы с вайрфреймами |
| PUT | `/design/page/{page_id}/blocks` | `planning:update` | Расстановка блоков по секциям страницы |

### `design_browser.py`

Playwright-сессия на проект: открыть URL, кликать, «пипеткой» забирать фрагмент
разметки как референс. Права у всех — `planning:view`.

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/design/browser/history/{project_id}` | История посещённых URL |
| POST | `/design/browser/navigate` | Перейти по URL, вернуть скриншот (base64) |
| POST | `/design/browser/click` | Клик по координатам, новый скриншот |
| POST | `/design/browser/pick` | Забрать HTML/CSS выбранного элемента |
| POST | `/design/browser/close` | Закрыть сессию браузера |

Приватные хелперы: `_browser_session_get`, `_browser_session_close`,
`_page_screenshot_b64`, `_page_scroll_info`, `_maybe_resize_viewport`,
`_browser_history_save`.

## Схема БД

Полный DDL — `migrations/0001.sql`, строки 723-870.

| Таблица | Назначение |
|---------|-----------|
| `project_state` | Стейты проекта (`name` UNIQUE, `description`) |
| `project_design_token` | Наборы design tokens (`name` UNIQUE, `tokens` JSON) |
| `project_design_ui_component` | Справочник компонентов: варианты, размеры, состояния, `tailwind_example`, `tags` |
| `project_design_ui_block_type` | Типы блоков (`name` UNIQUE, `title`) |
| `project_design_ui_block` | Библиотека блоков: `html`, `css`, `vars`, `slot`/`slots`, `stateless`, `width_min`/`height_min`, `expand_direction` ENUM(`none`,`vertical`,`horizontal`,`both`), `expand_factor_*` |
| `project_design_ui_block_size` | Замеры блока по вьюпортам, `uk_block_viewport(block_id, viewport_width)` |
| `project_design_prototype_page` | Страницы прототипа: `parent_id`, `page_type` (по умолчанию `feature`), `state_id`, `wireframe`, `grid_layout` JSON, `ux_spec` |
| `project_design_prototype_widget` | Виджеты блока: `css`/`html` MEDIUMTEXT, `created_by` (по умолчанию `ai`) |
| `project_design_prototype_page_block` | Связка страница ↔ блок ↔ виджет, `uq_page_block(page_id, block_id, section)` |
| `project_design_prototype_browser_history` | URL референсов, `uq_project_url(project_id, url(512))` |

Каскады: `project_design_ui_block.type_id` → `ON DELETE SET NULL`;
`project_design_ui_block_size.block_id` → `ON DELETE CASCADE`;
`project_design_prototype_page.state_id` → `ON DELETE RESTRICT ON UPDATE CASCADE`
(стейт нельзя удалить, пока на него ссылается страница).

Чипы вкладки Prototype лежат не в дизайн-таблицах, а прямо в `project.cloud_tags`
и `project.entities` (JSON-массивы).

## Агенты и workflow

Дизайн-часть построена на агентах и workflow из модуля планирования
(`project_planning.md`, `workflow.md`). Настройка — `/admin/agent_workflow`.

| Агент | Workflow | Где вызывается |
|-------|----------|---------------|
| `design_tokens_manager` | WF54 `design_tokens_generate` | `POST /design/tokens/generate` |
| `planning_wireframe_composer` | — | `POST /design/wireframe/compose/{project_id}`, `POST /design/prototype/page/{page_id}/auto-blocks` |
| `planning_designer` | WF32 `planning_design` | Конвейер планирования |

Агент резолвится по имени в БД, отсутствие записи — `503`
(`design.py:164-176`: «Агент design_tokens_manager не найден»).
LLM берутся через `ai_llm_node_get(node_id)`, отсутствие — тоже `503`.
Оба «долгих» запуска ждут результата через `asyncio.wait_for`:
токены и wireframe-compose — 180 с (`504` по таймауту), auto-blocks — 120 с.

### WF54 `design_tokens_generate`

| Шаг | Тип | Заголовок |
|-----|-----|-----------|
| 356 | `llm_to_json` | Генерация токенов |
| 357 | `return_response_text` | Вернуть токены |

### WF32 `planning_design` (Дизайн)

| Шаг | Тип | Заголовок |
|-----|-----|-----------|
| 271 | `tool_invoke` | Загрузить контекст |
| 272 | `workflow_invoke` | Исследование UI/UX → WF34 |
| 273 | `workflow_invoke` | Дизайн-система → WF35 |
| 274 | `workflow_invoke` | UX-спецификации → WF36 |
| 275, 276 | `variable_conversion` | |
| 277 | `tool_invoke` | Сохранить дизайн-документ |
| 278 | `variable_conversion` | |
| 279, 290, 291, 292, 293 | `tool_invoke` | Сохранить токены / UI-компоненты / Вайрфреймы / Карту страниц / Спецификации |

### WF33 `planning_prototype` (Прототип)

| Шаг | Тип | Заголовок |
|-----|-----|-----------|
| 242 | `tool_invoke` | Загрузить дизайн (`planning_prototype_context_load`) |
| 243 | `variable_conversion` | Инициализация |
| 250 | `llm_to_image` | Генерация hero image |
| 251 | `tool_invoke` | Сохранить hero image |
| 300 | `tool_invoke` | Инициализация версии прототипа (`planning_prototype_init`) |
| 301 | `workflow_invoke` | Генерация страниц по одной → WF39 |

Шаг 242 отдаёт в переменные `idea`, `design_content`, `project_title`,
`design_tokens`, `sitemap_pages_json`, `design_ui_components`,
`design_wireframes`, `design_sitemap`.
Шаг 300 — `version` → `prototype_version`, `doc_id` → `proto_doc_id`,
`preview_path` → `proto_preview_path`.
Шаг 301 крутит sub-workflow 39 с `repeat.until` = `sitemap_pages_json == "[]"`
и `max_iterations: 25` — то есть по одной странице за итерацию, пока список не опустеет.

### Остальные workflow дизайна

| id | Имя | Заголовок |
|----|-----|-----------|
| 34 | `planning_design_research` | Исследование UI/UX (`llm_to_json` → интернет-поиск → ответ) |
| 35 | `planning_design_system` | Design System Composer (moodboard, судья, токены, 11 шагов) |
| 36 | `planning_ux_spec` | UX Spec Writer (дерево страниц WF42, компоненты, вайрфреймы, судья) |
| 37 | `planning_prototype_refine` | Доработка прототипа |
| 38 | `planning_prototype_sitemap_check` | Проверка карты страниц |
| 40 | `planning_prototype_block_render` | Рендер блока |

## Ограничения

Проверено против кода на 2026-08-10 — три кнопки шапки ведут в никуда:

- **«Создать прототип»** (`createPrototype()`, `design.js:2258`) шлёт
  `POST /planning/project/{pid}/phase/prototype/approve`. Такого роута в проекте нет
  (единственный `approve` — `POST /task/{task_id}/pipeline/approve` в
  `project_task_pipeline.py:82`), поэтому запрос отдаёт 404. Следом
  `_protoPollStatus()` каждые 4 с ищет в `GET /planning/project/{pid}/phases` фазу
  `prototype`, которой `PLANNING_CHAIN` (`src/project/planning/planning_chain.py`)
  не создаёт — фаз всего шесть: `analyze`, `market`, `product`, `tech`, `gtm`,
  `financial`, `blueprint`. Запуск прототипа из UI не работает; WF33 вызывается
  только напрямую.
- **«Сгенерировать UI-блоки»** → `POST /design/project/{pid}/generate-ui-blocks`
  (`design.js:2444`) — роута нет.
- **«Сгенерировать страницы»** → `POST /design/project/{pid}/generate-pages`
  (`design.js:2458`) — роута нет.

Ещё две находки:

- `GET /design/prototype/page/{page_id}/render` выбирает `p.state`
  (`design_prototype.py:73`), а в `project_design_prototype_page` колонка называется
  `state_id` — на непустой странице запрос падает с `Unknown column 'p.state'`.
  Пустая страница отвечает заглушкой «Страница пуста» и ошибку не показывает.
- `data/uvicorn/public/js/project/prototype-editor-widget.js` (94 KB) не подключён
  ни в одном шаблоне — мёртвый файл.

Прочее:

- Рендер страницы тянет Tailwind 2 с `cdn.jsdelivr.net` — без интернета превью
  соберётся без стилей.
- Playwright-браузер держит сессию в памяти процесса uvicorn: рестарт контейнера
  её теряет, история URL при этом остаётся в БД.
