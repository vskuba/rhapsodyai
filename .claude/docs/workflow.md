# Workflow: описание функционала, нюансы, пути развития

> Составлено по результатам анализа кода: редактор (`data/uvicorn/template/admin/agent_workflow.html`,
> `agent_workflow_variable.html`), API (`src/uvicorn/routers/workflow/*`), схема БД (`migrations/0001.sql`,
> сиды `0002.sql`), движок выполнения (`src/ai/framework/agent/ai_framework_manager.py`, `src/ai/ai_workflow.py`),
> журнал выполнения (`src/ai/ai_workflow_trace.py`, роутер `workflow_trace.py`, страница `admin/workflow_trace.html`,
> план: `docs/workflow_trace_plan.md`).

## 1. Назначение

Workflow — конструктор детерминированных цепочек действий для AI-агентов. Вместо того чтобы полагаться на
"свободное" поведение LLM с инструментами, workflow задает явный сценарий: какие шаги выполнить, в каком
порядке, с какими условными переходами, какие переменные пробросить между шагами. Агент (`agent.workflow_id`)
становится «носителем» workflow, а его `agent.workflow_variable` (JSON) — параметризацией: один и тот же
workflow обслуживает множество агентов с разными входными данными (пример из сидов: 4 агента-девушки
anna/dasha/lera/elena используют один workflow `dating_talk`, отличаясь только `{"document_id": ...}`).

## 2. Модель данных (MySQL)

| Таблица | Роль |
|---|---|
| `agent_workflow` | Сам workflow: name, title, node_id, position, description, **subflow** (зарезервирован: 0=основной, 1=под-процесс — пока не используется движком) |
| `agent_workflow_step` | Шаг: workflow_id, type_id, title, position (порядок выполнения), **metadata LONGTEXT** — JSON-конфиг шага |
| `agent_workflow_step_type` | Справочник 6 типов шагов (name, icon, description, metadata-схема) |
| `agent_workflow_variable` | Реестр переменных: name, **type ENUM('global','input','workflow')**, default, description |
| `agent_workflow_variable_workflow` | M:N переменная ↔ workflow (для workflow/input-переменных) |
| `agent_workflow_variable_public` | Публичные переменные (бывшие «переменные ноды»): name, node_id, **type ENUM('public','proxy')**, default, position, description. Редактируются менеджерами на публичных страницах |
| `agent_workflow_variable_public_role` | M:N публичная переменная ↔ роль (гранулярный доступ) |
| `agent_workflow_variable_public_workflow` | M:N публичная переменная ↔ workflow: переменная видна в редакторе только тех workflow ноды, к которым привязана |
| `agent` | workflow_id (FK) + workflow_variable (JSON-инициализация) |
| `session.metadata` | Персистентное состояние: `workflow_step_current_index` для continue_workflow |
| `agent_session` | История: user-prompt / response-final / tool-call / system-prompt |
| `agent_workflow_run` | Журнал: один запуск workflow — status running/success/error, prompt, result/error, `variables_start` (снапшот на старте), duration_ms; вложенность sub-workflow через `parent_run_id`/`parent_step_id`/`depth` |
| `agent_workflow_run_step` | Журнал: выполненный шаг — `exec_index` (порядок выполнения, не position), `metadata_rendered` (вход), `variables_changed` (дифф), `output`, `transition`, status success/error/retry, duration_ms; каскадное удаление с запуском |

## 3. Типы переменных и приоритет инициализации

Порядок сборки `workflow_variables_all` при запросе (`src/uvicorn/routers/chat/chat.py`):

1. **Базовые** — `prompt_user`, `user_id/username/email`, `agent_*`, `companion_*`, `session_uuid`, `workflow_id`, `node_id`.
2. **Из агента** — `agent.workflow_variable` (JSON).
3. **Из запроса** — `request.variables` (клиент может передать переменные).
4. **Публичные переменные ноды** (таблица `agent_workflow_variable_public`, включая proxy) — рендерятся по порядку `position` с учетом уже собранных (могут ссылаться на них: `girl_title` default=`%prompt_user%`).
5. **Переменные workflow** (`type='workflow'`) — default-значения, добавляются только если ключа еще нет.
6. **Валидация global** — все `type='global'` обязаны присутствовать, иначе HTTP 400.
7. **Валидация input** — все `type='input'` обязаны присутствовать, иначе HTTP 400. **Это готовый контракт входа для будущих sub-workflow.**

Рендеринг: `ai_workflow_variables_render()` (`src/ai/ai_workflow.py`) — рекурсивная подстановка `%name%`
в строки/dict/list. **Нюанс — умная замена типов**: если строка состоит только из плейсхолдера (`"%id%"`),
возвращается исходное значение с типом (int/list/bool), а не строка.

**Условные блоки в шаблонах**: `%if var%...%else%...%endif%` (+ отрицание `%if !var%`) —
разворачиваются ДО подстановки переменных (`ai_workflow_if_blocks_render`). Переменная «истинна»,
если существует и ее значение не пустое, не `0` и не `false` (`0` — принятый сигнал «ничего нет»
из llm_to_json-шагов). Вложенность поддерживается (блоки разворачиваются изнутри наружу),
`%else%` опционален, незакрытый блок остается в тексте как есть. Основной кейс — скрытие пустых
секций промпта: `%if search_result%=== Заголовок ===\n%search_result%\n\n%endif%`.

