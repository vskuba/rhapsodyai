# Task — страница задач и конвейер агентов

Модуль задач: админ-страница `/admin/task`, REST API и конвейер, в котором задачу
последовательно ведут Manager → человек → Developer → QA.

**Текущий статус конвейера: заглушки.** Роли не обращаются к LLM и не меняют код —
работает и проверяется только механика состояний. Шов для настоящих исполнителей — §7.

---

## 1. Две независимые оси состояния

Главное, что нужно понять про этот модуль: у задачи **два состояния, а не одно**.

| Поле | Что означает | Кто меняет |
|------|--------------|------------|
| `task.status` | человеческий kanban-статус | человек через `/admin/task` |
| `task.pipeline_state` | стадия автоматики; `NULL` = вне конвейера | оркестратор + кнопки утверждения |

Смешивать их нельзя: на `status` завязаны фильтры, сортировка и цвета админки.
Задача входит в конвейер **только по явному действию человека** (opt-in) — созданная
обычным путём задача имеет `pipeline_state = NULL`, и агенты её не трогают.

`task.status`: `pending` · `queued` · `active` · `done` · `blocked` · `cancelled`

---

## 2. Страница `/admin/task`

Шаблон: `data/uvicorn/template/admin/project/task.html` (extends `base.html`).
Маршрут: `src/uvicorn/routers/dashboard.py` → `task_page()`.

### Панель инструментов

Заголовок, счётчик отфильтрованных задач, выбор проекта («Все проекты» = `project_id 0`),
поиск, чипы-фильтры по статусам с количеством, кнопка «+ Добавить».

Поиск и чипы применяются на клиенте в `visibleTasks()` — по названию, описанию,
отчёту и имени проекта.

### Таблица

Восемь колонок (`data-col`): `id` · `status` · `title` · `desc` · `project` · `goals` · `date` · `act`.

- **Порядок колонок** — drag-and-drop за заголовок, `localStorage.task_col_order_v1`
- **Ширины** — перетаскиванием разделителя, в процентах, `localStorage.task_col_pct_v2`

> При изменении набора колонок **обязательно поднять версию ключа** `task_col_pct_v2`,
> иначе применятся сохранённые ширины от старой раскладки и вёрстка поедет.

Слева у каждой строки — цветная полоса статуса (`--row-accent`, см. `STATUS_ACCENT`).
Строка кликабельна: раскрывается инлайн-редактор.

### Цели

JSON-массив `[{text, done}]` в колонке `task.goals`. Редактируются в двух местах:

- **прямо в таблице** — чекбокс, ✏ и ✕ (`inlineToggleGoal` / `inlineEditGoal` /
  `inlineDeleteGoal`), сохраняются сразу, без кнопки «Сохранить»; над списком —
  прогресс `2/3` с полоской
- **в раскрытой строке** — секция «Цели» с `_goalsCache`

### Раскрытая строка

Название, статус, описание (с голосовым вводом), цели, блок «Конвейер» (§6), отчёт.

> Поле отчёта имеет id `trep-{id}`, **не** `tr-{id}` — последний занят самим `<tr>`
> строки, и `getElementById` возвращал бы элемент таблицы вместо textarea.

### Голосовой ввод и ИИ

- 🎤 → `POST /chat/voice`, распознанный текст дописывается в описание
- «ИИ помощник» → `POST /task/ai-generate`: из описания получаются название,
  развёрнутое описание и список целей (цели применяются после создания задачи)

---

## 3. Машина состояний конвейера

```
task.pipeline_state:

  NULL --(«В конвейер»)--> new --> planning --> pending_approval
                                                       |
                                 («Отклонить») <-------+-------> («Утвердить»)
                                        |                              |
                                      NULL                         approved
                                                                       |
                                                                     split --> done | failed

task_subtask.state:

  planned --> developing --> qa_pending --> done
                   ^                 |
                   |                 +--> failed_qa --> повтор, пока attempt_count < MAX_ATTEMPTS
                   +-----------------'                        |
                                                              +--> blocked (лимит исчерпан)
```

Задача уходит в `done`, когда все подзадачи терминальны; если хоть одна `blocked` — в `failed`.

---

## 4. Транзакционный воркер

Оркестратор **не крутит бесконечный цикл**. Cronicle раз в N минут дёргает его,
он делает ровно одно действие и выходит.

**Кронджоб на весь конвейер ровно один** — `src/cronjob/task_orchestrator.py`. Отдельных
джобов на Manager, Developer и QA нет: один тик централизованно смотрит все стадии сразу
и выполняет первое подошедшее действие (порядок проверок — в `task_pipeline._action_next`).
Логика лежит в `src/project/task/` и кронджобом не является (правило 4.3 в
`architecture_rules.md`).

