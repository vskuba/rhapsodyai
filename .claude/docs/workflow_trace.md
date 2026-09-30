# Workflow Trace — журнал выполнения workflow

> Полная наблюдаемость запусков workflow: по каждому шагу — вход, выход, длительность,
> токены, модель, ошибки, переходы. По запуску целиком — маршрут с деревом sub-workflow.
> Страница — `/admin/workflow_trace`.

⚠ Соседняя страница под тем же пунктом меню «Логи» — **«Журнал»** (`/admin/journal`):
всё, что происходило на установке **вне** движка workflow. Её первая подвкладка, «Ошибки»,
собирает падения роутеров, воркеров, кронджобов и бота. Своя таблица, свой обработчик,
своя документация — `.claude/docs/journal.md`. Здесь про неё не пишут ничего, кроме
этой строки: предметы разные.

## Ключевые файлы

| Файл | Роль |
|------|------|
| `src/ai/ai_workflow_trace.py` | Модуль записи: `ai_workflow_trace_run_start/finish`, `ai_workflow_trace_step`, `ai_workflow_trace_runs_stale_close` |
| `src/ai/framework/agent/ai_framework_manager.py` | Вызывает трейс-функции из `_framework_workflow_run` и `_workflow_steps_run` |
| `src/uvicorn/routers/workflow/workflow_trace.py` | REST API: list, detail, replay, stop, delete |
| `data/uvicorn/template/admin/workflow_trace.html` | Страница `/admin/workflow_trace` |
| `src/auth/auth_permission.py` | `WORKFLOW_TRACE_VIEW/DELETE/REPLAY/STOP` |
| `migrations/20260101000000_initial_schema.sql` | DDL: `agent_workflow_trace`, `agent_workflow_trace_step` |

## Схема данных

### `agent_workflow_trace` — один запуск workflow
```
id, run_uuid (CHAR36 UNIQUE)
parent_run_id INT NULL FK→self   -- sub-workflow ссылается на родителя (CASCADE DELETE)
parent_step_id INT NULL          -- id шага workflow_invoke, породившего дочерний запуск
depth INT DEFAULT 0              -- 0 = верхний уровень
workflow_id INT NULL FK          -- ON DELETE SET NULL
agent_id, user_id INT NULL
session_uuid, request_uuid CHAR(36)
prompt_user LONGTEXT
variables_start LONGTEXT         -- полный JSON-снапшот переменных на старте
result LONGTEXT NULL
status ENUM('running','success','error','stopped')
error LONGTEXT NULL
started_at DATETIME(3), finished_at DATETIME(3) NULL
duration_ms INT NULL

subtask_id INT GENERATED VIRTUAL  -- номер подзадачи из variables_start
task_id    INT GENERATED VIRTUAL  -- номер задачи; у подзадачи здесь номер родителя
```

Индексы: `run_uuid` (unique), `(workflow_id, started_at)`, `session_uuid`, `parent_run_id`,
`(status, id)`, `(depth, status, id)`, `(finished_at)`, `(subtask_id, task_id)`.

### ⚠ Номер задачи — колонка, а не поиск по тексту

`subtask_id` и `task_id` **вычисляются** из `variables_start` при вставке
(`migrations/20260929123812`), писать в них не надо и нельзя. Завелись они потому, что
конвейер искал свои прогоны подстрокой (`variables_start LIKE '%"subtask_id": "5219"%'`)
и разбором JSON на лету — а это `type: ALL` по таблице в 174 МБ: **639 мс** на проде,
чаще всего чтобы не найти ничего.

⚠ Выражение колонки обязано быть безотказным: оно считается на каждой вставке, и ошибка
в нём — это отказ `INSERT`, то есть **потерянный прогон**. Отсюда `JSON_VALID` (поле
объявлено `LONGTEXT`, содержимое база не проверяет), `REGEXP '^[0-9]{1,9}$'` (номер
приходит и строкой, и числом; десятый знак переполняет `INT`) и `NULLIF(…, '')`
(«ключа нет» и «ключ пустой» — одинаковый `NULL`, ровно как их читает питон).

⚠ `VIRTUAL`, а не `STORED`: `STORED` переписал бы всю таблицу под замком.

