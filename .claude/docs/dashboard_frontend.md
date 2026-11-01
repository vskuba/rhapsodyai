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
| `/admin/session` | `admin/session.html` | Сессии: вкладки «Агенты» и «Чат», разметка вкладок — `{% include %}` из `admin/session/` |
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
| `tz.js` | `window.loadTz()`, `window.fmtTz(value, withSeconds)` | ⚠ Файл живёт в каркасе (`dashboard/js/`), а не здесь; не модуль, а глобали. `base.html` подключает его всем страницам, общие шаблоны каркаса — ещё и себе сами |
| `sidebar_resizer.js` | `initSidebarResizer`, `initSidebarResizerRight`, `initRowResizer` (глобальные) | ⚠ Файл живёт в каркасе (`dashboard/js/`), а не здесь. Тянущийся размер панели, позиция в localStorage, двойной клик — сброс |

`api.js` вытягивает текст ошибки из тела ответа (`detail`, затем `message`), а при
не-JSON теле оставляет HTTP-статус — поэтому `err.message` в `catch` уже пригоден для
`showNotification`.

**`tz.js` — частая ловушка, и ловушек две.**

Первая: скрипт подключён везде, но `fmtTz` отдаёт UTC, пока не вызван `loadTz()`. Его
зовут `backup.html`, `seed.html`, `session.html`; страницы, где времена выглядят
«сдвинутыми», просто забыли этот вызов при инициализации.

⚠⚠ Вторая больнее и стоила сломанной страницы у соседа. Файл лежит **в каркасе**
(`dashboard/js/tz.js`), а подключал его раньше только `base.html` **этого** проекта —
то есть общий код каркаса молча рассчитывал на глобаль, которой у соседней панели
нет. У DatingAi страница «Тесты → E2E» из-за этого не работала вовсе:
`ReferenceError: loadTz is not defined`, вёрстка при этом рисовалась, и обе колонки
навсегда оставались в «Загрузка…» — ни отказа, ни записи в журнале.

Отсюда правило: **общий шаблон каркаса, который зовёт `loadTz`/`fmtTz`, подключает
`tz.js` сам**, строкой перед своим модулем, и на `base.html` проекта не надеется.
Двойное подключение безвредно — скрипт идемпотентен.

Многостраничные модули:

- `js/workflow/` — редактор `/admin/workflow`: `main.js` (вход), `state.js` (общий стейт,
  поля не переприсваивать), `steps.js` (шаги, переходы, DnD), `step-widgets.js`
  (динамические поля по типу шага), `variables.js` (панель переменных), `graph.js`
  (mermaid), `utils.js`, `variable-group.js`, `variable-undefined.js`.
  ⚠⚠ `variable-group.js` — **чистый** модуль: что за переменные живут в шагах, к
  какой группе относится имя и что считать неопределённой переменной (`undefinedVariables`,
  секция `undefined` у `groupWorkflowVariables`) — **там и только там**; панель
  редактора, список workflow и страница трассы импортируют правило,
  а не пересчитывают своим разбором. Ни DOM, ни сети, ни стейта страницы: всё нужное
  приходит аргументами — реестр, шаги,
  справочники workflow и инструментов; **умолчаний из стейта там нет намеренно**,
  умолчание и есть скрытая привязка к редактору. Привязку к стейту страницы держит
  редактор, и в одном месте — адаптеры `editorVariableGroups` /
  `editorVariableGroupIndex` в `variables.js`.
  ⚠ `variable-undefined.js` — сеть и кэш, правила в нём нет: один GET
  `/workflow_variable/undefined_index` на страницу с сырьём `{steps, registryNames,
  hiddenNames}` на workflow; для открытого редактором workflow сырьё берётся из стейта
  страницы, пакет мог быть скачан до правки шага.

  ⚠ «Какой workflow открыт в редакторе» спрашивают у `editorWorkflowId()` из
  `utils.js` — там же, где остальные вопросы к DOM страницы. В модуле кэша его
  нет намеренно: вопрос не про индекс, и задают его те, кто про индекс не знает.

  ⚠⚠ **`hiddenNames` — четыре источника, и три из них про запускающего.** Реестр
  отвечает только за заведённое руками; значение приходит ещё с трёх сторон, и ни
  одной из них в реестре нет. Пока источники не были собраны, правило звало дырками
  40 живых имён из 74 по установке.

  | источник | пример | где лежит |
  |---|---|---|
  | `agent_variable` агента | `girl_name` | карточка агента |
  | `proxy`-переменные ноды | `girl_title` | `node_variable`, тип `proxy` |
  | словарь запускающего | `task_id`, `subtask_branch` | `variables_start` последних прогонов |
  | входящие подпрогона | `w_project_id` | `inputs_map` родительского `workflow_invoke` |

  Все четыре наружу не показываются и значком не помечаются.

  ⚠ Ещё две поправки живут в самом правиле, а не в `hiddenNames`: шаг с
  **непрозрачным инструментом** (`toolOutputIsOpaque`: объявлен `{"type": "dict"}`,
  а ключи движок раскладывает по ответу) снимает подозрение со всего
  `{tool}_{шаг}_result_*`, и **однобуквенное имя** не считается переменной —
  `%Y%m%d%H%M%S` это формат даты, а не три метки.

  ⚠⚠ Словарь запускающего виден правилу только после **первого прогона** workflow:
  `task_id` и соседей кладёт питон (`src/project/task/task_agent_*.py`), и в базе
  их нет больше нигде. Workflow, который ни разу не бегал и не объявил входящих,
  получит значки на рабочих именах — лечится прогоном или строкой `input` в реестре.
