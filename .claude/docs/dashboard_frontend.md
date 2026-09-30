# Dashboard Frontend — админка, шаблоны, скрипты

> Server-side rendering на Jinja2 из FastAPI, без сборки и без фреймворка. Страницы —
> `/admin/*`, разметка + стили + скрипты чаще всего лежат в одном `.html`.

**Правка `.html` не требует рестарта uvicorn** — шаблоны читаются с диска на каждый
запрос. Рестарт нужен только после `.py`.

## Страницы и роуты

HTML-роуты — `src/uvicorn/routers/dashboard.py` (не `html.py`), по одному короткому
хендлеру на страницу. API-роутеры лежат отдельно, в `src/uvicorn/routers/<entity>/`.

| Роут | Шаблон | Что это |
|------|--------|---------|
| `/` | `admin/chat.html` | Чат с агентом |
| `/login` | `login.html` | Логин; **не** наследует `base.html` |
| `/admin/agent` | `admin/agent.html` | Агенты |
| `/admin/workflow` | `admin/agent_workflow.html` | Редактор workflow и шагов |
| `/admin/workflow_trace` | `admin/workflow_trace.html` | Трейсы прогонов, токены |
| `/admin/variable` | `admin/node_variable.html` | Переменные ноды (роль-зависимый шаблон) |
| `/admin/llm` | `admin/llm.html` | LLM и статистика запросов |
| `/admin/node` | `admin/node.html` | Ноды |
| `/admin/tool` | `admin/tool.html` | Инструменты + тест-раннер |
| `/admin/fact`, `/admin/fact_collection` | `admin/fact*.html` | Факты и коллекции |
| `/admin/session` | `admin/session.html` | Просмотр сессий |
| `/admin/user`, `/admin/role` | `admin/user.html`, `admin/role.html` | Пользователи и роли |
| `/admin/cabinet` | `admin/cabinet.html` | Личный кабинет, access-токены |
| `/admin/miniapp` | `admin/miniapp.html` | Mini App в рамке телефона (iframe на `/telegram-app`) |
| `/admin/setting` | `admin/setting.html` | Настройки |
| `/admin/seed`, `/admin/backup` | `admin/seed.html`, `admin/backup.html` | Seed SQL и бэкапы |
| `/admin/queue` | `admin/queue.html` | Мониторинг очередей |
| `/admin/plan` | `admin/plan.html` | Планы |
| `/admin/task` | `admin/project/task.html` | Задачи + конвейер агентов |
| `/admin/task/diff` | `admin/project/task_diff.html` | Разница главной ветки и веток задачи или подзадачи (`?task=<id>`) + кнопка «Merge» с проверкой конфликтов |
| `/admin/planning` | `admin/project/planning.html` | Планирование проектов |
| `/admin/planning-phase-source` | `admin/project/planning_phase_source.html` | Источники для фаз |
| `/admin/design` | `admin/project/design.html` | Дизайн-модуль, прототип |
| `/admin/developing` | `admin/project/developing.html` | Разработка |

Вне админки: `telegram_app.html` (Mini App, см. `telegram_mini_app.md`) и
`custom/dating/node_variable.html` — кастомный шаблон под роль,
подменяется через `template_role_mapping` в `dashboard.py:16`.

## `base.html`

Блоки: `{% block title %}`, `{% block head %}` (стили страницы), `{% block content %}`,
`{% block scripts %}` (модульные скрипты страницы). Все админ-шаблоны — `{% extends "base.html" %}`.

Подключает глобально: `common.css`, `menu_top.css`, `notification.css` и `tz.js`.

**Меню двухуровневое.** Верхний ряд — `.tabnav-group` (Чат, LLM, Проекты, Логи, Ноды,
MiniApp, Настройки, Инструменты), под ним — `.tabnav-panel` со ссылками своей
группы. Активная группа вычисляется инлайн-скриптом внизу `base.html` по карте
`groupMap` (URL → группа): **добавил страницу — допиши её в `groupMap`**, иначе меню не
подсветится. Пользователи и роли — подпункты «Настроек»: отдельной вкладки под них нет. Часть пунктов ведёт наружу (Phpmyadmin, Qdrant, Cronicle, Redis, Grafana,
Gatus, OpenSearch) — это `localhost:PORT`, работающие при поднятом ssh-туннеле
`rhapsody-prod`.

Там же модульный скрипт: logout. Access-токен для Mini App берёт сама страница
`/admin/miniapp` — в шапке этой логики больше нет.

## Общие скрипты (`data/uvicorn/public/js/`)