⚠⚠ **Переход на колонки починил тихую потерю прогонов.** Старый образец искал номер
вместе с кавычками, а движок кладёт переменные как есть — числовая форма
(`"subtask_id": 5219`) не совпадала никогда, и такие прогоны не находились ни журналом
(`task_log`), ни замерами (`task_metric`). Знал об этом только `task_abort`, где номер
приводили к числу явно. Сторож — `TestRunsFoundByTaskNumber` в `tests/test_task_log.py`.

### ⚠ Полный проход по этой таблице дороже, чем кажется по числу строк

В строке три LONGTEXT (`variables_start` в среднем 2.9 КБ), и 26 тысяч строк весят
174 МБ. Проход читает кластерный индекс целиком. Замерено на проде за 9 суток:
905 млн прочитанных строк по этой таблице — около **34 тысяч полных проходов**, по
одному каждые 23 секунды, ровно под такт опроса страниц команды и задач. Индексы
`(status, id)` и `(depth, status, id)` закрывают шесть из восьми её запросов и делают
счётчики вкладок `Using index` — то есть без чтения строк вовсе.

### `agent_workflow_trace_step` — выполненный шаг
```
id, run_id FK→agent_workflow_trace (CASCADE DELETE)
exec_index INT                   -- порядковый номер выполнения (не position; петли/переходы дают exec_index > шагов)
step_id INT NULL                 -- id шага (NULL если шаг удалён из workflow)
step_title CHAR(100), step_type CHAR(50)  -- снапшот на момент запуска
llm_id INT NULL FK→llm           -- NULL для tool/text/variable шагов
metadata_rendered LONGTEXT       -- вход: metadata шага ПОСЛЕ рендера %переменных%
variables_changed LONGTEXT       -- выход: JSON только изменённых/новых переменных
output LONGTEXT NULL             -- ответ LLM / результат инструмента / результат sub-workflow
transition LONGTEXT NULL         -- сработавший переход: {phase, condition, to_step_id}
status ENUM('success','error','retry')
error LONGTEXT NULL
created_at DATETIME(3)
duration_ms INT NULL
tokens_input INT NULL            -- входящие токены LLM-шага (pydantic-ai usage.request_tokens)
tokens_output INT NULL           -- исходящие токены LLM-шага (pydantic-ai usage.response_tokens)
```

## Запись из движка

### Модуль `src/ai/ai_workflow_trace.py`

Три публичных функции — каждая обёрнута в `try/except(logger_info)`: **сбой трейса никогда не роняет workflow**.

- **`ai_workflow_trace_run_start(...) → int | None`** — создаёт строку запуска (status=running), возвращает `run_id`. Проверяет `WORKFLOW_TRACE_ENABLED`.
- **`ai_workflow_trace_run_finish(run_id, status, result, error, duration_ms)`** — закрывает запуск.
- **`ai_workflow_trace_step(run_id, exec_index, step, ..., llm_id, tokens_input, tokens_output)`** — пишет шаг. Значения длиннее `TRACE_VALUE_MAX_LEN = 20_000` символов обрезаются `...[truncated]`.
- **`ai_workflow_trace_runs_stale_close()`** — вызывается на старте uvicorn, переводит `status=running` в `stopped` (прерваны рестартом).
- **`ai_workflow_trace_variables_diff(before, after)`** — утилита: только изменённые/новые ключи.

### Включение/выключение

Переменная `.env`: `WORKFLOW_TRACE_ENABLED=1` (по умолчанию включён). Проверяется один раз в начале каждой трейс-функции.

### Где вызывается в `ai_framework_manager.py`

