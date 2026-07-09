# Workflow: описание функционала, нюансы, пути развития

> Составлено по результатам анализа кода: редактор (`data/uvicorn/template/admin/agent_workflow.html`,
> `agent_workflow_variable.html`), API (`src/uvicorn/routers/workflow/*`), схема БД (`migrations/0001.sql`,
> сиды `0002.sql`), движок выполнения (`src/ai/framework/agent/ai_framework_manager.py`, `src/ai/ai_workflow.py`).

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
| `agent_workflow_step_type` | Справочник 5 типов шагов (name, icon, description, metadata-схема) |
| `agent_workflow_variable` | Реестр переменных: name, **type ENUM('global','node','input','workflow')**, default, node_id, position, use_as_hint, description |
| `agent_workflow_variable_workflow` | M:N переменная ↔ workflow |
| `agent_workflow_variable_role` | M:N переменная ↔ роль (гранулярный доступ) |
| `agent` | workflow_id (FK) + workflow_variable (JSON-инициализация) |
| `session.metadata` | Персистентное состояние: `workflow_step_current_index` для continue_workflow |
| `agent_session` | История: user-prompt / response-final / tool-call / system-prompt |

## 3. Типы переменных и приоритет инициализации

Порядок сборки `workflow_variables_all` при запросе (`src/uvicorn/routers/chat/chat.py`):

1. **Базовые** — `prompt_user`, `user_id/username/email`, `agent_*`, `companion_*`, `session_uuid`, `workflow_id`, `node_id`.
2. **Из агента** — `agent.workflow_variable` (JSON).
3. **Из запроса** — `request.variables` (клиент может передать переменные).
4. **Переменные ноды** (`type='node'`) — рендерятся с учетом уже собранных (могут ссылаться на них: `girl_title` default=`%prompt_user%`).
5. **Переменные workflow** (`type='workflow'`) — default-значения, добавляются только если ключа еще нет.
6. **Валидация global** — все `type='global'` обязаны присутствовать, иначе HTTP 400.
7. **Валидация input** — все `type='input'` обязаны присутствовать, иначе HTTP 400. **Это готовый контракт входа для будущих sub-workflow.**

Рендеринг: `ai_workflow_variables_render()` (`src/ai/ai_workflow.py:43`) — рекурсивная подстановка `%name%`
в строки/dict/list. **Нюанс — умная замена типов**: если строка состоит только из плейсхолдера (`"%id%"`),
возвращается исходное значение с типом (int/list/bool), а не строка.

## 4. Типы шагов (семантика движка)

Движок: `_framework_workflow_run()` (`src/ai/framework/agent/ai_framework_manager.py:62-417`).
Цикл: `while step_index < steps_count`, на каждой итерации metadata шага прогоняется через рендер переменных.

| Тип | Что делает | Ключи metadata |
|---|---|---|
| `return_response_llm` ↩L | Отправляет контекст в LLM, результат — финальный ответ пользователю. **Завершает workflow.** | `prompt_user` |
| `llm_to_json` 🧠 | Запрос к LLM с требованием JSON; парсит ответ (`_json_str_clean` вырезает JSON из текста), проверяет наличие всех ожидаемых ключей, кладет их в переменные. До 3 повторов при ошибке парсинга. | `llm_to_json_variable: [{variable, text}]`, `prompt_user` |
| `tool_invoke` ⚙️ | Вызывает python-инструмент. Аргументы собираются из переменных по `inputs_map` (arg → имя переменной). Результат-dict раскладывается в переменные `{tool_name}_result_{key}`; скаляр — `{tool_name}_result_{typename}` (str/int/bool/list/float). Пишет tool-call в `agent_session`. | `tool_invoke: {tool_name, inputs_map, outputs_map}` |
| `return_response_text` ↩T | Возвращает текст-шаблон (после рендера переменных). **Завершает текущий запрос**; при `continue_workflow=true` сохраняет индекс следующего шага в `session.metadata` — следующий запрос пользователя продолжит workflow с этого места (диалоговые сценарии-«визарды»). | `prompt_user`, `continue_workflow` |
| `variable_conversion` ❴❵ | Переопределяет переменные значениями-шаблонами (рендер уже произошел). Используется для склейки JSON-строк, преобразования результатов инструментов. | `variable_conversion: [{variable, text}]` |

## 5. Переходы (transitions)

В metadata каждого шага: `transitions_before` (проверяются ДО выполнения шага) и `transitions_after`
(ПОСЛЕ, уже после инкремента индекса). Формат: `{variable, operator, value, step_id}`.
Операторы: `==`, `!=`, `>`, `<`, `contains`. Первый сработавший переход выигрывает, движок прыгает на шаг
с `step_id` (маппинг id → индекс).

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
приходит через `on_complete`-callback (`execute_llm_step`, строки 132-159).

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
- **`/admin/agent_workflow_variable`** — реестр переменных по нодам: name, node, description, роли,
  привязка к workflow, default, use_as_hint (переменные-«подсказки» видны ниже по position), drag-drop
  порядка. Field-policy: не-админ читает ограниченный набор полей и пишет только `default`.

## 8. Известные баги и тонкости (найдено при анализе)