```
Cronicle (:3012) --POST /cronjob--> uvicorn --subprocess--> src/cronjob/task_orchestrator.py
                                                                     |
                                                            src/project/task/task_pipeline.py
```

```bash
curl -s -X POST localhost:8011/cronjob -H 'Content-Type: application/json' \
  -d '{"cronjob_path":"src/cronjob/task_orchestrator.py","metadata":{"max_actions":1},"timeout":300}'
```

`metadata.max_actions` — сколько действий за запуск (по умолчанию 1). В stdout уходит
JSON `{"actions": N, "reclaimed": N, "steps": [...]}` — его забирает исполнитель кронджобов.

> Событие в Cronicle заводится вручную через UI и **своё на каждой инсталляции** —
> на проде придётся создать отдельно.

### Захват работы

Запуски крона могут накладываться, поэтому захват — условный `UPDATE` с проверкой
`rowcount`, а не `SELECT ... FOR UPDATE`:

```sql
UPDATE task SET pipeline_state = 'planning', pipeline_locked_at = NOW(), pipeline_locked_by = %s
 WHERE id = %s AND pipeline_state = 'new'
```

`rowcount == 0` → строку увёл параллельный воркер, тихо пропускаем.

Если воркер умрёт посреди перехода, строка залипнет в переходном состоянии
(`planning` / `developing`). `task_claim_locks_reclaim()` в начале каждого тика
возвращает такие строки в работу по `locked_at < NOW() - INTERVAL LOCK_TIMEOUT_SEC SECOND`.

Константы: `MAX_ATTEMPTS = 3` (`task_pipeline.py`), `LOCK_TIMEOUT_SEC = 900` (`task_claim.py`).

---

## 5. Схема БД

`task` — глобальная задача:

| Колонка | Назначение |
|---------|-----------|
| `status` | человеческий kanban-статус |
| `goals` | JSON `[{text, done}]` |
| `report` | отчёт о выполненных работах |
| `position` | порядок внутри проекта |
| `pipeline_state` | стадия конвейера, `NULL` = вне его |
| `pipeline_plan` | JSON `{plan_text, subtasks}` от Manager |
| `pipeline_error` | причина `failed` |
| `pipeline_locked_at` / `pipeline_locked_by` | оптимистичная блокировка |

`task_subtask` — единица работы Developer/QA: `state`, `attempt_count`, `last_error`,
`locked_at`/`locked_by`, FK на `task` с `ON DELETE CASCADE`.

`task_attempt` — история попыток: `attempt_no`, `role`, `status`, `output`, `error`,
`duration_ms`, FK на `task_subtask` с `ON DELETE CASCADE`.

Обе новые таблицы — runtime-данные, **в seed не добавлять**. Схема живёт только в
`migrations/0001.sql`.

---

## 6. API

| Метод | Путь | Права | Действие |
|-------|------|-------|----------|
| `GET` | `/tasks` | `PLANNING_VIEW` | все задачи |
| `GET` | `/tasks/{project_id}` | `PLANNING_VIEW` | задачи проекта |
| `POST` | `/tasks/{project_id}` | `PLANNING_CREATE` | создать |
| `PUT` | `/task/{id}` | `PLANNING_CREATE` | обновить (частично) |
| `DELETE` | `/task/{id}` | `PLANNING_CREATE` | удалить |
| `POST` | `/task/ai-generate` | `PLANNING_CREATE` | сгенерировать название/описание/цели |
| `GET` | `/task/{id}/pipeline` | `PLANNING_VIEW` | состояние + подзадачи + попытки |
| `POST` | `/task/{id}/pipeline/start` | `PLANNING_UPDATE` | `NULL` → `new` |
| `POST` | `/task/{id}/pipeline/approve` | `PLANNING_UPDATE` | `pending_approval` → `approved` |
| `POST` | `/task/{id}/pipeline/reject` | `PLANNING_UPDATE` | `pending_approval` → `NULL` |

CRUD — `project_task.py`, конвейер — `project_task_pipeline.py`. Каждый переход сверяет
текущее состояние прямо в `UPDATE`; несовпадение → `409`, чтобы двойной клик не
проскочил гонку.

---

## 7. Правила для ролей

Роли живут в `src/project/task/task_agent.py` — это **единственное место**, которое надо
заменить, чтобы конвейер заработал по-настоящему. Оркестратор читает только
документированные ключи возврата и ничего не знает о том, как результат получен.

```python
async def task_agent_manager_plan(task) -> {'plan_text': str, 'subtasks': [{'title','description'}]}
async def task_agent_developer_run(task, subtask, last_error='') -> {'ok': bool, 'output': str, 'error': str}
async def task_agent_qa_run(task, subtask) -> {'ok': bool, 'output': str, 'error': str}
```

