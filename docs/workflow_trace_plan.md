# План: журнал выполнения workflow (execution trace)

Цель: полная наблюдаемость запуска workflow — по каждому шагу видны вход, выход, длительность,
ошибки и сработавшие переходы; по запуску целиком — маршрут от начала до конца, включая
вложенные sub-workflow. Отдельная таблица (не `agent_session`) + отдельная админ-страница.

## 1. Модель данных (миграция 0001.sql)

Две таблицы вместо одной: «запуск» и «шаги запуска» — иначе шапку запуска (статус, длительность,
итог) пришлось бы дублировать в каждой строке шага.

### `agent_workflow_run` — один запуск workflow
| Колонка | Тип | Назначение |
|---|---|---|
| id | INT PK | |
| run_uuid | CHAR(36) UNIQUE | идентификатор запуска |
| parent_run_id | INT NULL FK→self | вложенность: запуск sub-workflow ссылается на родителя |
| parent_step_id | INT NULL | id шага workflow_invoke, породившего дочерний запуск |
| depth | INT | глубина вложенности (0 — верхний уровень) |
| workflow_id | INT FK | какой workflow выполнялся |
| agent_id, user_id | INT | контекст |
| session_uuid, request_uuid | CHAR(36) | связь с `agent_session` (историей чата) |
| prompt_user | LONGTEXT | входное сообщение |
| result | LONGTEXT NULL | финальный ответ (return_response_*) |
| status | ENUM('running','success','error') | |
| error | LONGTEXT NULL | текст исключения |
| started_at, finished_at | DATETIME(3) | |
| duration_ms | INT NULL | |

Индексы: run_uuid (unique), (workflow_id, started_at), session_uuid, parent_run_id.

### `agent_workflow_run_step` — выполненный шаг
| Колонка | Тип | Назначение |
|---|---|---|
| id | INT PK | |
| run_id | INT FK→agent_workflow_run ON DELETE CASCADE | |
| exec_index | INT | порядковый номер ВЫПОЛНЕНИЯ (не position: переходы/петли) |
| step_id | INT NULL | id шага (NULL, если шаг потом удалили) |
| step_title, step_type | CHAR | снапшот на момент запуска |
| metadata_rendered | LONGTEXT | **вход**: metadata шага ПОСЛЕ рендера %переменных% (промпт, inputs_map со значениями) |
| variables_changed | LONGTEXT | **выход**: JSON только изменённых/новых переменных шага |
| output | LONGTEXT NULL | сырой ответ LLM / результат инструмента / результат sub-workflow |
| transition | LONGTEXT NULL | сработавший переход: `{"phase":"before/after","condition":"%x% == 1","to_step_id":N}` |
| status | ENUM('success','error','retry') | retry — неудачная попытка llm_to_json |
| error | LONGTEXT NULL | |
| started_at, finished_at, duration_ms | | |

Снапшот-стратегия: полный словарь переменных пишется один раз в шапку запуска (в
`agent_workflow_run` можно добавить `variables_start LONGTEXT`), дальше — только диффы по шагам.
Состояние на любом шаге восстанавливается накатом диффов; объём БД не взрывается.
Значения длиннее ~20 КБ обрезаются с пометкой `...[truncated]`.

## 2. Запись из движка (`ai_framework_manager.py`)

1. Модуль `src/ai/ai_workflow_trace.py`: `trace_run_start/finish`, `trace_step` — вся запись
   в одном месте; каждая функция обёрнута в try/except с logger_info — **сбой трейса никогда
   не роняет workflow**.
2. `_framework_workflow_run` (обёртка): создаёт run (status=running), по завершении —
   finish (result/error, duration).
3. `_workflow_steps_run`: принимает `run_id`; на каждой итерации:
   - перед выполнением: снимок `step_meta` после рендера + отметка времени;
   - `dict(variables)` до шага → после шага дифф по ключам (новые + изменённые);
   - запись шага со статусом; ошибки шага пишутся до re-raise; retry llm_to_json — отдельной
     строкой со status='retry';
   - сработавший переход (before/after) — в поле `transition` строки шага.
4. Ветка `workflow_invoke`: дочерний запуск с `parent_run_id`/`parent_step_id`/`depth` —
   на странице собирается дерево.
5. Включение: env-флаг `WORKFLOW_TRACE_ENABLED` (config), по умолчанию включён в dev.
   Проверка одна, в начале функций трейса.

## 3. API (`src/uvicorn/routers/workflow/workflow_trace.py`)

| Эндпоинт | Назначение |
|---|---|
| `GET /workflow_trace/run/list?workflow_id&agent_id&user_id&status&page&limit` | список запусков (только depth=0), пагинация как у fact.html |
| `GET /workflow_trace/run/{run_uuid}` | запуск + шаги + дочерние запуски рекурсивно (дерево одним ответом) |
| `DELETE /workflow_trace/run/{run_uuid}` | ручное удаление запуска |

Права: `WORKFLOW_TRACE_VIEW` в `AuthPermission` (+ в набор роли user — только просмотр).

## 4. Страница `/admin/workflow_trace`

Паттерн session.html (фильтры + список + деталь):

- **Фильтры сверху**: workflow, агент, пользователь, статус, дата.
- **Слева — список запусков**: карточки «время · workflow · агент · статус-бейдж
  (✅/❌/⏳) · длительность · N шагов». Пагинация.
- **Справа — деталь запуска**:
  - шапка: prompt_user → итоговый ответ, суммарное время, статус/ошибка;
  - **таймлайн шагов**: строка = иконка типа + exec_index + название + длительность + статус;
    раскрытие (аккордеон) показывает: вход (metadata_rendered, pretty-print JSON со
    сворачиванием), выход (variables_changed), output (LLM/tool), сработавший переход
    («🔀 %x% == 1 → шаг N»);
  - шаг `workflow_invoke` разворачивается во **вложенный таймлайн дочернего запуска**
    (рекурсивно, с отступом);
  - клик по названию шага → открыть его в редакторе workflow.
- Пункт меню: base.html, раздел «📜 Logs» → «Trace workflow».
- JS: новый модуль либо страница по паттерну ES-module (state/api/notification переиспользуются).

## 5. Обслуживание

- Крон-чистка `src/cronjob/workflow/trace_cleanup.py`: удалять запуски старше N дней
  (config `WORKFLOW_TRACE_TTL_DAYS`, default 14); каскад удалит шаги.
- В сиды таблицы не входят (журнал), только DDL в 0001.sql + DROP-секция.

## 6. Этапы (каждый проверяем отдельно)

1. **DDL + запись из движка** (~150 строк движок+трейс-модуль): после этого журнал уже
   можно смотреть SQL-ом/phpMyAdmin — самое ценное появляется сразу.
2. **API + страница**: список запусков и таймлайн шагов без вложенности.
3. **Дерево sub-workflow + переходы + retry-строки** — полная картина маршрута.
4. **Полировка**: крон-чистка, обрезка больших значений, пункт меню, права.
5. **Опционально (потом)**: подсветка пройденного маршрута на графе Graph-режима
   (trace overlay поверх mermaid — пройденные рёбра зелёные, упавший шаг красный);
   кнопка «Повторить запуск» (replay с теми же входными переменными).

## Оценка

Движок+модуль трейса ~150 строк, миграция ~45, роутер ~120, страница ~550-650 (по образцу
session.html), крон ~40. Этап 1 — самый важный и самый маленький.