1. **[КРИТИЧНО] Числовые сравнения в переходах** — `>` и `<` сравнивают строки лексикографически
   (`str(10) > str(5)` → False). `ai_framework_manager.py:108-114, 398-404`. Нужен try-float.
2. **KeyError при отсутствии переменной в переходе** — `model.workflow_variables[variable_name]` без
   `.get()`: опечатка в имени переменной валит весь workflow. Строки 106, 259, 396.
3. **Жадная регулярка в `_json_str_clean`** — `(\{.*})` захватит от первой `{` до последней `}`;
   на ответе LLM с двумя JSON-блоками парсинг сломается. Строка ~450.
4. **Потенциальный deadlock в `execute_llm_step`** — если `on_complete` не будет вызван consumer'ом
   очереди, `await step_future` повиснет (спасает только 60-сек timeout запроса).
5. **Дубликат `input_values_set()`** в task-фреймворке (`py_modules/ai/framework/task/ai_framework_manager.py:106-107`).
6. Результаты инструментов сериализуются в строки — `%tool_result%`-переменная со списком после
   вставки в шаблон становится JSON-строкой; «умная замена типов» помогает только когда плейсхолдер — вся строка.
7. Колонка `subflow` в `agent_workflow` есть в схеме и уже фильтруется в UI переменных (subflow=0), но
   движком не используется.
8. Переменные с одинаковыми именами: `inputs_map` в `tool_invoke` хранится и как `metadata.tool_invoke.inputs_map`
   (движок) — фронтовые обработчики должны учитывать вложенность.

## 9. Пути оптимизации и улучшения

### 9.1 Ближние (устранение рисков)
- Исправить баги §8 (1-4) — прежде всего числовые операторы и `.get()` в переходах.
- Добавить операторы переходов: `>=`, `<=`, `exists`, `empty`, `not_contains`, `regex`.
- Валидация workflow при сохранении: ссылки переходов на существующие шаги, наличие используемых
  переменных, достижимость шагов (сейчас можно сохранить битый граф).
- Журнал выполнения (execution trace): писать в `agent_session` или отдельную таблицу каждый шаг
  с входом/выходом — сейчас отладка только по логам.
- Персистентность переменных при `continue_workflow`: сохранять снапшот `workflow_variables` в
  `session.metadata` рядом с индексом шага.

### 9.2 Sub-workflow (главное направление)
Цель: workflow вызывает другой workflow как шаг, передает входящие переменные, получает результат, продолжает.

Инфраструктура уже готова наполовину:
- **Контракт входа** — переменные `type='input'` (+ валидация присутствия уже реализована в chat.py);
- **Флаг `subflow`** в `agent_workflow` — помечать переиспользуемые под-процессы, скрывать их из
  списков агентских workflow;
- **Конвенция результата инструментов** `{name}_result_{key}` — естественно расширяется на
  `{workflow_name}_result_{key}`.

Предлагаемый дизайн — новый тип шага `workflow_invoke` (id=6):
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
Семантика движка:
1. Загрузить шаги и переменные дочернего workflow (тот же SQL, что в chat.py).
2. Собрать **изолированный** scope дочернего: базовые переменные + значения из `inputs_map`
   (родительская переменная → input-переменная ребенка) + default'ы ребенка; провалидировать `type='input'`.
3. Рекурсивно выполнить цикл шагов (вынести тело `_framework_workflow_run` в переиспользуемую
   функцию, принимающую scope и steps; future заменить на возврат значения).
4. Результат ребенка: значение `return_response_text`/`return_response_llm` кладется в
   `{workflow_name}_result_str`; дополнительно по `outputs_map` — выбранные переменные дочернего
   scope копируются в родительские.
5. Ограничения: max глубина вложенности (например 5), детект циклов по стеку workflow_id,
   таймаут на дочерний вызов, `continue_workflow` внутри sub-workflow запретить (или прокидывать
   стек индексов в session.metadata).
6. Требуется контракт выхода: рекомендуемый вариант — добавить `type='output'` в ENUM переменных,
   чтобы редактор мог показывать, что именно возвращает под-процесс.

UI: конфигуратор шага по образцу `widget_tool_invoke` — селект workflow (subflow=1), автоматическая
загрузка его input-переменных для inputs_map и output-переменных для outputs_map.

### 9.3 Дальнейшее развитие
- **Версионирование workflow** (draft/published + копия шагов) — сейчас правка ломает живых агентов мгновенно.
- **Типизация переменных** (str/int/json/bool + поле `pattern` для regex-валидации — колонку в БД добавить, идея уже витает в field-policy).
- **Обработка ошибок как переход** — `on_error: step_id` в metadata шага вместо падения всего workflow.
- **Параллельные шаги** — группа tool_invoke без взаимных зависимостей (asyncio.gather).
- **Dry-run из админки** — кнопка «Тест» с ручными значениями input-переменных и трейсом по шагам (без записи в сессии).
- **Визуализация графа** — переходы уже фактически образуют граф; отрисовка (mermaid/канвас) сильно упростит отладку сложных workflow вроде dating_talk (17+ шагов).
- **Кэш загрузки** шагов/переменных workflow (сейчас 3-4 SQL-запроса на каждый chat/ask).

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