## 4. Типы шагов (семантика движка)

Движок: `_framework_workflow_run()` (`src/ai/framework/agent/ai_framework_manager.py:119-260`) —
обертка резюме/`continue_workflow`; сам цикл шагов и переходов — `_workflow_steps_run()` (строки 261-878).
Цикл: `while step_index < steps_count`, на каждой итерации metadata шага прогоняется через рендер переменных.

| Тип | Что делает | Ключи metadata |
|---|---|---|
| `return_response_llm` ↩L | Отправляет контекст в LLM, результат — финальный ответ пользователю. **Завершает workflow.** | `prompt_user` |
| `llm_to_json` 🧠 | Запрос к LLM с требованием JSON; парсит ответ (`_json_str_clean` вырезает JSON из текста), проверяет наличие всех ожидаемых ключей, кладет их в переменные. До 3 повторов при ошибке парсинга. | `llm_to_json_variable: [{variable, text}]`, `prompt_user` |
| `tool_invoke` ⚙️ | Вызывает python-инструмент. Аргументы собираются из переменных по `inputs_map` (arg → имя переменной). Результат-dict раскладывается в переменные `{tool_name}_{step_id}_result_{key}`; скаляр — `{tool_name}_{step_id}_result_{typename}` (str/int/bool/list/float). ID шага в имени делает переменную уникальной: повторные вызовы одного инструмента не перезаписывают друг друга. Пишет tool-call в `agent_session`. | `tool_invoke: {tool_name, inputs_map}` |
| `return_response_text` ↩T | Возвращает текст-шаблон (после рендера переменных). **Завершает текущий запрос**; при `continue_workflow=true` сохраняет индекс следующего шага в `session.metadata` — следующий запрос пользователя продолжит workflow с этого места (диалоговые сценарии-«визарды»). | `prompt_user`, `continue_workflow` |
| `variable_conversion` ❴❵ | Переопределяет переменные значениями-шаблонами (рендер уже произошел). Используется для склейки JSON-строк, преобразования результатов инструментов. | `variable_conversion: [{variable, text}]` |
| `workflow_invoke` 🔁 | Вызывает другой workflow как под-процесс в **изолированном scope**: только явные входы по `inputs_map` (родительская переменная → input ребенка) + default'ы переменных ребенка; input-контракт валидируется. Результат → `{child_name}_{step_id}_result_str` + копии по `outputs_map`. Лимит глубины `MAX_WORKFLOW_DEPTH=5`, детект циклов по стеку workflow-id. Внутри подавлены side-эффекты: system/user-prompt и response-final не пишутся в историю, `continue_workflow` игнорируется с warning. | `workflow_invoke: {workflow_id, inputs_map, outputs_map}` |

## 5. Переходы (transitions)

В metadata каждого шага: `transitions_before` (проверяются ДО выполнения шага) и `transitions_after`
(ПОСЛЕ, уже после инкремента индекса). Формат: `{variable, operator, value, step_id}`.
Операторы: `==`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `not_contains`, `regex`, `exists`, `empty`
(числа сравниваются численно; `exists`/`empty` оценивают наличие/пустоту переменной и работают даже
для отсутствующих переменных, поле «Значение» у них игнорируется; `regex` — `re.search` по значению,
битый паттерн даёт False с warning). Первый сработавший переход выигрывает, движок прыгает на шаг
с `step_id` (маппинг id → индекс).

**Нюанс:** после before-перехода целевой шаг выполняется сразу — его собственные `transitions_before`
НЕ проверяются (цепочки before-прыжков не работают), а вот `transitions_after` вычисляются уже
по metadata целевого шага. Сработавший переход пишется в журнал выполнения (поле `transition`).

Завершение workflow: прошли все шаги (возврат «Воркфлоу успешно завершен.»), либо `return_response_llm`
/ `return_response_text`, либо исключение.

## 6. Жизненный цикл запроса

```
POST /chat/ask
  → загрузка агента, LLM (по user_llm, с ротацией по rate_limit_at), шагов workflow, переменных
  → сборка workflow_variables_all (приоритеты §3) + валидация global/input
  → framework_model_create() + framework_workflow_run() (asyncio-таска)
  → await future (timeout 60 сек)
  → восстановление step_index из session.metadata (continue_workflow)
  → цикл шагов → future.set_result(ответ)
```

LLM-шаги выполняются через очередь `ai_framework_model` (`queue_`) — модель кладется в очередь, ответ
приходит через `on_complete`-callback (`execute_llm_step`).

Параллельно с выполнением пишется журнал (`src/ai/ai_workflow_trace.py`): запись запуска при старте
(status=running, снапшот переменных), строка на каждый выполненный шаг (вход/дифф переменных/output/
переход/длительность, статусы success/error/retry), закрытие запуска (result либо error + duration).
Сбой записи журнала никогда не роняет workflow; выключатель — env `WORKFLOW_TRACE_ENABLED`.

**Важно про персистентность:** между запросами сохраняется только `workflow_step_current_index`
(в `session.metadata`) и история сообщений (`agent_session`). Сам словарь переменных живет в памяти
одного запроса и пересобирается заново — накопленные в середине workflow значения теряются при
continue_workflow, если не были возвращены пользователю или не восстанавливаются шагами заново.