```
_framework_workflow_run():
  run_uuid = uuid4()
  trace_run_id = ai_workflow_trace_run_start(run_uuid, workflow_id, agent_id, ...)
  workflow_runs_active[run_uuid] = asyncio.current_task()   ← для кнопки «Стоп»
  try:
    result = await _workflow_steps_run(model, ..., trace_run_id=trace_run_id)
    ai_workflow_trace_run_finish(trace_run_id, 'success', result, duration_ms)
  except CancelledError:
    ai_workflow_trace_run_finish(trace_run_id, 'stopped', ...)
  except Exception:
    ai_workflow_trace_run_finish(trace_run_id, 'error', error=traceback, ...)
  finally:
    workflow_runs_active.pop(run_uuid)

_workflow_steps_run():
  # На каждой итерации:
  trace_exec_index += 1
  trace_step_started = time.monotonic()
  trace_vars_before = dict(variables)

  # После LLM-шага (llm_to_json / return_response_llm):
  trace_llm_id = model.entity_llm_current.get('id')
  trace_tokens_input  = model.tokens_input    # заполняет ai_framework.py после engine_run
  trace_tokens_output = model.tokens_output

  # workflow_invoke (sub-workflow):
  child_run_id = ai_workflow_trace_run_start(..., parent_run_id=trace_run_id, depth=depth+1)
  # → рекурсивный вызов _workflow_steps_run(..., trace_run_id=child_run_id)

  await ai_workflow_trace_step(trace_run_id, trace_exec_index, current_step,
      metadata_rendered, variables_changed, output, transition,
      status, error, duration_ms, llm_id, tokens_input, tokens_output)
```

### Откуда берутся токены

В `src/ai/framework/agent/ai_framework.py`, сразу после `result = await engine.run(...)`:
```python
_usage = result.usage()          # pydantic-ai AgentRunResult
framework_model.tokens_input  = _usage.request_tokens   # входящие
framework_model.tokens_output = _usage.response_tokens  # исходящие
```
Поля `tokens_input/output` добавлены в `AiFrameworkModel`. Менеджер читает их после `await execute_llm_step()`.

## REST API

Все эндпоинты в `src/uvicorn/routers/workflow/workflow_trace.py`. Роутер подключён в `main_uvicorn.py`.

| Метод | Путь | Право | Назначение |
|-------|------|-------|------------|
| GET | `/workflow_trace/run/list` | `WORKFLOW_TRACE_VIEW` | Список запусков (depth=0), пагинация |
| GET | `/workflow_trace/run/{run_uuid}` | `WORKFLOW_TRACE_VIEW` | Запуск + шаги + дерево дочерних BFS |
| POST | `/workflow_trace/run/{run_uuid}/replay` | `WORKFLOW_TRACE_REPLAY` | Повтор с variables_start |
| POST | `/workflow_trace/run/{run_uuid}/stop` | `WORKFLOW_TRACE_STOP` | Отмена живой задачи |
| DELETE | `/workflow_trace/run/{run_uuid}` | `WORKFLOW_TRACE_DELETE` | Удаление (каскад FK) |

### GET `/workflow_trace/run/list`

Фильтры (query params): `workflow_id`, `agent_id`, `node_id`, `status` (running/success/error), `page`, `limit` (макс. 100).

⚠ **Ноды у прогона нет** — она у агента (`agent.node_id`), поэтому `node_id` разворачивается
в `r.agent_id IN (SELECT id FROM agent WHERE node_id = %s)`. Подзапросом, а не джойном: то же
условие идёт и в `COUNT(*)`, который таблицу агентов не джойнит, и порядок параметров у обоих
запросов остаётся общим.

Возвращает для каждого запуска: `steps_qty` (COUNT шагов), `children_qty` (COUNT дочерних запусков).

⚠ **`result` и `error` список не отдаёт** — карточка их не показывает, а это LONGTEXT
на тридцать строк; целиком они есть в ручке запуска, которая открывается щелчком по
карточке. `prompt_user` обрезан до 300 знаков на сервере: в карточке у него
`white-space: nowrap; text-overflow: ellipsis`, то есть видна ровно одна строка.

⚠ Уборки старых запусков здесь больше нет, она в кроне (см. «Обслуживание»).

### GET `/workflow_trace/run/{run_uuid}`

1. Загружает корневой запуск.
2. BFS по `parent_run_id` — собирает всё дерево потомков.
3. Один JOIN-запрос за шагами всех запусков дерева (`s.*, l.name AS llm_name`).
4. Собирает дерево: каждый запуск получает `steps: []` и `children: []`.
5. Возвращает корень с вложенными `children` и `steps`.

### POST `/workflow_trace/run/{run_uuid}/replay`

