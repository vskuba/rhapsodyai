# Team — члены команды и heartbeat

> Карточки в `project_team` (Manager / Developer / QA) описывают роли, под
> которыми запускаются оболочки `claude-shell`. Набор ролей **свой у каждого проекта**:
> карточка принадлежит проекту через `project_id`. Страница `/admin/team` раз в 15 с перечитывает
> блоки проектов и считает «живость» по свежести пинга в реестре сессий
> (`ai_claude_session_registry.last_seen_at`), а не по `project_team.last_ping_at`.
> Здесь же лежит справочник `project_task_type` — типы задач для `/admin/task`.

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `src/uvicorn/routers/project/project_team.py` | REST API `/api/team/*`, `TeamPingRequest`, `TeamStatusResponse` |
| `src/project/team/team_member.py` | Записи `project_team`: список, поиск по id/роли, ping, activate/deactivate |
| `src/project/team/team_project.py` | Блоки `/admin/team`: карточки ролей по проектам, живость и готовность |
| `src/project/team/team_queue.py` | Очередь роли для карточки: кто чего ждёт и что делает сейчас |
| `src/project/team/team_agent.py` | Агент движка и его workflow для карточки роли |
| `src/project/team/team_session.py` | Действия над живой оболочкой: перезапуск агента по сессии и по роли |
| `src/project/team/team_task_type.py` | Справочник `project_task_type` |
| `src/mysql_/repository/project/team_repository.py` | Репозиторий `project_team` |
| `src/mysql_/repository/project/task_type_repository.py` | Репозиторий `project_task_type` |
| `data/uvicorn/template/admin/project/team.html` | Страница `/admin/team` — карточки, авто-обновление |
| `src/uvicorn/routers/dashboard.py` | Роут `/admin/team` (`require_auth`) |
| `migrations/0001.sql` | Схема `project_team`, `project_task_type`, FK `project_task.task_type_id` |
| `tests/test_team_ping.py` | Интеграционные тесты API (`pytest.mark.integration`) |

Сама оболочка `claude-shell` живёт **вне этого репозитория** — в проекте нет кода, который
отправляет heartbeat. Внутри репозитория ping посылают только тесты — на странице
`/admin/team` кнопки пинга нет, она лишь читает `GET /api/team`.

## Роли и записи

У каждого проекта свой комплект из трёх карточек — три роли, у каждой своя команда
запуска и свой рабочий каталог:

| project_id | name | role | command |
|------------|------|------|---------|
| N | Manager | `manager` | `claude-shell --gx10 --manager` |
| N | Developer | `developer` | `claude-shell --gx10 --developer` |
| N | QA | `qa` | `claude-shell --gx10 --qa` |

Заготовка комплекта — константа `TEAM_MEMBER_ROLE_CARD` в `team_member.py`; заводит его
`team_member_cards_ensure(project_id)` — идемпотентно, создаёт только недостающие роли и
подставляет `work_dir` проекта. Её вызывают оба пути создания проекта:
`POST /planning/project` (`project_planning.py`) и инструмент `project_create`
(`src/tool/project/project.py`), поэтому новый проект сразу встречает человека готовыми
карточками, а не пустым блоком.

`project_id IS NULL` — карточка вне проектов; такие строки питают блок «Без проекта» на
`/admin/team` (в питон-словарях этот ключ — `0`, константа `TEAM_PROJECT_NO_PROJECT`).

`claude-shell --gx10` без флага роли — «безролевая» оболочка: она регистрируется только
в `ai_claude_session_registry` и `project_team` не трогает (`claude_session_registry.md`).

### Какому проекту принадлежит пинг

Оболочка знает свою роль (`--manager/--developer/--qa`), но не знает `project_id`, а роль
теперь не уникальна. Проект вычисляется из каталога запуска:
`team_project_id_by_work_dir(work_dir)` сравнивает нормализованный путь (без хвостового
слэша) с `project.work_dir` — тем же правилом, каким `_project_sessions_select` разносит
сессии по блокам, так что карточка и её оболочка всегда попадают в один проект.
Если проект не определился, `team_member_get_by_role(role, project_id=None)` откатывается
на первую строку с этой ролью — внешняя оболочка не должна получать 404 на `/ping`.