## 7. Редактор (админка)

- **`/admin/agent_workflow`** — два режима: «Настройки» (title/name/node/position/description + список
  входящих переменных type='input' с добавлением/удалением/редактированием) и «Шаги» (drag-drop список,
  панель переменных в 5 группах: входящие/общие/ноды/tool/workflow, конструктор metadata по типу шага,
  редактор переходов before/after). Неиспользуемые в шагах workflow-переменные подсвечиваются серым
  (`extractVariablesFromSteps` → класс `unused-variable`).
- **`/admin/variable`** (шаблоны `agent_workflow_variable_public.html` — admin и custom/dating) — реестр
  публичных переменных по нодам: name, node, description, роли, type (public/proxy), default, drag-drop
  порядка (position). Подсказки под полем «Значение» — proxy-переменные той же ноды (эндпоинт
  `/workflow_variable/public/{id}/hints`). Для ролей manager_dating* рендерится упрощенный кастомный шаблон
  (только значение + подсказки). Field-policy (`agent_workflow_variable_public`): не-админ читает
  ограниченный набор полей и пишет только `default`.

## 8. Известные баги и тонкости (актуализировано при повторном анализе)

1. **[ИСПРАВЛЕНО] Числовые сравнения в переходах** — `>` и `<` сравнивали строки лексикографически.
   Теперь `_transition_condition_check()`: числа сравниваются численно (try-float), иначе — строки.
2. **[ИСПРАВЛЕНО] KeyError при отсутствии переменной в переходе** — отсутствующая переменная теперь
   означает «условие не выполнено» (переход пропускается с warning в логе), а не падение workflow.
3. **Жадная регулярка в `_json_str_clean`** — `(\{.*})` захватит от первой `{` до последней `}`;
   на ответе LLM с двумя JSON-блоками парсинг сломается (`ai_framework_manager.py:938`).
4. **Потенциальный deadlock в `execute_llm_step`** (строка 369) — если `on_complete` не будет вызван
   consumer'ом очереди, `await step_future` повиснет (спасает только таймаут запроса, см. §9 ниже).
5. **Временный JSON-prompt в `execute_llm_step` фактически не применяется** — `model.prompt_system`
   подменяется перед `queue.put(model)` и восстанавливается сразу после (строки 385-394), до того как
   consumer очереди прочитает модель: LLM почти всегда получает оригинальный prompt, JSON спасает
   только `_json_str_clean`. Если consumer в другом потоке — это гонка. Правильно: передавать
   переопределение отдельным полем модели, а не мутировать общий prompt_system.
6. **IndexError при continue_workflow после правки workflow** — сохраненный
   `workflow_step_current_index` не проверяется на границы: если шаги удалили между запросами,
   `model.workflow_steps[start_index]` упадет (`_framework_workflow_run`, строка 174).
7. **Переход на удаленный шаг роняет workflow** — `workflow_steps_mapping[target_step_id]` дает
   KeyError (строки 329 и 850, before/after), а `int(transition.get('step_id'))` — TypeError при
   пустом step_id. Graph-режим редактора предупреждает о битых ссылках, но сохранить их по-прежнему можно.
8. **Счетчик ретраев llm_to_json общий на весь запуск** — `iteration_exception` (инициализация
   строка 280, инкремент 474-475) не сбрасывается между шагами: 3 неудачные попытки суммарно на ВСЕ
   llm_to_json-шаги запуска, а не на каждый.
9. **Таймаут запроса не останавливает workflow** — по timeout `chat.py:217` отменяет только future
   (`future.cancel()`, строка 221); фоновая asyncio-задача (`asyncio.create_task(...)`,
   `ai_framework_manager.py:83`, ссылка на task нигде не сохраняется) продолжает выполнять шаги,
   жечь LLM-токены и писать в журнал/сессию.
10. **Зависшие `status='running'` в журнале** — при рестарте сервера посреди запуска записи
    `agent_workflow_run` остаются running навсегда (нужен janitor при старте или в крон-чистке).
11. **Рендер раскрывает плейсхолдеры внутри подставленных значений** —
    `ai_workflow_variables_render` продолжает замену по уже обновленной строке: если значение
    переменной само содержит `%other%`, оно тоже раскроется. Следствие — инъекция через
    пользовательский ввод: `prompt_user` со строкой `%secret_var%` вытянет значение переменной scope.
12. Результаты инструментов сериализуются в строки — `%tool_result%`-переменная со списком после
    вставки в шаблон становится JSON-строкой; «умная замена типов» помогает только когда плейсхолдер — вся строка.
13. Колонка `subflow` в `agent_workflow` используется только UI (чекбокс «Sub-workflow», скрытие из
    селекта workflow агентов); движок флаг не проверяет — `workflow_invoke` может вызвать и «основной» workflow.
14. Переменные с одинаковыми именами: `inputs_map` в `tool_invoke` хранится и как `metadata.tool_invoke.inputs_map`
    (движок) — фронтовые обработчики должны учитывать вложенность.

> Удалено из списка: дубликат `input_values_set()` в task-фреймворке — файл
> `py_modules/ai/framework/task/ai_framework_manager.py` больше не существует.

## 9. Пути оптимизации и улучшения

