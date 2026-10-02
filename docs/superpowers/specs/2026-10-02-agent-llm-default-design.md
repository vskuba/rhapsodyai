# LLM default агента: колонка `agent.llm_id`, select на `/admin/agent` и pin в выборе модели

> Спека от 2026-10-02. У агента появляется своя модель по умолчанию: список в select
> «LLM default» — модели текущей ноды, выбранный номер живёт в `agent.llm_id`, а
> движок при запросе к агенту ставит эту модель первой в цепочку. Пусто — работает
> как сейчас, по приоритету ноды.

## 1. Зачем

Сейчас модель агенту не принадлежит: её берёт нода. Все точки входа (`/chat/ask`,
телеграм-бот, cron-задачи, роли конвейера) зовут `ai_llm_node_get(node_id)` и
кладут список в заявку, а движок берёт первую по приоритету ноды:

```sql
ORDER BY nl.rate_limit_at ASC, nl.position ASC   -- ai_llm_node_get()
framework_model.entity_llm_current = entities_llm[0]  -- framework_model_create()
```

Поэтому одному агенту из всех агентов ноды свою модель не поставить: захочешь
выделить — заводи отдельную ноду. Колонка `agent.llm_id` даёт точке входа сказать
«этому агенту — вот эта модель», не трогая ноду и не размножая записи.

## 2. Что меняется по именам

| Что | Имя | Где |
|---|---|---|
| Колонка | `agent.llm_id INT NULL DEFAULT NULL` | миграция `20261002120000_agent_llm_default.sql` |
| Точка создания | `llm_id` в теле `POST /agent` | `src/uvicorn/routers/agent/agent.py` |
| Точка правки | `llm_id` в merge и `UPDATE` у `PUT /agent/{id}` | там же |
| Select | «LLM default» в левой колонке формы, под «Workflow» | `data/uvicorn/template/admin/agent.html` |
| Pin в движке | сортировка `entities_llm` перед выбором `entity_llm_current` | `src/ai/ai_llm.py::ai_llm_pin`, зовёт `framework_model_create` |
| Тесты | `tests/test_agent_llm_default.py` | по образцу `test_agent_variable.py` |
| Док | `agent.md` (поле), `llm.md` (цепочка вызова и «Выбор LLM») | `.claude/docs/` |

## 3. База

Миграция — новым файлом (начальная схема заморожена), тем же приёмом, что
`20260911180339_agent_variable.sql`: `information_schema.COLUMNS` + `PREPARE`,
второй прогон — «колонка уже есть».

```sql
ADD COLUMN `llm_id` INT NULL DEFAULT NULL
    COMMENT 'Модель по умолчанию для этого агента; NULL — брать по приоритету ноды'
```

- **`NULL` и без умолчания** — у всех существующих агентов пина нет, они обязаны
  вести себя ровно как сегодня.
- **FK `ag_llm` (`llm`(`id`) ON DELETE SET NULL)** — удалённая из справочника
  модель оставляет агента с `NULL`, то есть возвращает его к поведению ноды, а не
  вешает битую ссылку. Проверяется по `information_schema.TABLE_CONSTRAINTS`
  тем же условием.

`GET /agent/{id}` и `/agent/list` читают строку целиком (`repo.find` → `SELECT *`),
поэтому поле наружу выходит само — отдельной точки не нужно.

## 4. Движок: выбор LLM, когда приходит запрос на агента

Одно место на все точки входа: `framework_model_create()` между двумя существующими
строками (`entities_llm` уже в модели, `entity_llm_current` ещё не выбран) зовёт
`ai_llm_pin()` — сортировка живёт в домене LLM, одним паттерном с соседней
`ai_llm_filter_by_type()`:

```python
# src/ai/ai_llm.py — пин поверх порядка ноды: модель первой, остальное как было
def ai_llm_pin(llm_list: list[dict], llm_id: int | None, agent_name: str = '') -> list[dict]:
    if not llm_id:
        return llm_list
    if any(llm.get('id') == llm_id for llm in llm_list):
        pinned = sorted(llm_list, key=lambda llm: llm.get('id') != llm_id)
        logger_info(f"📌 LLM агента '{agent_name}' запинена: {pinned[0].get('name')} (agent.llm_id)")
        return pinned
    logger_info(f"⚠️ agent.llm_id={llm_id} агента '{agent_name}' нет среди моделей ноды — берём порядок ноды")
    return llm_list

# src/ai/framework/agent/ai_framework_manager.py — вызов из framework_model_create()
framework_model.entities_llm = ai_llm_pin(
    metadata.get('entities_llm', []), entity_agent.get('llm_id'), entity_agent.get('name', ''))
```

Почему здесь, а не в вызывающих: `entity_agent` и `entities_llm` сходятся уже
в этой точке, а зовут её двадцать мест (`chat.py`, `telegram_bot.py`, `task_agent_*`,
`planning_phase.py`, …). Править каждый — размазать один функционал, что запрещено
правилом инкапсуляции.

