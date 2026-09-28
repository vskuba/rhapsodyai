# Detective — игра-детектив на движке workflow

> Публичная браузерная игра (PWA): движок генерирует дело об убийстве, создаёт **динамических
> агентов** под каждого подозреваемого и сержанта, игрок допрашивает их в чате и предъявляет
> обвинение. Целиком собрана из существующих примитивов — workflow, `agent.dynamic`,
> guest-сессии, `/play` static mount. Отдельного «игрового» кода в движке нет.

## Состав

```
apps/detective/                       # PWA-фронтенд (статика, монтируется как /play)
├── index.html                        # разметка чата
├── manifest.json                     # start_url/scope = /play/detective/
├── sw.js                             # заглушка service worker (skipWaiting + clients.claim)
├── css/app.css
└── js/app.js                         # весь клиент (~370 строк)
src/uvicorn/routers/detective/detective.py   # GET /detective/case_agents
src/tool/detective/detective_.py             # 6 инструментов workflow
```

БД: таблица `detective_case`. Динамические агенты — в обычной таблице `agent` с `dynamic = 1`.

Workflow (таблица `agent_workflow`):

| id | name | Роль |
|----|------|------|
| 12 | `detective_bot` | главный: команды, генерация дела, вердикт |
| 13 | `detective_talk` | диалог с подозреваемым/сержантом (назначается динамическим агентам) |
| 14 | `detective_suspect_create` | sub-workflow: создать одного подозреваемого |

Агент-хост — `agent.id = 30` (`detective_bot`, `dynamic = 0`), companion — `id = 4`
(`detective_player`). Оба ID **захардкожены во фронтенде**.

## Как игрок попадает в игру

1. `main_uvicorn.py` монтирует `apps/` как `/play` через `NoCacheStaticFiles(html=True)`,
   и `/play` перечислен в публичных префиксах `auth_middleware` — сессия не нужна.
   На проде Caddy перехватывает `/play/detective/*` раньше uvicorn и отдаёт статику из
   `/srv/apps/detective` с `try_files {path} /index.html`.
2. `guestLoginEnsure()` → `POST /auth/guest`. Endpoint идемпотентный: если в сессии уже
   валидный пользователь — возвращает его; иначе создаёт `guest_<uuid4hex[:12]>` с
   `role_id = NULL`, `dynamic = 1`, случайным bcrypt-паролем и ставит `session["role"] = "guest"`.
   Непустая роль — всё, что нужно `AuthChecker([])`. `dynamic = 1` держит гостей вне
   node-экспорта и `mysql_migration_prod_create`.
3. `session_uuid` генерируется на клиенте (`uuidV4()` вручную — `crypto.randomUUID()`
   недоступен вне secure context, прод ходит по HTTP) и хранится в `localStorage`
   под `detective_session_uuid`. Он же — ключ изоляции всей партии.
4. История восстанавливается через `POST /chat/messages` `{session_uuid, limit: 50}`.

## Протокол чипов

Клиент рендерит токены из текста ответа регуляркой
`/\[\[link:([\s\S]+?)\]\]|\[\[([\s\S]+?)\]\]/g`:

- `[[link:URL|текст]]` → `<a class="chat-link">`
- `[[текст]]` → кликабельный чип `<span class="chat-suggestion">`

Клик по чипу (`onChipClick`): если текст совпал с `title` кого-то из `suspects`/`sergeant` —
переключаем `currentAgentId` на этого агента и печатаем его `greeting`; иначе отправляем текст
как обычное сообщение. Так `[[Имя]]` работает как «перейти к допросу», а `[[/accuse]]` — как
команда. Когда игрок не у агента 30, добавляется чип `🔙 Вернуться к делу`.

Список агентов дела клиент берёт из `GET /detective/case_agents?session_uuid=…` →
`{result: {suspects: [{id, title, greeting}], sergeant: {...}}}` (выборка по `name LIKE
'case_<uuid>_%'` и `name = 'sergeant_<uuid>'`, `ORDER BY id ASC`).

Отправка: `POST /chat/ask` `{question, agent_id: currentAgentId, session_uuid,
variables: {companion_title: «Игрок»}}` — троицу сборщик больше не
подставляет, и workflow 12/13 читает `companion_title` как входящую (шаги-источники
`inputs_map`). Флаг `requestInFlight` блокирует **и кнопку, и чипы** — иначе двойной
тап по `[[/new_case]]` запускает генерацию дела дважды.

Голос: удержание кнопки микрофона (`pointerdown/up/leave`) → `POST /chat/voice` FormData
`file=voice.wav`; расшифровка подставляется в поле ввода, **не** отправляется автоматически.
Кнопка скрывается, если нет `navigator.mediaDevices?.getUserMedia`.

## Конвенция имён динамических агентов

| Шаблон | Кто |
|--------|-----|
| `case_<session_uuid>_s1` … `_s4` | подозреваемые (`title` = имя персонажа) |
| `sergeant_<session_uuid>` | сержант Ковальски — держит все материалы дела |