Общее для всех трёх: исключение внутри роли — не падение тика. Оркестратор ловит его,
пишет строку в `task_attempt` со `status='error'` и двигает состояние по ветке провала.

### Manager

**Отвечает за:** разложить глобальную задачу на план и список подзадач.

- Возвращает **и** человекочитаемый `plan_text`, **и** машинный `subtasks` — первое идёт
  человеку на утверждение, второе после утверждения материализуется в `task_subtask`
- Пустой `subtasks` = провал: задача уходит в `failed`, а не в бесконечное планирование
- Подзадача должна быть достаточно мелкой, чтобы Developer закрыл её за один заход, и
  достаточно самостоятельной, чтобы QA мог проверить её отдельно
- **Не материализует подзадачи сам** — только после утверждения человеком
- Ориентир по реализации: `project_task_ai_generate` в `project_task.py` — там весь путь
  `AgentRepository` → `ai_llm_node_get` → `ai_workflow_load` → `framework_model_create`
  → `framework_workflow_run` → `await future`

### Developer

**Отвечает за:** выполнить одну подзадачу.

- Получает `last_error` — непустой, если предыдущий круг завалил QA. Обязан его учесть,
  а не начинать с нуля
- **Коммит только в feature-ветку и PR.** Пуш в `main` и самостоятельный merge запрещены —
  это решение, а не рекомендация по умолчанию
- Работает над одной подзадачей за раз; `attempt_count` растёт по кругам Developer→QA,
  лимит `MAX_ATTEMPTS = 3`
- При исчерпании лимита подзадача уходит в `blocked` — дальше её никто не берёт,
  нужен человек
- Исполнитель ещё не выбран: агент внутри приложения либо внешняя сессия Claude Code.
  Сигнатура рассчитана на оба варианта

### QA

**Отвечает за:** проверить результат подзадачи.

- **Не исполняет произвольный сгенерированный код.** Только прогон существующего набора
  тестов — `pytest tests/`. Это осознанное ограничение: исполнение LLM-авторского кода в
  процессе с доступом к `.env`, БД и сети — главный риск схемы, и без песочницы этот шаг
  не открывается
- Требует поднятый uvicorn на :8011 — то есть **QA не может перезапускать сервис, который
  сам же тестирует**. Изменения в `.py`, требующие рестарта, нужно проводить отдельным
  порядком
- Возвращает `ok=False` с внятным `error` — он попадёт в `subtask.last_error` и дальше в
  `last_error` следующего вызова Developer. Полный вывод кладётся в `output` и оседает
  в `task_attempt`
- На проде QA **строго наблюдательный**: не правит код, не перезапускает сервисы, не
  трогает состояние — только пишет отчёты и заводит задачи

---

## 8. Файлы

| Файл | Роль |
|------|------|
| `data/uvicorn/template/admin/project/task.html` | страница целиком (разметка, CSS, JS) |
| `src/uvicorn/routers/dashboard.py` | HTML-маршрут `/admin/task` |
| `src/uvicorn/routers/project/project_task.py` | CRUD задач |
| `src/uvicorn/routers/project/project_task_pipeline.py` | эндпоинты конвейера |
| `src/cronjob/task_orchestrator.py` | точка входа Cronicle, один тик |
| `src/project/task/task_pipeline.py` | машина состояний |
| `src/project/task/task_claim.py` | захват работы, реклейм блокировок |
| `src/project/task/task_state.py` | запись состояний и истории попыток |
| `src/project/task/task_plan.py` | формат плана Manager |
| `src/project/task/task_agent.py` | **шов**: Manager / Developer / QA |
| `tests/test_task_pipeline.py` | тесты переходов и гонки |
| `migrations/0001.sql` | `task`, `task_subtask`, `task_attempt` |

---

## 9. Проверка

```bash
.venv/bin/python3 -m pytest tests/test_task_pipeline.py -v
```

Тесты детерминированы — заглушки не ходят в LLM. Покрыто: opt-in вход, конфликт
повторного старта, план без подзадач до утверждения, отклонение, полный проход до
`done`, параллельные тики (задачу забирает ровно один воркер).

Ручной прогон по шагам — дёргать `/cronjob` (§4) и смотреть, как состояние двигается
на один шаг за вызов.

---

## 10. Известные ограничения

- **`POST /cronjob` без авторизации** (`src/uvicorn/routers/cronjob/cronjob.py`): любой,
  кто дотянется до порта, запустит любой файл из `src/cronjob/`. Было и раньше, но теперь
  за этим эндпоинтом стоит джоб, меняющий состояние задач
- `task.project_id` без FK — «Все проекты» использует `project_id = 0`
- Порядок шагов в тике breadth-first: Developer разбирает все `planned`, прежде чем дойдёт
  очередь до QA. На корректность не влияет, но подзадачи завершаются пачками