| Модуль | Экспорт | Назначение |
|--------|---------|-----------|
| `api.js` | `getData`, `postData`, `putData`, `deleteData` | fetch-обёртки, `credentials: 'include'`, `FormData` определяется автоматически |
| `notification.js` | `showNotification(msg, type)` | Тосты `success`/`error`/`warning`/`info` |
| `setting.js` | `SettingGet(key, userId)`, `SettingSet(key, value, userId)` | Пользовательские настройки в БД |
| `agent_group_tree.js` | `buildGroupTree`, `renderGroupTree` | Дерево групп с раскрытием в localStorage |
| `lang_switcher.js` | `i18nTextResolve`, `userLanguageGet`, `nodeLanguagesGet`, `langSwitcherCreate` | Мультиязычные поля |
| `user_access_token.js` | `loadUserTokens`, `deleteToken`, `initTokenGeneration` | Access-токены (кабинет, пользователи) |
| `tz.js` | `window.loadTz()`, `window.fmtTz(value, withSeconds)` | Не модуль, а глобали; подключён в `base.html` |
| `sidebar_resizer.js` | `initSidebarResizer(...)` (глобальная) | Тянущаяся ширина сайдбара, ширина в localStorage |

`api.js` вытягивает текст ошибки из тела ответа (`detail`, затем `message`), а при
не-JSON теле оставляет HTTP-статус — поэтому `err.message` в `catch` уже пригоден для
`showNotification`.

**`tz.js` — частая ловушка.** Скрипт подключён везде, но `fmtTz` отдаёт UTC, пока не
вызван `loadTz()`. Его зовут `backup.html`, `seed.html`, `session.html`; страницы, где
времена выглядят «сдвинутыми», просто забыли этот вызов при инициализации.

Многостраничные модули:

- `js/workflow/` — редактор `/admin/workflow`: `main.js` (вход), `state.js` (общий стейт,
  поля не переприсваивать), `steps.js` (шаги, переходы, DnD), `step-widgets.js`
  (динамические поля по типу шага), `variables.js` (панель переменных), `graph.js`
  (mermaid), `utils.js`, `variable-group.js`, `undefined-index.js`.
  ⚠⚠ `variable-group.js` — **чистый** модуль: что за переменные живут в шагах, к
  какой группе относится имя и что считать неопределённой переменной (`undefinedVariables`,
  группа `VAR_GROUP_UNKNOWN`, секция `undefined` у `groupWorkflowVariables`) — **там и
  только там**; панель редактора, список workflow и страница трассы импортируют правило,
  а не пересчитывают своим разбором. Ни DOM, ни сети, ни стейта страницы: всё нужное
  приходит аргументами — реестр, шаги,
  справочники workflow и инструментов; **умолчаний из стейта там нет намеренно**,
  умолчание и есть скрытая привязка к редактору. Привязку к стейту страницы держит
  редактор, и в одном месте — адаптеры `editorVariableGroups` /
  `editorVariableGroupIndex` в `variables.js`.
  ⚠ `undefined-index.js` — сеть и кэш, правила в нём нет: один GET
  `/workflow_variable/undefined_index` на страницу с сырьём `{steps, registryNames,
  hiddenNames}` на workflow; для открытого редактором workflow сырьё берётся из стейта
  страницы, пакет мог быть скачан до правки шага. Proxy-переменные нод и
  `agent_variable` в правило приходят как `hiddenNames`: наружу не показываются и не
  помечаются.
- `js/project/` — страница планирования: `main.js`, `projects.js`, `panel.js`,
  `actions.js`, `ideas.js`, `compare.js`, `markdown.js`, `cronicle.js`, `design.js`,
  `prototype-editor-widget.js`, `utils.js`
- `js/telegram_app/` — Mini App, см. `telegram_mini_app.md`
- `js/vendor/mermaid.min.js`, `js/chart.umd.min.js` — вендорные, локально, без CDN

## CSS

| Файл | Область |
|------|---------|
| `common.css` (79 строк) | Только `body`, `.page-content`, `.main-wrapper`, `.sidebar`, `.sidebar-label` и базовый вид `input/select/textarea/button` |
| `menu_top.css` | Верхнее меню: `.topbar`, `.nav-shell`, `.tabnav-group`, `.tabnav-panel`, `.topbar-user*` |
| `notification.css` | Тосты |
| `design.css` (2386 строк) | Дизайн-модуль; подключает только `project/design.html` |
| `telegram_app.css`, `user_access_token.css`, `code_mirror_*.css` | По названию |

**Общей библиотеки классов нет.** `.editor-container`, `.agents-sidebar`, `.form-control`,
`.btn-save` и прочее описано инлайном в `{% block head %}` каждой страницы, которая их
использует. Меняя такой класс, чините одну страницу, а не все — и наоборот, общий вид
надо повторять руками.

## Два макета

### Master-Detail (старый)

`agent.html`, `agent_workflow.html`, `node.html`, `tool.html`, `user.html`, `role.html`,
`plan.html`, `fact_collection.html`, `workflow_trace.html`, `project/planning.html`,
`node_variable.html`, `queue.html`.