- Доступен только для `depth=0`.
- Загружает `variables_start` из записи запуска.
- Использует **текущую версию workflow** (не снапшот шагов) — для тестирования правок.
- Создаёт новую сессию `replay_session_uuid` — история replay не засоряет оригинальную переписку.
- Таймаут 60 сек.

### POST `/workflow_trace/run/{run_uuid}/stop`

- Отменяет `asyncio.Task` из `workflow_runs_active`.
- Если задачи нет (зависший `running` после рестарта) — помечает запись напрямую.
- Дочерние `running`-запуски закрывает здесь же (уровень за уровнем).

## Права доступа

```python
# src/auth/auth_permission.py
WORKFLOW_TRACE_VIEW   = "workflow_trace:view"
WORKFLOW_TRACE_DELETE = "workflow_trace:delete"
WORKFLOW_TRACE_REPLAY = "workflow_trace:replay"
WORKFLOW_TRACE_STOP   = "workflow_trace:stop"
```

В роли `user` выдано только `WORKFLOW_TRACE_VIEW`. Остальные права — у `admin`.

## Страница `/admin/workflow_trace`

**Файл:** `data/uvicorn/template/admin/workflow_trace.html`

### Структура

- **Фильтры сверху**: нода (select), workflow (select), агент (select) — три строки, в каждой
  заголовок и поле рядом (`.filter-row`); статус — вкладками над ними. Нода **ведущая**: она
  сужает два других списка до своих (см. ниже).
- **Слева — список запусков**: карточки с workflow-title, agent-title, статус-бейдж, длительность, кол-во шагов/дочерних.
- **Справа — детальная панель**: prompt_user → result, переменные запуска, LLM-вызовы, таймлайн шагов, дерево sub-workflow.
- **Между колонками — разделитель** `#traceResizer`: тянется мышью, ширина сайдбара живёт в
  `localStorage` под ключом `workflow_trace_sidebar_width` (общий помощник
  `js/sidebar_resizer.js`, тот же, что на `agent`, `tool`, `seed`, `agent_workflow`).

⚠ Ширина заголовка фильтра задана в `px` (`flex: 0 0 72px`) по самому длинному из трёх —
`WORKFLOW`. Меньше — и min-content раздвигает именно его строку: поля перестают стоять в
колонку, хотя правило у всех трёх одно.

### Нода сужает два других селекта

`node_id` есть и у `agent`, и у `agent_workflow`, а оба справочника страница и так держит
в памяти (`state.workflows`, `state.agents`) — поэтому отбор идёт на клиенте, без второго
похода на сервер. Пересобирает списки `filterOptionsRebuild`, она же наполняет их в первый
раз: отдельного кода начальной загрузки нет, и списку неоткуда разойтись самому с собой.

⚠ Сужение обязано совпадать с тем, что умеет ручка списка, а она отбирает прогоны по
`agent.node_id` и безнодового агента при выбранной ноде не вернёт никогда. Оставить такого
агента в селекте значило бы завести пункт, который всегда даёт пустой список.

⚠⚠ **Выбор, не переживший смену ноды, сбрасывается в «Все» и стирается из хранилища.**
Иначе он воскрес бы при следующей загрузке, когда нода снова станет своей, — человек
получил бы отбор, который сам уже потерял из виду. Отсюда же `option` «Все» с **явным**
`value = ''`: у `option` без атрибута `value` свойство `.value` отдаёт его текст, и в
запрос уехало бы `workflow_id=Все workflow`.

⚠ Сужение по `workflow.node_id` теоретически может спрятать workflow, чьи прогоны под этой
нодой есть: инвариант «workflow агента лежит на ноде агента» схемой не держится. На проде
проверено — таких прогонов 17 из 3663, и все до одного принадлежат **удалённым** workflow
(`LEFT JOIN` даёт NULL), то есть тем, которых в селекте нет ни при каком отборе. Живого
workflow с чужой нодой нет. Появится — сужение станет прятать реальный пункт, и чинить это
надо будет отбором по факту прогонов, а не по конфигурации.

### Выбор фильтров переживает перезагрузку