Всё привязано к `session_uuid`, а не к `user_id`: гости массово шарят «пустого»
пользователя, и партии не должны пересекаться.

## Инструменты (`src/tool/detective/detective_.py`)

Все функции `async`, каждая берёт соединение через `async with mysql_get_db_async() as db`.

| Функция | Вход | Выход / эффект |
|---------|------|----------------|
| `detective_dynamic_agents_cleanup` | `session_uuid` | `DELETE FROM agent WHERE dynamic = 1 AND (name LIKE 'case_<uuid>_%' OR name = 'sergeant_<uuid>')` → `{deleted_qty}` |
| `detective_case_seed_generate` | `location_pool`, `weapon_pool` | `{location_theme, weapon_theme, guilty_suspect_index}` — `random.choice` + `random.randint(1, 4)` |
| `detective_case_create` | `session_uuid, user_id, victim_name, crime_description, guilty_suspect_name, solution_reveal` | INSERT в `detective_case` → `{id}` |
| `detective_suspects_queue_build` | `session_uuid`, `suspect_1..4_{name,sheet,greeting,interrogation}` | список из 4 словарей `{agent_name, name, sheet, greeting, interrogation}` |
| `detective_case_suspects_list` | `session_uuid` | `{chips, qty, victim_name, crime_description}`; `chips = " ".join(f"[[{title}]]")` |
| `detective_case_verdict_check` | `session_uuid, accused_name` | `{correct, guilty_suspect_name, solution_reveal}`; сравнение регистронезависимое, `solved = 1` ставится в любом случае |

Активное дело = строка с максимальным `id` для данного `session_uuid`
(`ORDER BY id DESC LIMIT 1`), поэтому `/new_case` не удаляет прошлые дела.

## Ключевой приём: жребий до LLM

`detective_case_seed_generate` выбирает тему локации, способ убийства и **номер виновного**
программно, до вызова LLM, и подаёт их в промпт как `%location_theme%`, `%weapon_theme%`,
`%guilty_suspect_index%`. Правило №10 промпта заставляет модель сделать виновным
`%suspect_<guilty_suspect_index>_name%`.

Причина: при свободной генерации LLM повторяет одни и те же декорации (особняк, гроза) и
почти всегда делает виновным первого подозреваемого — игра становится предсказуемой.
Тот же приём годится для любого workflow, где нужна настоящая вариативность.

## Workflow 12 `detective_bot`

Шаг 0 (`return_response_text`) печатает `%agent_greeting%` со списком команд и
`continue_workflow: false` — то есть по умолчанию бот только ждёт ввода. Ветвление —
через `transitions_before` по `prompt_user`:

| Ввод | Переход |
|------|---------|
| `/new_case` | шаг 156 → cleanup → шаг 143 (генерация) |
| `/accuse` | шаг 131 (список подозреваемых → вопрос → вердикт) |
| `/close_case` | шаг 207 → cleanup → шаг 208 («Дело закрыто») |

Ветка `/new_case`:

1. `tool_invoke` `detective_dynamic_agents_cleanup` — снести агентов прошлой партии.
2. `tool_invoke` `detective_case_seed_generate` (шаг 143).
3. `variable_conversion` — переложить `%detective_case_seed_generate_143_result_*%` в
   `location_theme` / `weapon_theme` / `guilty_suspect_index`.
4. `llm_to_json` «Сгенерировать дело» — **33 выходные переменные**: `victim_name`,
   `crime_description`, `guilty_suspect_name`, `solution_reveal`,
   `suspect_1..4_{name,sheet,greeting,interrogation,brief,relation}`, а также материалы дела
   `autopsy_report`, `evidence_report`, `witness_statements`, `bank_records`,
   `scene_inventory`. Промпт — 12 правил: fair-play классический детектив, ровно 4
   подозреваемых, мотив минимум у двух, разные типы родства/связи, язык `%user_language%`.
5. `tool_invoke` `agent_workflow_id(name = %detective_talk_workflow_name%)` → id workflow 13.
6. `tool_invoke` `detective_suspects_queue_build` → очередь из 4.
7. `workflow_invoke` → workflow **14**, `repeat: {count: 4}` (см. ниже).
8. `variable_conversion` — собрать сержанта: `sergeant_agent_name = "sergeant_%session_uuid%"`,
   `sergeant_title`, `sergeant_greeting`, и большой `sergeant_prompt_system` с секциями
   `=== ВСКРЫТИЕ ===`, `=== УЛИКИ ===`, `=== ПОКАЗАНИЯ СВИДЕТЕЛЕЙ ===`,
   `=== БАНКОВСКИЕ ЗАПИСИ ===`, `=== ОПИСЬ МЕСТА ПРЕСТУПЛЕНИЯ ===`,
   `=== ПРЕДВАРИТЕЛЬНЫЕ ДОПРОСЫ ПОДОЗРЕВАЕМЫХ ===`. Сержант **не знает**, кто виновен —
   иначе он сливает разгадку по первому вопросу.