### 9.1 Ближние (устранение рисков)
- Исправить актуальные баги §8 (3-11) — прежде всего защиту индекса continue_workflow (§8.6),
  переходы на несуществующие шаги (§8.7) и отмену фоновой задачи по таймауту (§8.9).
- ✅ Добавлены операторы переходов: `>=`, `<=`, `exists`, `empty`, `not_contains`, `regex`
  (движок `_transition_condition_check` + селекты в редакторе переходов).
- ✅ **Журнал выполнения (execution trace)** — реализован по плану `docs/workflow_trace_plan.md`:
  - таблицы `agent_workflow_run` / `agent_workflow_run_step` (0001.sql): снапшот переменных в шапке
    запуска + диффы по шагам, значения >20 КБ обрезаются с пометкой `...[truncated]`;
  - модуль `src/ai/ai_workflow_trace.py` — сбой записи не роняет workflow, выключатель
    `WORKFLOW_TRACE_ENABLED`;
  - интеграция в движок: статусы success/error/retry (retry llm_to_json — отдельной строкой),
    сработавшие переходы, дочерние запуски sub-workflow (`parent_run_id`/`parent_step_id`/`depth`);
  - API `GET /workflow_trace/run/list` (пагинация, фильтры workflow/agent/status),
    `GET /workflow_trace/run/{uuid}` (дерево с шагами одним ответом), `DELETE` (каскад);
    права `WORKFLOW_TRACE_VIEW`/`WORKFLOW_TRACE_DELETE`;
  - страница `/admin/workflow_trace` (меню «Logs»): фильтры в левой колонке, автовыбор последнего
    запуска, таймлайн шагов с аккордеоном (вход/выход/output/переход/ошибка), вложенные
    sub-workflow, удаление запуска.
  **Не сделано из плана:** крон-чистка (`WORKFLOW_TRACE_TTL_DAYS`, файла
  `src/cronjob/workflow/trace_cleanup.py` нет), trace-overlay на графе,
  фильтры по пользователю и дате, переход из шага журнала в редактор workflow.
- Валидация workflow при сохранении: ссылки переходов на существующие шаги, наличие используемых
  переменных, достижимость шагов (Graph-режим показывает предупреждения на клиенте, но сохранить
  битый граф по-прежнему можно — нужна серверная проверка в PUT).
- Персистентность переменных при `continue_workflow`: сохранять снапшот `workflow_variables` в
  `session.metadata` рядом с индексом шага (снапшот на старте уже пишется в журнал —
  `agent_workflow_run.variables_start` — его же можно использовать для восстановления).

### 9.2 Sub-workflow (главное направление)
Цель: workflow вызывает другой workflow как шаг, передает входящие переменные, получает результат, продолжает.

**Статус: движок реализован** (`ai_framework_manager.py`):
- `ai_workflow_load(workflow_id)` — общая загрузка workflow (сущность + шаги + переменные),
  переиспользуется chat.py и движком;
- цикл шагов вынесен в runner `_workflow_steps_run(model, steps, variables, start_index, depth,
  workflow_stack)` — терминальные шаги возвращают результат, а не пишут в future;