Три селекта пишутся в `localStorage` (`workflow_trace_filter_node` / `_workflow` / `_agent`),
карта ключей — `FILTER_STORAGE_KEY`; она же задаёт список селектов, на которые вешаются
слушатели. Восстановление (`filtersRestore`) идёт **после** наполнения справочников: у
пустого `select` выставлять нечего, и сохранённый выбор потерялся бы молча. Возврат к
«Все» — такой же выбор и сохраняется пустой строкой.

⚠ Сохранённый id, которого больше нет в списке (workflow удалён, агент переехал на другую
ноду), не восстанавливается и стирается из хранилища. `select` с `value` вне своих
`options` уходит в `selectedIndex = -1` и показывает **пустую строку** — не «Все workflow»,
а именно пустоту: человек видел бы отбор, которого не делал, и не понимал, почему список
пуст.

⚠⚠ **Порядок внутри `filtersRestore` — не стилистика.** Сперва ставится нода, затем
`filterOptionsRebuild` пересобирает зависимые списки, и только потом восстанавливаются
workflow и агент. Пока зависимые селекты не пересобраны, сохранённого workflow в их
`options` нет — и правило абзацем выше сочло бы его протухшим и стёрло из хранилища.

⚠ Начальная вкладка определяется пробой `status=running&limit=1`, и проба идёт **с
восстановленными фильтрами** (общий сборщик `filterParams` — он же у `loadRuns`). Без них
страница с выбранной нодой открывалась бы на Running из-за чужих прогонов и показывала
пустой список.

### Переменные: два аккордеона

В сводке перед «LLM вызовы» — ряд из двух свёрнутых аккордеонов рядом. Оба раскрываются
кликом по заголовку, тело строится при первом раскрытии (списков на странице десятки —
свой у каждого sub-workflow, а открывают единицы). Строка: `[чип группы]` · `%имя%` ·
бейджи · значение; list/dict — бейдж типа и вложенный JSON.

#### Чип группы — откуда имя взялось

Перед именем стоит чип со значком группы: 📥 входящие, 🇬 глобальные, 🇳 Node, ⚙️ Tool,
🇼 Workflow, 🌀 Dynamic. Из одного имени этого не видно, а позиция не подскажет —
списки отсортированы по алфавиту. В чипе только значок: название («Входящие
переменные»…) съедало бы треть строки, оно живёт подсказкой наведённой мыши. Цвета
чипов — те же, что у полосы `.variable-item-*` на панели редактора.

Значок и название — **отдельные поля секции**, а не одна строка: `variableGroupIndex`
отдаёт `{key, icon, label, title}`, где `title` — собранная подпись «значок +
название» для заголовков аккордеона и optgroup, а чипы берут `icon` и `label` врозь.
⚠ Доставать значок разбором подписи (`title.split(' ')[0]`) нельзя: подпись
показывают человеку, и восстанавливать по ней структуру — значит ловить неразрывный
пробел или название без значка чипом со словом вместо знака.

⚠⚠ **Правило разбора одно на обе страницы** и живёт чистым модулем
`js/workflow/variable-group.js` — ни DOM, ни сети, ни стейта (устройство —
`dashboard_frontend.md`). Страница зовёт `variableGroupIndex(реестр, шаги, workflows,
tools)`: реестр и шаги берутся **у этой ветки** (у sub-workflow scope свой), шаги
подаются как `{id: step_id, metadata: metadata_rendered}`. Своя копия правил разошлась
бы с панелью на первой правке — переменная числилась бы входящей в одном месте и
динамической в другом.

⚠ Ради справочника инструментов страница грузит `/tool/list` (право `TOOL_VIEW`) — из
имени инструмента и его выходных ключей собираются имена tool-переменных. Точка стоит в
общем `Promise.all` со справочниками фильтров: у всех ролей с `WORKFLOW_VIEW` есть и
`TOOL_VIEW`, но роль с одним без другого уронила бы заодно фильтры и иконки шагов.

⚠⚠ Имя, которого нет ни в реестре, ни в следах шагов, получает чип со значком ∅ и
подписью «не объявлена» в подсказке. Честный ответ, а не недосмотр: так выглядят,
например, имена, вычищенные из подстановки позже прогона, — на выгрузке 334 прогонов
это `companion_id/name/title`.