- `js/session/` — страница `/admin/session`: `main.js` (переключение вкладок и
  ленивый завод каждой), `agent.js` (вкладка «Агенты», `agent_session`),
  `chat.js` (вкладка «Чат», `companion_session`), `util.js` (экранирование,
  заполнение `select`, память отборов — `localStorage` одной дверью на всю
  страницу, включая выбранную подвкладку). ⚠ Вкладки не делят ни поля, ни отборы, ни ленту —
  поэтому не делят и модуль; разметка вкладок тоже разведена по шаблонам
  (`admin/session/agent.html`, `admin/session/chat.html`), а стили лежат одним
  файлом `css/session.css`, потому что их делят три шаблона. Устройство —
  `.claude/docs/session.md`
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
| `session.css` | Страница `/admin/session`; вынесена из шаблона, потому что её делят три шаблона (оболочка и две панели вкладок) |
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
  `WORKFLOW_VARIABLE_VIEW`, ответ — все workflow разом одним GET.
  ⚠⚠ Ручка в `workflow_variable.py` — **тонкая**, как `workflow_export.py` рядом:
  сбор живёт в `src/ai/ai_workflow_undefined.py` (`ai_workflow_undefined_index`),
  там и правят. Роутер знает про HTTP и право, и больше ни про что.
  ⚠ Ключи словаря старта считает база (`JSON_KEYS`), а не питон: `variables_start`
  хранит и промпты прогона, и по сети он ехать не должен. Отбор последних
  прогонов (`AI_WORKFLOW_UNDEFINED_RUNS_LIMIT`) идёт по id, тяжёлая колонка
  читается только у отобранных строк

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
8. **⚠⚠⚠ Виджет шага правит чужую переменную — только через очередь**
   (`variableValueStage`, `workflow/variables.js`). Скрытые строки, на которых
   держится сохранение переменных, есть **только у входящих**:
   `renderInputVariables` наполняет контейнер фильтром `type === 'input'`.
   Для переменной рода `workflow` строки нет, и `syncHiddenRow` уходит ни с чем —
   молча, как и положено функции, которой нечего обновлять.

   Выглядит это хуже, чем «не сохранилось»: форма показывает новое значение
   (список состояния правится), кнопка отвечает «Изменения успешно сохранены»,
   а база остаётся прежней. Расходится только после перезагрузки страницы.
   Поймано на проде 01.11.2026 — доля жребия `dice_img_attach` в `dating_talk`
   менялась с 5 на 15 и возвращалась к 5.

   Очередь уносит `saveStagedVariableValues(workflowId)` по кнопке «Сохранить
   workflow», запросом `PUT /workflow/{id}/variable/{varId}`. Сторожит
   `tests/test_workflow_dice_spec_var.py::TestTheQueueReachesTheBase`.

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