## Схема БД

Полный DDL — `migrations/0001.sql`, секция `-- ─── Project Team ───`.

### `project_team`

| Колонка | Тип | Назначение |
|---------|-----|-----------|
| `id` | INT PK | |
| `project_id` | INT NULL → `project.id` | Проект карточки; `NULL` — карточка вне проектов. FK `ON DELETE CASCADE` |
| `name` | VARCHAR(100) | Имя члена команды; уникально в паре `uk_team_project_name (project_id, name)` |
| `role` | VARCHAR(50) | `manager` / `developer` / `qa` |
| `command` | VARCHAR(255) | Команда запуска оболочки (показывается на карточке) |
| `work_dir` | VARCHAR(255) | Рабочая директория проекта |
| `status` | ENUM('active','inactive') | Последний известный статус |
| `last_ping_at` | DATETIME | Время последнего пинга — **основной признак живости** |
| `pid` | INT | PID процесса оболочки |
| `session_uuid` | CHAR(36) | UUID сессии Claude Code |
| `created_at`, `updated_at` | DATETIME | |

Отдельной колонки `member_type` нет — тип члена команды это `role`.

### `project_task_type`

| Колонка | Тип | Назначение |
|---------|-----|-----------|
| `id` | INT PK | |
| `name` | VARCHAR(50) UNIQUE | `dev`, `bug`, `test`, `research`, `plan` |
| `title` | VARCHAR(100) | Отображаемое название |
| `description` | TEXT | |

Текущее содержимое: `dev` — Разработка, `bug` — Исправление ошибки, `test` — Тестирование,
`research` — Исследование, `plan` — Планирование.

Ссылка из задач: `project_task.task_type_id INT DEFAULT NULL`,
`fk_pt_task_type … ON DELETE SET NULL` — удаление типа не удаляет задачи, а обнуляет поле.

## REST API

Роутер подключён с префиксом `/api/team` и `include_in_schema=False` (в `/docs` не виден).

**Публичны только три POST-а.** В `public_paths` middleware (`main_uvicorn.py`,
`exact → POST`) внесены `/api/team/ping`, `/api/team/activate`, `/api/team/deactivate` —
их дёргает внешняя оболочка, у которой нет браузерной сессии. Читающие
`GET /api/team` и `GET /api/team/types` закрыты `AuthChecker([AuthPermission.PLANNING_VIEW])`:
они отдают `work_dir`, `pid` и `session_uuid`, публиковать это незачем. Без сессии
`GET /api/team` → **401**.

Внести весь префикс в `startswith → ANY` (как было раньше) нельзя ещё и потому, что
`startswith_patterns` берёт список по методу, а при его отсутствии — `ANY`: любой
per-method ключ в `startswith` полностью перекрыл бы общий список. Пометки на отдельные
методы поэтому живут только в `exact`.

| Метод | Путь | Тело | Назначение |
|-------|------|------|-----------|
| GET | `/api/team` | — | Список членов команды (`order_by=id`) |
| POST | `/api/team/ping` | `member_id` \| `role` (+ `pid`, `session_uuid`, `work_dir`) | `status='active'`, `last_ping_at=NOW()` |
| POST | `/api/team/activate` | то же | То же, что ping — явная активация из UI/скрипта |
| POST | `/api/team/deactivate` | то же | `status='inactive'`, сброс `pid` и `session_uuid` |
| GET | `/api/team/types` | — | Справочник `project_task_type` |
| POST | `/api/team/session/restart` | `session_uuid` | Перезапуск агента в оболочке; закрыт `PLANNING_UPDATE` |

### Перезапуск агента — `team_session.py`

Действия над конкретной живой оболочкой вынесены в `src/project/team/team_session.py`
(состав карточек — в `team_project.py`). Перезапуск просят двумя способами, механизм один:
в очередь `ai_claude_session` кладётся маркер `__RESTART_WATCH__` с `dynamic=1`, оболочка
подтверждает его через `inbox-ack` и поднимает дочерний Claude Code заново — контекст при
этом обнуляется.