Ответ этот — **общая константа** `VAR_GROUP_UNKNOWN` в `variable-group.js`, той же
формы, что секции, и потому подставляется вместо них без оговорок. Держать её у
показывающего нельзя: пока её знала только трасса, панель графа на тех же именах
рисовала пустое место — а таких там 117 из 2075 по всем workflow установки (результаты
инструментов, чьих ключей нет в `args.output`, и алиас
`workflow_invoke_<шаг>_result_str` от движка).

**«Переменные (N)» — что было в прогоне.** Данные уже приходят в
`GET /workflow_trace/run/{run_uuid}`: снапшот `variables_start`, поверх него по порядку
выполнения ложатся `variables_changed` шагов. Показывается **последнее** значение, метка
говорит, откуда оно: `старт` или `шаг #N` (номер — `exec_index`).

**«Входящие workflow переменные (M)» — вход ветки.** Реестр из
`GET /workflow/{id}/variables` (право `WORKFLOW_VIEW`, то же, что у `/workflow/list` в
фильтрах страницы), отфильтрованный по `type = 'input'`: это контракт вызова — с чем
ветку позвали. Остальные объявленные (`workflow`, `global`, переменные ноды) не
показываются: они про внутреннюю кухню ветки, а фактические их значения и так в левом
списке. У строки — описание из реестра и значение: из прогона с меткой источника, а если
переменная значения не получила — умолчание реестра с меткой `умолчание`.

⚠⚠ **Чипа группы здесь нет намеренно.** Список строится как `реестр.filter(type ===
'input')`, а разбивка кладёт `type === 'input'` ровно в группу «Входящие» — чип у всех
строк вышел бы один и тот же и лишь повторял бы заголовок аккордеона. Проверено на 334
прогонах: 330 строк из 330 дали `input`, других не бывает по построению.

Ответы кэшируются по `workflow_id` на время жизни страницы и тянутся в `loadRunDetail`
**до** рендера: сам рендер синхронный и ждать не умеет. Реестр не загрузился (workflow
удалён, прав не хватило) — аккордеон просто не показывается, журнал остаётся читаемым.

У sub-workflow под заголовком дочернего запуска свой такой же ряд: и scope, и реестр
переменных у него собственные — одноимённая переменная у ребёнка своя.

Снапшот старта длиннее `TRACE_VALUE_MAX_LEN` пишется с хвостом `...[truncated]` и не
разбирается как JSON — вместо левого списка показывается предупреждение об обрезке.

### Строка шага (step-row)

```
[#N] [иконка типа] [Название шага] [LLM-badge] [↑tokens_in ↓tokens_out] [🔀] [status] [duration]
```

Раскрытие (аккордеон) показывает:
- **Вход**: `metadata_rendered` (pretty JSON)
- **Изменённые переменные**: `variables_changed` (diff)
- **Output**: сырой ответ LLM / результат инструмента
- **Переход**: `transition` (phase, condition, to_step_id)
- **Ошибка**: `error`

Иконки типов шагов: `stepTypeIcons` в state — маппинг `step_type → символ`.

### Токены в UI

Рядом с `llm_name`-бейджем: `step-tokens` (`↑N ↓N`). Показывается только для LLM-шагов (не null).

### Действия

- **Replay** — POST `/replay`, открывает результат в той же панели.
- **Stop** — POST `/stop`, доступно для `status=running` запусков.
- **Delete** — DELETE, с подтверждением.

## Обслуживание

- **Старт uvicorn и каждый тик конвейера**: `ai_workflow_trace_runs_stale_close()`
  закрывает застрявшие `running`-записи статусом `stopped`. Брошенной считается
  замолчавшая: ни одной строки шага дольше `TRACE_RUN_STALE_SECONDS` (9000с).

  **Порог обязан быть больше самого долгого шага.** Строка трассы пишется по
  завершении шага, поэтому работающая «реализация» (до 7200с) молчит и по этому
  признаку неотличима от мёртвой. Порог 3600 при шаге 7200 давал живым прогонам
  «Прерван рестартом сервера»: прогон 2470 подзадачи #5238 помечен брошенным в 04:44,
  а его шаг закончился в 04:51. Прогон при этом не гибнет — движок ставит `stopped`
  только сам, поймав отмену, — но журнал врёт, а ради ухода от этого функцию и писали.
  Связь держит `TestStaleTracesClosed` в `tests/test_task_pipeline.py`: берёт максимум
  из живых workflow, а не число из памяти.