- шаг `workflow_invoke`: изолированный scope ребенка — **только явные входы** (inputs_map +
  default'ы переменных ребенка, никакого неявного наследования из родителя); контракт задают
  input-переменные ребенка (даже базовые вроде `prompt_user` объявляются input'ом subflow и
  мапятся явно); лимит глубины (`MAX_WORKFLOW_DEPTH=5`), детект циклов по стеку workflow-id;
  результат → `{child_name}_{step_id}_result_str` + копии по outputs_map;
- в sub-workflow подавлены побочные эффекты верхнего уровня: system/user-prompt и response-final
  не пишутся в историю, `continue_workflow` игнорируется с warning, `is_transition=True` для
  return_response_llm (ответ ребенка — промежуточный, не финальный).

UI и БД тоже готовы: тип шага id=6 (сиды), виджет `widget_workflow_invoke` (селект workflow +
маппинг input-переменных ребенка + подсказка переменной результата), чекбокс «Sub-workflow» в
настройках workflow, скрытие subflow=1 из селекта workflow агентов, переменная результата в
группе tool-переменных, оранжевый узел на графе переходов.

Формат metadata шага `workflow_invoke` (id=6):
```json
{
  "workflow_invoke": {
    "workflow_id": 7,
    "inputs_map":  { "document_id": "girl_document_id" },
    "outputs_map": { "summary": "girl_summary" }
  },
  "transitions_before": [], "transitions_after": []
}
```

**Осталось из дизайна:**
- контракт выхода: добавить `type='output'` в ENUM переменных, чтобы редактор показывал, что именно
  возвращает под-процесс, а `outputs_map` собирался из селекта, а не вручную;
- таймаут на дочерний вызов (сейчас sub-workflow ограничен только общим 60-сек таймаутом запроса);
- журнал уже пишет дочерние запуски деревом — на странице trace они отображаются вложенным
  таймлайном (реализовано).

### 9.3 Дальнейшее развитие
- **Версионирование workflow** (draft/published + копия шагов) — сейчас правка ломает живых агентов мгновенно.
- **Типизация переменных** (str/int/json/bool + поле `pattern` для regex-валидации — колонку в БД добавить, идея уже витает в field-policy).
- **Обработка ошибок как переход** — `on_error: step_id` в metadata шага вместо падения всего workflow.
- **Параллельные шаги** — группа tool_invoke без взаимных зависимостей (asyncio.gather).
- **Dry-run из админки** — кнопка «Тест» с ручными значениями input-переменных; трейс по шагам уже
  есть (журнал) — достаточно флага «не писать в agent_session» и запуска от имени тестовой сессии.
- **Визуализация графа** — ✅ реализовано: третий режим редактора (кнопка «Graph» в шапке формы,
  `#stepsGraph`). Диаграмма строится на клиенте (mermaid, вендорен в `/static/js/vendor/`) из
  `allCurrentStepsData`: сплошные ребра — последовательное выполнение, пунктирные — условные
  переходы (before/after) и `continue_workflow`, цвета узлов — по типам шагов, терминальные шаги —
  «стадионы». Клик по узлу открывает шаг в редакторе; активный шаг подсвечен рамкой. Под шапкой —
  предупреждения валидации: недостижимые шаги и переходы на несуществующие step_id.
- **Trace-overlay на графе** — подсветить пройденный маршрут запуска поверх Graph-режима
  (данные уже есть: `exec_index` + `transition` из журнала): пройденные ребра зеленые, упавший шаг красный.
- **Replay запуска** — ✅ реализовано: `POST /workflow_trace/run/{uuid}/replay` (право
  `WORKFLOW_TRACE_REPLAY`, только admin) + кнопка «🔁 Повторить» в сводке запуска на странице trace.
  Прогоняет workflow с сохраненным снапшотом `variables_start`; шаги берутся из ТЕКУЩЕГО определения
  workflow (проверка правок на реальных входных данных); история и continue_workflow-индекс пишутся
  в новую сессию (оригинальная переписка не засоряется); LLM — пользователя запуска, с фолбэком на
  текущего; replay-запуск сам попадает в журнал и автоматически открывается в списке.
- **Метрики из журнала** — агрегаты по `agent_workflow_run_step`: среднее/максимальное время шага,
  доля ошибок и ретраев по workflow — готовая витрина «какой шаг тормозит сценарий».

### 9.4 Производительность
- **Кэш загрузки на chat/ask** — сейчас на каждый запрос 6-7 SQL: workflow + шаги + переменные,
  global-переменные, input-переменные, публичные переменные ноды, полный список tools. Всё это
  меняется редко — просится TTL-кэш в памяти (инвалидация по PUT workflow/step/variable).
- **Однопроходный рендер переменных** — `ai_workflow_variables_render` для каждой строки
  перебирает ВСЕ переменные (O(строк × переменных)); замена на один проход
  `re.sub(r'%(\w+)%', lookup)` быстрее и заодно закрывает инъекцию §8.11 (значения не ресканируются).
- **Запись журнала вне критического пути** — каждый шаг ждет INSERT в
  `agent_workflow_run_step` (плюс COMMIT); при выключенном пуле это заметная добавка к каждому шагу.
  Вариант: fire-and-forget (`asyncio.create_task`) или буфер с батч-вставкой при завершении запуска.
- **COUNT(*)-подзапросы в `/workflow_trace/run/list`** (`steps_qty`, `children_qty`) — на больших
  объемах журнала заменить на LEFT JOIN с GROUP BY или денормализованные счетчики в шапке запуска.
- **Крон-чистка журнала** — без TTL таблицы `agent_workflow_run*` растут неограниченно
  (LONGTEXT-поля); заодно janitor для зависших `status='running'` старше часа (§8.10).

## 10. Чек-лист задачи «создать новый workflow»

Каждая задача на новый workflow должна фиксировать:

1. **Назначение** — одна фраза: что сценарий делает для пользователя.
2. **Нода** и агент(ы)-носители (или subflow=1, если это под-процесс).
3. **Входящие переменные** (`type='input'`): имя, описание, пример значения — контракт входа.
4. **Используемые инструменты** — есть ли готовые (`src/tool/*`), что нужно дописать.
5. **Схема шагов** — таблица: №, тип, назначение, ключевые поля metadata, какие переменные читает/пишет.
6. **Переходы** — условия ветвления (переменная, оператор, значение, целевой шаг).
7. **Точки выхода** — какие шаги завершают сценарий (`return_response_*`), нужен ли `continue_workflow`.
8. **Результат** — что получает пользователь/родительский workflow (будущий контракт выхода).
9. **Тест-сценарий** — 2-3 примера входа и ожидаемого поведения (включая ветку ошибки).

## 11. Правила создания инструментов (src/tool/)

**Папка = область инструмента.** Каждый инструмент лежит в папке, название которой отвечает
за его предметную область, и ВСЕ инструменты этой области живут в одной папке:

| Область | Папка | Примеры инструментов |
|---|---|---|
| MySQL (экспорт, поиск таблиц, любые операции с БД) | `src/tool/mysql/` | `mysql_tables_find`, `mysql_export_to_migration` |
| Qdrant | `src/tool/qdrant/` | `qdrant_fact_search`, `qdrant_fact_remove` |
| Git | `src/tool/git/` | будущие git-инструменты |
| Факты | `src/tool/fact/` | `fact_collection_add`, `fact_collection_output_format` |
| Сессии | `src/tool/session/` | `session_messages` |
| Окружение (прод/локаль) | `src/tool/env/` | `env_is_prod` |

Правила:
1. **Имя функции начинается с области**: `mysql_*`, `qdrant_*`, `git_*` — по имени сразу видно,
   к какой папке и подсистеме относится инструмент.
2. **Инструменты делаются узкими и составными**: вместо одного «умного» инструмента — цепочка
   простых, соединяемых через переменные workflow. Пример: `mysql_tables_find(pattern)` находит
   таблицы по вхождению → его `tables_str` подается на вход `mysql_export_to_migration(tables,
   migration_file)`. Каждый переиспользуем отдельно.
3. **Аргументы — простые типы** (str/int/bool): значения приходят из workflow-переменных;
   списки передаются строкой через запятую, сложные структуры — JSON-строкой.
4. **Возврат — dict с говорящими ключами** (`{"tables_qty": ..., "report_str": ...}`): каждый
   ключ станет переменной `{tool}_{step_id}_result_{key}` в workflow.
5. **Регистрация автоматическая, но с нюансом force**: `ai_tool_sync()` сканирует `src/tool/` и
   пересобирает таблицу `tool` (группа — по имени папки), НО пропускает синк молча, если в `tool`
   уже есть хоть одна запись, а `force=True` не передан (`src/ai/ai_tool.py:26-29`) — а после первого
   же деплоя запись там есть всегда. `main_uvicorn.py` (лайфспан, вокруг строки 89) вызывает синк
   по-разному в зависимости от окружения: `ai_tool_sync(force=True)` на проде (`env_is_prod()`),
   `ai_tool_sync()` (без force) локально. Значит на ПРОДЕ новый/переименованный/перемещенный
   инструмент подхватится автоматически при каждом рестарте uvicorn; ЛОКАЛЬНО простой рестарт
   недостаточен — нужен ручной `ai_tool_sync(force=True)` (или очистка таблицы `tool`). Дважды
   наступали на эти грабли: `mysql_migration_prod_create` и `env_is_prod` тихо не появлялись в
   `tool` после деплоя, пока не был сделан форс-синк вручную.
6. **Безопасность**: все, что попадает в SQL/shell/пути из аргументов, валидируется
   (см. проверку имен таблиц в `mysql_export_to_migration`).
7. **Инструмент возвращает dict — ключи ОБЯЗАТЕЛЬНО описываются в docstring** (секция
   `Returns:`): описания попадают в БД через `ai_tool_sync` и показываются в UI
   (детали инструмента, Output Mapping). Формат:

   ```python
   async def github_user_info(random: int = 2) -> dict:
       """
       This function returns the full name of the repository.
       It identifies the repository based on its most recent active commits.
       Returns:
           A dictionary containing the user's GitHub login, name, and email.
           login (str): The GitHub username of the authenticated user.
           name (str): The full name of the authenticated user.
           email (str): The email address associated with the authenticated user's GitHub account.
       """
   ```

## 12. Workflow-оболочка для тестирования (`workflow_shell_test`, id 9)

Универсальный тестер: LLM играет роль собеседника и в цикле разговаривает с целевым
workflow. Запускается из чата агентом **Workflow tester** (нода Dev). Сначала мастер
из трех вопросов собирает цель (выбор чипсами `[[...]]`): нода → workflow ноды → агент
этого workflow. Затем пользователь пишет сценарий (кто собеседник, о чем говорит,
чего добивается) — и запускается цикл диалога.

**Прод-заглушка (шаги id 154/155, position -2/-1)** — тестовые прогоны имеют смысл только
локально (жгут LLM-токены и пишут в БД, ничего не проверяют на реальном проде), поэтому
самый первый шаг workflow (по порядку выполнения, ДО мастера на position 0) — проверка
окружения:
```
pos -2  id=154  tool_invoke  env_is_prod() → is_prod ('1'/'0')
                transitions_after: is_prod=='1' → шаг 155 (заглушка)
                                   is_prod=='0' → шаг 73  (первый шаг мастера, "ноды")
pos -1  id=155  return_response_text  «🚫 Тестовые прогоны workflow доступны только
                локально, на проде отключены.» (continue_workflow=false, завершает запуск)
```
Оба исхода — явные переходы по `step_id`, а не «естественный next-step» (грабли, на которые
уже наступали при первой реализации: раз шаг 155 идет сразу за 154 по position, он выполнился
бы ВСЕГДА, если не прописать переход и для ветки is_prod=='0' тоже — простое `False` условие
лишь не прыгает, а не пропускает следующий по порядку шаг). Инструмент `env_is_prod`
(`src/tool/env/env_.py`) смотрит `APP_ENV` (на проде — `_prod`, см. §11 про force-синк).

**Шаги мастера и цикла (нода Dev, workflow 9, position 0+ — не сдвинуты, заглушка выше добавлена с отрицательным position):**

Мастер построен на универсальных инструментах — конвейер «выборка → колонка → чипсы»:
`mysql_find_by(table, criteria)` → `dict_column(rows, 'name')` → `list_render(names,
'[[%s]]', ' ')`. Параметры выборки задаются шагом `variable_conversion` перед каждым
вызовом (переменные `find_table`, `find_criteria`).

```
-- Мастер выбора цели (каждый вопрос — continue_workflow, ответ приходит следующим сообщением)
pos 0-4   ноды:     conversion(node, {}) → mysql_find_by → dict_column(name)
                    → list_render → return «Спросить ноду» [continue]
pos 5-11  workflow: conversion({name: prompt_user}) → mysql_find_one_by(node) →
                    conversion({node_id: X, subflow: 0}) → mysql_find_by → dict_column
                    → list_render → return «Спросить workflow» [continue]
pos 12-18 агенты:   mysql_find_one_by(agent_workflow по имени) → test_workflow_id →
                    mysql_find_by(agent по workflow_id) → dict_column → list_render
                    → return «Спросить агента» [continue]
pos 19-23 конфиг:   mysql_find_one_by(agent по имени) → dict_column(workflow_variable,
                    document_id) → conversion(target_agent_*, document_id)
                    → return «Спросить сценарий» [continue]

-- Цикл диалога
pos 24 session_uuid_create            — отдельная сессия диалога (не засоряет сессию тестера)
pos 25 llm_to_json «Сообщение тестера» — LLM придумывает следующее сообщение по сценарию
                                         и накопленному диалогу (%test_dialog%)
pos 26 workflow_invoke                — вызов целевого workflow: id из %test_workflow_id%,
                                         передаются prompt_user, session_uuid и identity цели
pos 27 session_message_add             — пишет пару user-prompt/response-final в сессию диалога,
                                         чтобы session_messages целевого workflow видел историю
pos 28 counter_increment              — +1 к счетчику
pos 29 variable_conversion            — append диалога + счетчик; переход
                                         test_iteration < %test_iterations_limit% → на pos 25
pos 30 return_response_text           — стенограмма диалога + uuid сессии
```

**Настройка (переменные workflow 9; мастер заполняет их сам, defaults — запасной вариант):**

| Переменная | Default | Назначение |
|---|---|---|
| `test_workflow_id` | 5 | Целевой workflow (заполняет мастер) |
| `test_iterations_limit` | 20 | Сколько циклов диалога |
| `target_agent_id/name/title` | 20/anna/Анна | Identity целевого агента (заполняет мастер) |
| `document_id` | anna | Из workflow_variable выбранного агента (заполняет мастер) |
| `chat_timeout` | 1800 | Таймаут ответа в чате, сек (см. ниже) |

**Что для этого добавлено в платформу:**

- Движок: алиас результата `workflow_invoke_{step_id}_result_str` (не зависит от имени
  целевого workflow — `workflow_id` можно задавать переменной).
- Движок: переменная `prompt_system` в scope переопределяет системный промпт агента.
  Критично для оболочки: model принадлежит агенту-тестеру, и без переопределения
  целевой workflow отвечал бы промптом тестера, а не персоной целевого агента
  (мастер передает `agent.prompt_system` цели через inputs_map шага workflow_invoke).
- Движок: **переменные переживают continue_workflow** — вместе с индексом шага в metadata
  сессии сохраняется снапшот изменённых переменных (`workflow_variables_saved`) и
  восстанавливается при resume. Переменные запроса (prompt_user, session_uuid, agent_* —
  всё с `type='global'` в `agent_workflow_variable`) в снапшот не попадают и не
  восстанавливаются: их владелец — чат-слой, каждое сообщение приносит их заново
  (`_workflow_variables_protected()`). Без этого мастер терял бы выбор пользователя
  между сообщениями.
- Универсальные инструменты:
  `mysql_find_by(table_name, criteria, limit)` / `mysql_find_one_by(table_name, criteria)`
  (src/tool/mysql/) — выборка записей; criteria — dict, значение-список → IN, None → IS NULL,
  имена таблицы/колонок валидируются, datetime приводится к строке;
  `dict_column(data, column_name)` (src/tool/dict/) — значения по ключу из списка словарей,
  словаря или JSON-строки; `list_render(items, template, separator)` — форматирование списка
  ("[[%s]]" + " " = чипсы чата); `counter_increment(value, step)` — счетчик циклов;
  `session_message_add(session_uuid, user_message, agent_response, agent_id, user_id)` —
  запись пары сообщений в сессию.
- Чат: переменная `chat_timeout` поднимает таймаут ожидания ответа (по умолчанию 60 сек).

**Ограничения:** бюджет `MAX_WORKFLOW_ITERATIONS = 300` шагов на запуск — при 5 шагах цикла
лимит итераций ~55; каждый цикл — это 1 LLM-вызов тестера + LLM-вызовы целевого workflow,
20 циклов dating_talk ≈ 60+ LLM-вызовов (минуты). Прогон целиком виден в
`/admin/workflow_trace`: каждый вызов целевого workflow — вложенный child-run.

## 13. Интерактивный синтаксис чата: чипсы, команды, вопросы

### 13.1 Поддержка по платформам

| Функция | Admin Chat (`/admin/chat`) | Telegram Mini App |
|---|---|---|
| `[[text]]` чипсы | ✅ полная | ❌ нет |
| Авто-ссылки `http://...` | ✅ | ✅ |

В Telegram Mini App `appendBubble()` делает только `linkify()` (преобразует `http://...` в `<a>`).
`[[]]`-чипсы там НЕ работают — они выведутся как обычный текст со скобками.

### 13.2 Синтаксис чипсов (admin chat)

Regex разбора: `\[\[link:([\s\S]+?)\]\]|\[\[\+([\s\S]+?)\]\]|\[\[!([\s\S]+?)\]\]|\[\[([\s\S]+?)\]\]`

| Синтаксис | Действие при клике | CSS-класс |
|---|---|---|
| `[[текст]]` | Вставляет текст в поле и **отправляет** | `.chat-suggestion` |
| `[[+текст]]` | Вставляет текст в поле **без отправки** (можно дописать) | `.chat-insertion` |
| `[[!текст]]` | Вставляет и **отправляет** (красный стиль — опасное действие) | `.chat-danger` |
| `[[link:URL\|текст]]` | Открывает URL в новой вкладке (текст опционален) | `a.chat-link` |
| `[[/command]]` | Подставляет команду и **отправляет** (распознаётся по ведущему `/`) | `.chat-command` |

После клика `[[текст]]` `prompt_user` содержит **точный текст** (без скобок).
`[[+текст]]` — только вставка в поле, пользователь сам решает отправлять ли.
`[[/command]]` — отправляет `/command` целиком (не через insertIntoInput, а прямым присвоением).

### 13.3 Вопросы пользователю через continue_workflow

Шаг `return_response_text` (type_id=4) с `"continue_workflow": true`:

1. Показывает `prompt_user` как ответ бота
2. Сохраняет `workflow_step_current_index` + снапшот изменённых переменных в `session.metadata`
3. **Ждёт следующего сообщения** — workflow возобновится со следующего шага

**Персистентность переменных между сообщениями:**
- Переменные, изменённые в шагах ДО `continue_workflow`, сохраняются в `workflow_variables_saved` и восстанавливаются при resume.
- Переменные запроса (`type='global'`: `prompt_user`, `user_id`, `session_uuid`, `agent_*`) в снапшот НЕ попадают — приходят заново с каждым запросом (это правильно).
- После `return_response_text` без `continue_workflow` (или `return_response_llm`) сессия завершена: следующее сообщение стартует workflow с нуля.

**Паттерн «вопрос→ответ»:**
```
Step N:   return_response_text, continue_workflow=true
          prompt_user: "Опишите идею проекта:"

Step N+1: variable_conversion
          [{variable: "project_idea", text: "%prompt_user%"}]
          ← prompt_user здесь = ответ пользователя

Step N+2: tool_invoke ...   ← использует project_idea
```

### 13.4 Команды и маршрутизация через transitions_before

`transitions_before` проверяются ДО выполнения шага → идеальны для маршрутизации по командам:

```
Step 0: return_response_text (continue_workflow=false)
        prompt_user: "%agent_greeting%"
        transitions_before:
          prompt_user == "/girl_create" → step 16
          prompt_user == "/girl_remove" → step 111
```

При запуске workflow `prompt_user` = то, что написал пользователь. Если пользователь кликнул `[[/girl_create]]` — `prompt_user` будет `/girl_create` (без скобок). Переходы сравнивают именно это значение.

**Важно:** в greeting и prompt_user команды пишутся как `[[/command]]`; значения в `transitions_before/after` (`"value": "/command"`) остаются без скобок — это то, что чип отправляет.

### 13.5 Генерация чипсов программно (list_render)

Инструмент `list_render(items, template, separator)` (`src/tool/dict/`):
- `items` — JSON-строка или список значений
- `template` — `%s` = элемент, пример: `[[%s]]`
- `separator` — разделитель, пример: ` ` (пробел между чипсами)

Результат: `list_render_{step_id}_result_str` — строка чипсов для подстановки в `prompt_user`.

**Конвейер «таблица → чипсы»:**
```
variable_conversion  → mysql_find_by(table, criteria)
                     → dict_column(rows, 'name')      ← column_name по ключу
                     → list_render(names, '[[%s]]', ' ')
                     → return_response_text(%list_render_{id}_result_str%, continue=true)
```

Пример из dating_bot: список девушек для удаления → `%agent_list_111_result_chips%`.

### 13.6 Паттерн «главное меню через greeting + chips»

Классический паттерн (dating_bot, mysql_export):

```sql
-- Agent greeting (статический, из agent.greeting):
'Привет!\n\n[[Создать проект]] [[Статус проекта]] [[/new_case]]'

-- Workflow step 0 (transitions_before маршрутизируют команду):
type: return_response_text, continue_workflow=false
prompt_user: "%agent_greeting%"
transitions_before:
  prompt_user == "Создать проект" → step 10
  prompt_user == "Статус проекта" → step 20
  prompt_user == "/new_case"      → step 30   ← [[/command]] отправляет "/new_case"
```

Другой вариант — без команд в greeting, а чипсы в первом `continue_workflow` шаге:

```sql
-- Workflow step 0: возвращает меню с чипсами и ждёт
type: return_response_text, continue_workflow=true
prompt_user: "Что хотите сделать?\n\n[[Создать проект]] [[Статус проекта]]"

-- Workflow step 1: маршрутизация по ответу
type: variable_conversion
variable_conversion: [{variable: "bot_action", text: "%prompt_user%"}]
transitions_after:
  bot_action == "Статус проекта" → step 20
  bot_action == "Создать проект" → step 10
  bot_action != "Создать проект" → step 11  ← free text → treat as idea directly
```

Третья строка (`!= "Создать проект"`) — catch-all: срабатывает только если первые два не сработали (т.к. transitions_after первый match выигрывает).