- `team_session_restart(session_uuid)` — кнопка 🔄 в углу активной карточки на `/admin/team`
  (и та же механика в Telegram Mini App). Ответа не ждёт: новый heartbeat придёт секундами
  позже, страница увидит его следующим опросом `/api/team/projects`.
- `team_session_restart_role(role)` — перед тем как роль возьмёт в работу новую задачу.
  Ждёт подтверждения маркера и возвращения агента в `ready`, чтобы первый промпт не ушёл в
  умирающий процесс. Ничего не бросает, отдаёт `reason`: `no_session` / `no_ack` /
  `not_ready`. Таймауты и порядок ожидания — `claude_shell.md` §4.1, применение в конвейере —
  `project_task.md`.

Если watch мёртв, маркер из очереди никто не прочитает — на этот случай кнопка шлёт
уведомление владельцу в Telegram: плагин в терминале разбудит агента, и watch поднимут руками.

### Идентификация: `member_id` или `role`

`team_member_resolve()` принимает любой из двух:

- `member_id` — так делает страница `/admin/team`, она знает id карточки;
- `role` — так делает оболочка: ей известен только флаг запуска (`--manager` / `--developer`
  / `--qa`), а id она не знает. Поиск `find_one_by({'role': role}, order_by='id')` — при
  нескольких записях с одной ролью возьмётся младшая по id.

Не передано ни одного → **422** (`member_id or role is required`), запись не найдена → **404**.

### Формат ответов

Ответы отдаются как есть, без обёртки `{"result": …}`:

```bash
curl -X POST http://localhost:8011/api/team/ping \
  -H "Content-Type: application/json" -d '{"role": "qa", "pid": 12345}'
# {"success": true, "member_id": 3}
```

```bash
curl -s http://localhost:8011/api/team | python3 -m json.tool
# [
#   {"id": 1, "name": "Manager", "role": "manager",
#    "command": "claude-shell --gx10 --manager", "work_dir": "",
#    "status": "inactive", "last_ping_at": "2026-08-10T12:59:54",
#    "pid": 3256, "session_uuid": "fddbbdf7-db88-4ea2-a5a7-2f84e392addc"},
#   ...
# ]
```

`last_ping_at` — наивный datetime из MySQL, без таймзоны; фронтенд дописывает `'Z'` и
трактует его как UTC.

Необязательные поля пинга собираются в `TeamPingRequest.session_get()` и попадают в
`UPDATE` только если непустые (`TeamService._session_data`) — пинг без `pid` не затирает
уже записанный PID.

`team_deactivate()` намеренно чистит `pid` и `session_uuid` (процесса больше нет, иначе на
карточке они читаются как живая сессия), но **не** чистит `work_dir` — это настройка члена
команды, а не след процесса.

## Страница `/admin/team`

Страница строится блоками: один блок — один проект, внутри карточки ролей. Карточка —
иконка роли (👔 manager, 💻 developer, 🔍 qa), переведённое название, индикатор статуса,
бейдж готовности агента, метаданные (Session UUID, последний пинг, LLM, агент и workflow);
у серых карточек ещё и команда запуска с кнопкой копирования. Данные даёт
`GET /api/team/projects` → `team_project_blocks_get()`.

Ключевое поведение:

- **Живость считается по свежести пинга, а не по колонке `status`.** Порог —
  `TEAM_PROJECT_PING_STALE_SECONDS = 30` в `team_project.py`: оболочка пингует реестр раз в
  несколько секунд, так что 30 с — это много пропущенных пингов подряд, а не один
  задержавшийся. Колонка `status` остаётся `active` навсегда, если процесс убили через
  `kill -9` — деактивацию он отправить не успевает.
- **Протухшая карточка роли исчезает, если у роли есть живая.** Закрытая и заново открытая
  оболочка оставляет в реестре две строки, и старая иначе занимала бы слот роли в ряду
  (`_cards_stale_drop`). Единственную протухшую карточку роли оставляем — на ней команда
  запуска, и она показывает, что роль когда-то работала.