Что из этого следует по существующим механизмам — трогать их не нужно:

- `entity_llm_current = entities_llm[0]` (следующая строка той же функции) —
  уже пин; шапка трассы, `ai_session_message_add(llm_id=…)` и журнал `llm_request`
  видят пин как есть.
- Фоллбэк при 429/503 (`ai_framework.py:205`) идёт по списку за пин-моделью:
  пин — первым, остальная нода остаётся подстраховкой. Так и принято
  (§8.1): пин + фоллбэк по ноде, а не только пин.
- Диспетчер параллельных слотов (`ai_thread.py:127`) берёт первую свободную из
  того же списка — при `llm_parallel_per_agent_max > 1` второй слот уйдёт на
  следующую модель ноды, как и сейчас.
- Per-step переопределение (`llm_input_type`/`llm_output_type` у шага) фильтрует
  список и после пина — порядок внутри отфильтрованного сохраняется, шаг с
  `output_type='image'` по-прежнему зовёт image-модель.

## 5. API (`src/uvicorn/routers/agent/agent.py`)

- `POST /agent`: в словарь `repo.add({...})` добавить `"llm_id": data.get('llm_id')`.
- `PUT /agent/{id}`: в `merged_data` — `"llm_id": data.get('llm_id', current_agent.get('llm_id'))`,
  в `UPDATE ... SET` — `llm_id = %s`. Частичное обновление, как у соседей: не
  прислали поле — значение остаётся; прислали `null` — пишем.
- `POST /agent/create` (дорожка по именам для DatingAi) **не трогаем**: служебным
  клиентам пин не нужен, а раз в колонке NULL — их агенты живут по ноде.

## 6. Страница `/admin/agent`

По образцу `node.html` (там список моделей уже есть):

1. В `initAgentsManager` добавить `getData('/llm/list')` в `Promise.all` — карта
   `id → name` для подписей опций.
2. При выборе ноды (и при открытии агента) — `getData('/node/{nodeId}')`: `llm_ids`
   приходят уже в порядке ноды (`rate_limit_at, position`); карта кэшируется в
   `Map`, второй раз тот же узел не тянется. «Вне ноды» (node_id NULL) — список
   catchall-ноды: тот же `ai_llm_node_get` и так мержит пин с ней.
3. Опции select: «Нет» (значение пустое → `null`) + модели эффективной ноды
   (`llm.name`, как в чек-листах страницы «Ноды»). «Нет» — один из доступных
   вариантов, он означает «пина нет, берём по приоритету ноды».
4. `selectAgentForEdit`: `'llm_id': agent.llm_id || ''` в `fields`. Пина, которого
   нет в списке ноды, select не показывает — стоит «Нет» (решение Хозяина, §8.2),
   и при ближайшем сохранении значение уйдёт в базу как `null`.
5. `saveAgentConfig`: в payload — `llm_id: document.getElementById('llm_id').value || null`.
6. Смена ноды в форме (`node_id` change) — перелистать опции select под новую ноду;
   пин, которого в новой ноде нет, не подсвечивается — стоит «Нет», сохранение
   обнулит значение (тот же случай, что и предупреждение движка в §4).

## 7. Тесты

`tests/test_agent_llm_default.py`, метка `ai`, по образцу `test_agent_variable.py`
(HTTP на стенд + вызов функций напрямую, живая модель не нужна):

1. `POST /agent` с `llm_id` → `GET /agent/{id}` вернул тот же `llm_id`.
2. `PUT` без поля — значение осталось; `PUT` с `null` — очистилось.
3. `framework_model_create` с `llm_id` — `entity_llm_current` есть пин-модель, даже
   когда по порядку ноды она была не первой; без `llm_id` — первая по ноде (как было).
4. Пин вне списка ноды — поведение как сейчас + предупреждение в журнале.

`tests_llm/` не трогаем: workflow не менялся.

## 8. Принятые решения Хозяина

1. **Фоллбэк при пине — есть.** Пин первым, нода под ним: при 429/503 агент
   уезжает на соседнюю модель ноды, как система ходит сейчас. Не «только пин».
2. **Пин вне списка ноды в select не показывается**: стоит опция «Нет» — один из
   доступных вариантов, значение `null`; при сохранении она же уходит в базу.

## 9. Что здесь не делать

- Не менять `POST /agent/create` и дорожку «workflow заводит сам» — пин там не
  просили, NULL их и так устраивает.
- Не править `ai_llm_node_get` и порядок `node_llm`: пин — над списком, а не вместо.
- Не заводить отдельную точку «получить LLM ноды»: `/node/{id}` отдаёт `llm_ids`
  и `/llm/list` — имена, вторая копия уже есть на странице «Ноды».