- **Каскадное удаление**: `agent_workflow_trace_step` → FK `ON DELETE CASCADE`. Дочерние `agent_workflow_trace` → FK `ON DELETE CASCADE` (self-referencing).
- **Крон-чистка**: `src/cronjob/workflow_trace_cleanup.py`, раз в час. Сносит запуски
  старше `TRACE_KEEP_DAYS` (7) пачками по `TRACE_TRIM_BATCH` (200), потолок захода —
  `TRACE_TRIM_MAX` (10000). Шаги и sub-workflow уходят каскадом.

  ```
  POST /cronjob {"cronjob_path": "src/cronjob/workflow_trace_cleanup.py",
                 "metadata": {}, "timeout": 300}
  ```

  Событие в Cronicle заведено (2026-09-29) и своё на каждой инсталляции: на проде
  `emumz4duzzz`, локально `emumz63ughn`. Плагин `urlplug`, `timing: {"minutes": [40]}`
  — раз в час в :40, в стороне от соседей (`fact_verify` в :15, `cronicle_log_cleanup`
  в 04:30). `max_children: 1`, поэтому наложившийся запуск Cronicle пропустит;
  `catch_up: 0` — пропущенный час не догоняем, уборка не срочная.

  ⚠ Заводить событие можно **через API, а не только руками в UI** — так оно
  воспроизводимо и не зависит от того, что человек не забыл поставить галочку:

  ```bash
  docker exec cronicle sh -c '
  S=$(curl -s -X POST http://localhost:3012/api/user/login/v1 \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"admin\",\"password\":\"admin\"}" \
      | sed -n "s/.*\"session_id\":\"\([^\"]*\)\".*/\1/p")
  curl -s "http://localhost:3012/api/app/get_schedule/v1?session_id=$S"   # список
  curl -s -X POST "http://localhost:3012/api/app/run_event/v1?session_id=$S" \
       -H "Content-Type: application/json" -d "{\"id\":\"emumz4duzzz\"}"  # прогон
  '
  ```

  ⚠ Новое событие собирают **копией соседнего**, а не с нуля: у полей `target`,
  `category` и адреса входа значения свои на каждой инсталляции. На проде вход —
  `http://caddy:8090/cronjob` (Blue-Green: прямое имя контейнера переживает только
  чётное число деплоев), локально — `http://uvicorn:8000/cronjob`.

  Проверено прогоном через сам Cronicle на обеих установках: `Success (HTTP 200 OK)`.
  Первый прогон на проде снёс 126 прогонов, накопившихся с тех пор, как уборку убрали
  из ручки списка.

  ⚠⚠ **Раньше эта уборка стояла первой строкой ручки списка**, то есть шла на каждое
  открытие страницы трасс — а страница зовёт список дважды при заходе и ещё раз на
  каждое переключение вкладки, отбора и страницы. Стоило это 119 мс полного прохода по
  таблице в 174 МБ и удаляло **ноль строк**: 26 тысяч запусков набегают меньше чем за
  неделю, до порога не доживает никто. Хуже цены была блокировка: условие шло без
  индекса, а изоляция у базы `REPEATABLE-READ` — `DELETE` брал next-key-замок на каждую
  просмотренную строку, и открытие страницы трасс на сотню миллисекунд запирало запись
  трассы для всех идущих в этот момент workflow.

  ⚠ `depth = 0` в условии обязателен: у дочерних запусков свой `finished_at`, и он почти
  всегда раньше родительского — адресный снос выдрал бы ветки из-под живого дерева.
  ⚠ `ORDER BY finished_at` тоже: без него база выбирает, какие именно `batch` строк
  снести, на своё усмотрение, и уборка перестаёт быть «сначала самое старое».
- **Что за ней осталось**: `task_abort._inbox_fail` по-прежнему ищет прогон разбором
  JSON (`variables_start → $.task_shell_session`) полным проходом. Путь редкий —
  человек нажал «оборвать», — но если он станет частым, лечится так же: сгенерированной
  колонкой.