- **Готовность агента** (`agent_status`) приходит с heartbeat оболочки и показывается
  бейджем только у активных карточек: `ready` — сообщение уйдёт в дочерний процесс сразу,
  `busy` — встанет в очередь. Свежий пинг сам по себе этого не гарантирует; подробности —
  `claude_session_registry.md` §4.1.
- **Агент и workflow роли** (`team_agent.py`): строки «Агент» и «Workflow» в мета-блоке
  карточки — ссылки на `/admin/agent?agent_id=N` и `/admin/workflow?workflow_id=N`
  (открываются в новой вкладке, чтобы не терять живую страницу команды). Карта
  `TEAM_AGENT_BY_ROLE` связывает роль с именем агента, а не с id: id зависит от установки.
  Сейчас в ней `manager` → `task_plan_manager` и `developer` → `task_dev_developer`;
  QA — заглушка (`task_agent.py`), агента у неё нет, и строки не рисуются. Агент
  принадлежит роли, а не
  проекту: карточки менеджеров всех проектов показывают один и тот же агент, различаясь
  только оболочкой, в которую он ходит.
- **Очередь роли на карточке** (`team_queue.py`): строка «в очереди N», под ней задача в
  работе (первая, с маркером ▶) и первые `TEAM_QUEUE_PREVIEW_LIMIT = 3` ожидающих, а если
  ждущих больше — хвост «и ещё N». Корневые задачи стоят в очереди у той роли, которая их
  планирует (тип задачи → роль, `task_role.py`: `plan`/`research` и задачи без типа —
  менеджер, `dev` — разработчик, `bug`/`test` — QA), подзадачи — всегда у Developer и QA.
  Подзадача — строка того же `project_task` с непустым `parent_id`; подсказка на строке
  показывает родительскую задачу. Поэтому у карточек Developer и QA список смешанный:
  свои корневые задачи на планирование плюс подзадачи чужих планов.
- **Что считается очередью, определяет SQL захвата, а не колонка `status`.** Условия
  скопированы из `task_claim.py`: планировщик ждёт задачи своих типов без плана либо без
  целей и задачи в `reviewing`; разработчик — подзадачи в `planned`/`failed_qa` с
  непотраченными попытками (`attempt_count < MAX_ATTEMPTS`); QA — подзадачи в
  `qa_pending`. Живой оболочки очередь, в отличие от захвата, не требует: карточка для
  того и показывает список, чтобы было видно, что ждёт погашенную роль. Порядок в списке
  совпадает с порядком захвата, поэтому первый ожидающий — следующий кандидат в работу.
  «В работе» от «в очереди» отличает блокировка (`locked_by` / `pipeline_locked_by`):
  у `reviewing` и `qa_pending` состояние при захвате не меняется, меняется только она.
- **Очередь считается в разрезе проекта — и конвейер тоже.** Карточки сгруппированы
  блоками проектов, поэтому цифра отвечает на вопрос «сколько задач этого проекта ждут
  роль», и захват конвейера отбирает ровно их: `task_role_shell_live_by_project()`
  раскладывает живые оболочки по проектам (проект — по `work_dir` реестра сессий, роль
  обязана иметь карточку `(project_id, role)`), а `task_role_project_type_sql()` требует
  совпадения `project_id` задачи. Менеджер соседнего проекта чужую задачу забрать не
  может. Исключение — задачи без проекта (`project_id` NULL или 0): они ничьи, и их берёт
  любая живая роль подходящего типа, иначе заведённые мимо проекта задачи не выполнил бы
  никто. Адресация прогона — тоже пара «роль + каталог проекта» (`claude_shell_call(...,
  work_dir=…)`), подробности — `project_task.md` §«Кто планирует».
- Авто-обновление `setInterval(loadTeamProjects, 15000)` плюс кнопка ручного обновления.
- **Кнопок ping/activate/deactivate на карточке нет.** Страница только читает
  `GET /api/team`; все три POST-а вызывает внешняя оболочка (и тесты). Мёртвый код кнопок
  (`sendPing`, `getPingColor`, CSS `.ping-indicator`, `.team-actions`, `.action-btn*`)
  из шаблона удалён.