```html
<div class="editor-container">
  <div class="agents-sidebar">
    <div class="sidebar-header"><button class="btn-create">+ Создать</button></div>
    <div class="agent-list" id="entityList">
      <div class="group-header">НОДА</div>
      <div class="agent-item active">Название</div>
    </div>
  </div>
  <div class="editor-section">
    <form id="entityForm">
      <input type="hidden" id="entityId">
      <div class="form-layout-grid">   <!-- настройки | промпты | переменные -->
        <div class="form-grid"><div class="form-group">
          <label>Поле</label><input class="form-control">
        </div></div>
      </div>
      <div class="editor-footer">
        <button class="btn-save">Сохранить</button><button class="btn-delete">Удалить</button>
      </div>
    </form>
  </div>
</div>
```

Скелет скрипта: `initManager()` тянет сущности и справочники через `Promise.all` →
`renderList()` группирует по `node_id` и сортирует по `position` → `selectForEdit(id, el)`
заполняет форму → `saveConfig()` выбирает PUT или POST по скрытому `id` →
`deleteEntity()`. Вызовы вешаются внизу скрипта без `DOMContentLoaded`: `type="module"`
и так откладывается до разбора DOM.

### Собственный макет (новые страницы)

`project/task.html` (`.task-page`), `project/design.html` (`.design-layout`),
`project/developing.html` (`.dev-layout`), `seed.html` (`.seed-layout`),
`backup.html` (`.backup-layout`), `llm.html` (`.llm-layout` + `.page-tabs`),
`setting.html` (`.setting-layout`).

Здесь нет сайдбара со списком и формы справа: это таблицы, деревья и раскрывающиеся
строки-редакторы. Копировать master-detail в новую страницу такого рода не надо — он
описан выше как то, что уже есть, а не как обязательный образец.

## Контракты API

Уживаются два поколения, и это видно прямо в ответах:

- **Старое** — `{"result": ...}` для списка и для одной сущности; при явном исходе
  добавляется `{"status": "success" | "error", "message": "..."}`.
  Так отвечают `/agent/*`, `/workflow/*`, `/node/*`, `/tool/*`, `/llm/*`, `/user/*`,
  `/fact/*`, `/project/*`
- **Новое** — ключ по имени сущности: `{"tasks": [...]}`, `{"task": {...}}`,
  `{"revisions": [...], "total": n}`. Так отвечают `project_task*`, дизайн-роутеры
- **Ошибки** — всегда `{"detail": "текст"}` (`HTTPException`), `api.js` его и показывает

Отдельные формы, которые легко забыть:

- `/workflow/{id}/steps` → `{"result": [{id, type_id, title, position, metadata, icon}]}` —
  колонка называется `title`, не `name`
- `/workflow/{id}/steps/reorder` — `PUT` с `{positions: [{id, position}]}`
- `/workflow/{id}/variables` → `{"result": [{id, name, default}]}`
- `/workflow_variable/undefined_index` → `{"result": {"workflows": {id: {steps,
  registryNames, hiddenNames}}}}` — **сырьё**, а не вычисленный ответ: «Undefined
  переменные» вычисляет клиент (`undefinedVariables` из `variable-group.js`); право
  `WORKFLOW_VARIABLE_VIEW`, ответ — все workflow разом одним GET

## Грабли

1. **`groupMap` в `base.html`** — новая страница без записи там останется без подсветки меню
2. **`loadTz()`** — без вызова все времена на странице показываются в UTC
3. **Jinja2 против JS-шаблонов** — `{{ }}` в JS экранировать как `{{ '{{' }}` либо выносить
   скрипт в `.js`
4. **`workflow_variable` и `agent_variable`** — перед отправкой всегда `JSON.stringify()`.
   На `/admin/agent` это два независимых блока в одной колонке; строки собираются
   по контейнеру (`variablesCollect(containerId)`), а не по классу `.variable-row`
   на всей странице — иначе переменные агента и workflow слились бы в один словарь
5. **`metadata` шагов** — приходит строкой с сырыми переводами строк; парсить через
   `parseMetadata()` с фолбэком на экранирование `\n`
6. **Редкие глифы** — символы без покрытия шрифтом рендерятся случайной буквой (наступали
   на `⑂`); нестандартным иконкам нужен `line-height: 1`, иначе чип выше соседей
7. **`FormData`** — `postData` сам не ставит `Content-Type`, если передан `FormData`
   (голосовые в Mini App)

## Новая страница: чек-лист

1. Шаблон `data/uvicorn/template/admin/<entity>.html`, `{% extends "base.html" %}`
2. HTML-роут в `src/uvicorn/routers/dashboard.py`
3. API-роутер `src/uvicorn/routers/<entity>/<entity>.py`, зарегистрировать в `main_uvicorn.py`
4. Ссылка в меню `base.html` **и** запись в `groupMap`
5. Права — `AuthPermission` + роль (`auth.md`)
6. Стили — инлайном в `{% block head %}`; общего файла для них нет

Статика раздаётся так:
```python
app.mount("/static", StaticFiles(directory="data/uvicorn/public"), name="static")
```
