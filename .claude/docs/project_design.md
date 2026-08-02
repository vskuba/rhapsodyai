# Project Design Module

Страница `/admin/design` — визуальный редактор дизайна проекта. Состоит из 4 вкладок.

## Вкладки

| data-tab | Название | Назначение |
|---|---|---|
| `blocks-widgets` | Блоки/Виджеты | Редактор HTML/CSS виджетов и блоков (default active) |
| `pages` | Страницы | Wireframe-builder: сборка страниц из блоков |
| `ui-components` | UI-компоненты | Библиотека переиспользуемых компонентов |
| `prototype` | Прототип | Конфигуратор генерации прототипа |

---

## Вкладка Prototype (Конфигуратор)

Пользователь выбирает конфигурацию, которая уходит в workflow генерации прототипа. Конфигурация расширяется со временем.

### Текущие части конфигурации

**Design Tokens** — набор токенов (цвета, шрифт, border-radius). Выбирается из списка слева.
- Генерируются через AI-агент `design_tokens_manager` → workflow `design_tokens_generate` (id=54)
- Превью: цветовые чипы + кнопки/карточка/статусы на реальных цветах токена
- Шрифт подгружается динамически из Google Fonts

**Стейты** — из таблицы `project_state`. Чекбоксы, по умолчанию все включены.

### Тулбар Prototype
```
[Токены: <name>]  [Стейты: anon, auth]  [● Processing / ● Done / ● Error]  [Создать прototип]
```

### Кнопка "Создать прototип"
Активируется когда: выбран проект И выбран набор токенов.

Поведение:
1. POST `/planning/project/{pid}/phase/prototype/approve` с `{token_id, state_ids: [...]}`
2. Остаётся на странице Design (без редиректа)
3. Поллинг GET `/planning/project/{pid}/phases` каждые 4 сек → ищет фазу `phase === 'prototype'`
4. Статусы: `pending/running` → `● Processing` (пульсирует), `complete` → `● Done`, `error` → `● Error: <msg>`

---

## Вкладка Блоки/Виджеты

Двухпанельный редактор: левая колонка — список блоков проекта, правая — виджеты внутри блока.

Каждый блок содержит набор виджетов. Виджет = HTML + CSS.

### Ключевые функции
- `loadBlocksWidgets()` — загрузка блоков/виджетов выбранного проекта
- `generateBwBlock()` — AI-генерация блока из описания
- `regenBwBlock(blockId)` — регенерация блока
- `saveBwCss(widgetId)` / `saveBwHtml(widgetId)` — сохранение виджета
- `bwToggleApprove(blockId)` — одобрение блока (нужно перед созданием прototипа)

---

## Вкладка Страницы (Wireframe Builder)

Сборка страниц из одобренных блоков. Отображается как iframe-превью.

- `loadPagesTab()` — загрузка дерева страниц
- `saveWireframe()` — сохранение layout
- `GET /design/prototype/page/{page_id}/render` — собирает HTML страницы из блоков/виджетов для iframe

---

## Вкладка UI-компоненты

Библиотека компонентов без привязки к проекту (кнопки, формы, карточки и т.д.).

CRUD: список → выбор → редактирование полей (name, description, variants, sizes, states, tailwind_example, tags).

---

## API Endpoints

### Design States
| Method | Path | Auth |
|---|---|---|
| GET | `/design/states` | `DESIGN_VIEW` |

### Design Tokens
| Method | Path | Auth | Описание |
|---|---|---|---|
| GET | `/design/tokens` | `DESIGN_VIEW` | Список наборов токенов |
| POST | `/design/tokens` | `DESIGN_CREATE` | Создать набор вручную |
| DELETE | `/design/tokens/{id}` | `DESIGN_DELETE` | Удалить набор |
| POST | `/design/tokens/generate` | `DESIGN_CREATE` | AI-генерация через workflow |

### Prototype
| Method | Path | Auth | Описание |
|---|---|---|---|
| GET | `/design/prototype/pages/{project_id}` | `DESIGN_VIEW` | Страницы прototипа |
| GET | `/design/prototype/page/{page_id}/render` | `DESIGN_VIEW` | Рендер страницы в HTML |

### UI Components
| Method | Path | Auth |
|---|---|---|
| GET | `/design/ui-components` | `DESIGN_VIEW` |
| GET | `/design/ui-components/{id}` | `DESIGN_VIEW` |
| POST | `/design/ui-components` | `DESIGN_CREATE` |
| PUT | `/design/ui-components/{id}` | `DESIGN_UPDATE` |
| DELETE | `/design/ui-components/{id}` | `DESIGN_DELETE` |

---

## Таблицы БД

| Таблица | Назначение |
|---|---|
| `project_design_token` | Наборы design tokens (id, name, title, description, tokens JSON) |
| `project_state` | Стейты пользователя (id, name, description) — например anon/auth |
| `project_design_prototype_block` | Блоки прototипа проекта |
| `project_design_prototype_page` | Страницы прototипа |
| `project_design_prototype_page_block` | Связь страница↔блок↔виджет |
| `project_design_prototype_widget` | Виджеты (HTML + CSS) |
| `project_design_ui_component` | Библиотека UI-компонентов |

---

## AI-генерация токенов

**Агент:** `design_tokens_manager` (id=97), node_id=6  
**Workflow:** `design_tokens_generate` (id=54)

Шаги:
1. **Шаг 356** — тип `llm_to_json` → генерирует `design_tokens_json` по описанию проекта
2. **Шаг 357** — тип `return_response_text` → возвращает JSON токенов

Промпт подбирает цвета из тематики проекта (не синий по умолчанию), вариативный `borderRadius`, шрифт.

Структура токенов (flat формат, генерируется LLM):
```json
{
  "colors": { "primary": "#16A34A", "secondary": "#...", ... },
  "typography": { "fontFamily": "Nunito", "fontSize": "16px" },
  "borderRadius": "12px"
}
```

Также поддерживается nested формат: `{"primary": {"value": "#hex", "description": "..."}}`

---

## Старые planning-workflow дизайна (wf 32, 33 — выведены из planning-фаз)

Ранее дизайн был фазой в planning-цепочке. Сейчас заменён на отдельный модуль `/admin/design`.

**Design workflow (32)** — цепочка sub-workflows:
- **WF 34** (Research) — исследование рынка, moodboard
- **WF 35** (Design System):
  - Step 258: дизайн-система → `design_system_content` + `design_tokens_json`
  - Step 261: судья дизайн-системы
- **WF 36** (UX Spec):
  - Step 265: UX Spec Writer → `ux_spec_content` (токены, UI-компоненты, карта страниц, вайрфреймы)
  - Step 268: UX Judge (вайрфреймы ≥4 блока на стр., ≥6 страниц)

**Prototype workflow (33)** — мультистраничный HTML-прototип:
- Step 242: `planning_prototype_context_load` → `design_tokens`, `design_ui_components`, `design_wireframes`, `design_sitemap`
- Step 244: генерация index.html → `html_content` + `html_pages_json`
- Step 247: Proto Judge (≥7/10)
- Step 249: `planning_prototype_save` → `data/planning/{id}/design/v{N}/`
- Steps 288-289: генерация и сохранение недостающих страниц

Файлы прototипа: `data/planning/{project_id}/design/v{N}/*.html`

---

## Файлы

| Файл | Назначение |
|---|---|
| `src/uvicorn/routers/design/design.py` | Все API эндпоинты |
| `data/uvicorn/template/admin/design.html` | Вся фронтенд-логика (3100+ строк) |