- Единственная кнопка на карточке — копирование команды запуска. Команда передаётся через
  `dataset.command` (`copyCommand(this)`), а не подстановкой строки в `onclick`: любая
  кавычка внутри команды ломала обработчик.

Никакого cron-джоба, который переводил бы просроченные записи в `inactive`, в проекте нет —
устаревание существует только как вычисление на фронтенде.

## Связь с реестром сессий Claude

`POST /telegram-app/claude/session/register`
(`src/uvicorn/routers/telegram_app/telegram_app_claude_session.py`) принимает необязательный
`role`. Если он передан вместе с непустым `work_dir` — после регистрации сессии на карточке
обновляется `work_dir`. Карточка ищется парой «роль + проект» (проект — из того же
`work_dir` через `team_project_id_by_work_dir`), иначе запись ушла бы в первую попавшуюся
строку с этой ролью. Ошибки глушатся, регистрация из-за них не падает. Без `role` или с
пустым `work_dir` `project_team` не затрагивается. Подробности — `claude_session_registry.md`.

## Типы задач на `/admin/task`

`GET /api/team/types` — единственный источник типов для страницы задач: `select` в форме
создания (`#newTaskType`) и в строке задачи (`#ttt-<id>`), который пишет `task_type_id`.
Первая опция — «Не указан» (пустое значение), дальше 5 типов из справочника.

Табов-фильтров по типу задачи **нет**: `.task-type-tab`, `_taskTypeFilter` и авто-назначение
типа существующим задачам были нерабочим кодом (в частности, при загрузке страницы
рассылался залп `PUT /task/{id}`) и удалены. Табы над таблицей — это фазы
(`#phaseTabs`: Планирование / Разработка / Тестирование-Баги). Сама страница — `project_task.md`.

## Тесты

`tests/test_team_ping.py` — интеграционные, требуют поднятого uvicorn (`BASE_URL`, по
умолчанию `http://localhost:8011`), ходят по HTTP через `httpx`. Фикстура `qa_member`
восстанавливает исходный статус после прогона. Проверяют: поля в `GET /api/team`, ping по
`member_id` и по `role`, 404 на неизвестную роль/id, 422 на пустое тело, очистку
`pid`/`session_uuid` при deactivate и сохранение `work_dir`.

```bash
.venv/bin/python3 -m pytest tests/test_team_ping.py -v
```

`tests/test_team_task_pages.py` — Playwright-проверки страниц `/admin/team` и `/admin/task`
(sync API, headless chromium). Логин — общая учётка `tests.constants.TEST_AUTH` через
`/login` (`#username` / `#password`, редирект на `/`). Одна авторизованная вкладка на
модуль. Проверяют: карточки и их поля (`.team-role`, `.status-indicator`,
`.team-command-code`, `.meta-value`, `.ping-time`), совпадение `data-command` кнопки
копирования с показанной командой, 401 на `GET /api/team` без сессии, ping, фазовые табы,
`/api/team/types` и опции `#newTaskType`.

API-запросы идут через `page.request` / `context.request` — они несут cookie контекста;
голый `requests` с одним `csrf_token` сессию не передаёт и получил бы 401.

```bash
.venv/bin/python3 -m pytest tests/test_team_task_pages.py -v
```

`tests/manual_test_team_task.py` — тот же набор проверок скриптом, без pytest
(`.venv/bin/python3 -m tests.manual_test_team_task`). Имя файла не совпадает с
`python_files = test_*.py`, поэтому pytest его не собирает.

## Ограничения

- `command` ограничен 255 символами.
- Истории пингов нет — хранится только последнее время.
- Уведомления о потере активности нет.
- `project_team` и `project_task_type` наполняются только из дампа `data/seeds/*.sql`; в
  `0001.sql` их данных нет (там только схема). Если карточек в дампе не оказалось, после
  сброса БД таблицы нужно наполнить заново через `/admin/seed` (`seed.md`). Пустой
  `project_task_type` = селект типов на `/admin/task` состоит из одной опции «Не указан».
- Карточки в дампе идут после `project`: у `project_team.project_id` внешний ключ на
  `project.id`, порядок INSERT-ов ломать нельзя.