9. `tool_invoke` `agent_create_or_update` — сержант.
10. `tool_invoke` `detective_case_create` — зафиксировать дело.
11. `return_response_text` «Дело открыто»: жертва, описание, отчёт о вскрытии и 4 чипа
    `[[%suspect_N_name%]] (%suspect_N_relation%) — %suspect_N_brief%` плюс `[[/accuse]]`.

Ветка `/accuse`: `detective_case_suspects_list` (шаг 131) → вопрос «Кого ты обвиняешь…»
с чипами и `continue_workflow: true` → `detective_case_verdict_check` (шаг 133) → ответ с
условным блоком `[<if ..._correct>]✅ Верно!…[<else>]❌ Мимо…[<endif>]`.

## Workflow 13 `detective_talk`

Назначается **всем** динамическим агентам партии (и подозреваемым, и сержанту) — персона
приходит из `prompt_system` конкретного агента, а не из workflow.

1. `tool_invoke` `session_messages(session_uuid, limit = %session_messages_limit%)` (20).
2. `return_response_llm` — если история непустая, впереди идёт `=== История допроса ===`,
   затем `=== %companion_title% спрашивает ===\n%prompt_user%`. Инструкция: 1–3 предложения,
   от первого лица, в образе, язык `%user_language%`.

## Workflow 14 `detective_suspect_create` — паттерн цикла

Вызывается из шага 7 workflow 12 с `repeat: {count: 4}`:

```json
"workflow_invoke": {
  "workflow_id": 14,
  "repeat": {"count": 4},
  "inputs_map": {
    "suspects_queue": "detective_suspects_queue_build_124_result_list",
    "talk_workflow_id": "agent_workflow_id_123_result_int",
    "node_id": "node_id", "victim_name": "victim_name",
    "companion_title": "companion_title", "user_id": "user_id"
  },
  "outputs_map": {
    "list_shift_137_result_rest": "detective_suspects_queue_build_124_result_list"
  }
}
```

Внутри: `list_shift(items = %suspects_queue%)` (шаг 137) снимает первый элемент и возвращает
`rest`. `outputs_map` кладёт `rest` **обратно в ту же переменную**, из которой читает
`inputs_map`, — на следующей итерации очередь короче на один. Это штатный способ сделать
`for` поверх `workflow_invoke`; счётчика в движке нет.

Далее `variable_conversion` собирает `current_suspect_prompt_system` (никогда не выходить
из образа; невиновный отвечает правдиво, но нервничает; виновный отрицает, но путается
в деталях алиби при точных вопросах; не противоречить протоколу первичного опроса) с
секциями `=== Твоя легенда ===` (`%list_shift_137_result_sheet%`) и
`=== Что ты уже рассказал(а) полиции при первичном опросе ===`
(`%list_shift_137_result_interrogation%`), и `agent_create_or_update` создаёт агента
`case_<uuid>_sN` с `workflow_id = %talk_workflow_id%`.

## Переменные workflow

Привязаны к workflow 12/13/14 в `agent_workflow_variable*`. Значимые дефолты:

| Переменная | Значение / смысл |
|-----------|------------------|
| `detective_talk_workflow_name` | `detective_talk` — ищется по имени, id не хардкодится |
| `session_messages_limit` | `20` — глубина истории допроса |
| `suspects_queue` | `[]` — заполняется на лету |
| `location_pool` | JSON-массив декораций («уединённый особняк на скале у моря», «плавучее казино на реке», «горнолыжное шале, отрезанное снежной бурей», …) |
| `weapon_pool` | JSON-массив способов («отравленный бокал вина», «удушение шарфом», «подстроенное падение с высоты», …) |
| `sergeant_title` | `Сержант полиции` |

Расширять вариативность игры = дописать строк в `location_pool` / `weapon_pool` через
`/admin` — код и промпты трогать не нужно.

## Known issues

- **Нет DDL для `detective_case`.** В `migrations/20260101000000_initial_schema.sql` на месте таблицы только
  комментарий `-- developing / detective`, самой `CREATE TABLE` нет ни там, ни в `data/`.
  На чистой БД `/new_case` падает на шаге `detective_case_create`, а `/accuse` отвечает
  «Дело еще не начато». Схема живёт только в `20260101000000_initial_schema.sql` (`migration.md`) — таблицу надо
  туда добавить.
- **Битый `greeting` у агента 30** прямо в seed-файле:
  `[[link:http:/[[/92]].5.17.195:8011[[/play]][[/detective]]/|🕵️ Играть]]` — каждый
  `/`-сегмент обёрнут в `[[…]]`, ссылка «Играть» не рендерится.
- `sw.js` — заглушка: кеширования, offline и push нет, только `skipWaiting` +
  `clients.claim`. `manifest.json` без иконок (`icons: []`).
