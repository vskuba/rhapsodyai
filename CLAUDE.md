# CLAUDE.md

## Project Overview

**RhapsodyAi** — multi-modal AI agent framework.
- **Telegram Bot** (`main_telegram.py`)
- **FastAPI/Uvicorn Server** (`main_uvicorn.py`) — Web API + HTML frontend

`py_modules/` — shared libraries, только Python (общий submodule, каталог — `.claude/docs-common/py_modules.md`) | `dashboard/` — общая статика панелей, второй submodule (⚠ раздача ищет файл **сперва у нас**, потом там: свой файл с тем же именем перекрывает общий. ⚠⚠ Общие модули подключаются **абсолютным путём** `/static/js/notification.js` — относительный требовал бы файла на диске проекта, то есть общего submodule при нём не бывает; прогон такого модуля на node — `js_static_run`) | `src/` — application code

See `.claude/docs/quickstart.md` for development commands and setup.

See `.claude/docs/ai_framework.md` for AI Framework architecture and usage.

See `.claude/docs/database.md` and `.claude/docs/migration.md` for database schema, migrations, and reset procedures.

**Универсальные правила — в `.claude/docs-common/`** (индекс: `.claude/docs-common/readme.md`).
Там правила без привязки к проекту: именование, контракт API, права, схема БД, деплой,
инструменты, LLM, трейс, время, тесты, формат документации. `.claude/docs/` описывает, как это
реализовано именно здесь. При расхождении конкретика из `.claude/docs/` — актуальнее.

⚠️ `.claude/docs-common` — **симлинк на `py_modules/docs`**, общий для всех проектов.
Читается как обычная папка, но правка через него меняет общий репозиторий: коммит идёт в
`py_modules`, и её увидят соседние проекты. Проектной конкретике там не место.

## Development Patterns

See the documentation files in `.claude/docs/` for detailed patterns:

- **New Tool** → `.claude/docs/tools.md`
- **New Worker / фоновая обработка** → `.claude/docs/worker.md`
- **New Admin Page** → `.claude/docs/dashboard_frontend.md`
- **New Protected Endpoint** → `.claude/docs/auth.md`
- **Workflow** → `.claude/docs/workflow.md`
  - ⚠⚠⚠ **АРХИТЕКТУРУ WORKFLOW ПРИДУМЫВАЕТ ТОЛЬКО ЧЕЛОВЕК. Модели разрешено
    повторять то, что уже есть, — и ничего больше.** Новый шаг, переменная,
    переход делаются **по образцу соседних**. Новый приём вводит только человек,
    и только конкретным указанием. Встретил в workflow что-то неправильное —
    **скажи, но не правь**. Полное правило и счёт ошибок — `workflow.md`, шапка.
  - ⚠ правка промпта, шага, перехода или входящей переменной — тесты маршрута
    (`tests_llm/`, метка `llm`) идут **сами**: ответы модели даёт подмена.
    ⚠⚠ Живые (`llm_live`) по-прежнему **предлагают, а не запускают**: нода одна на
    тесты и на прод. Папка на workflow — `tests_llm/<имя_workflow>/`
- **Что сломалось на установке** → `.claude/docs/journal.md` (страница «Журнал»,
  `/admin/journal`, подвкладка «Ошибки»; ошибки стекаются туда сами — от кода
  требуется только сообщать сбой `logger_exception`, а не `logger_info`)
- **Team / Ping System** → `.claude/docs/project_team.md`
- **DeepSeek Harness: включение ролей со страницы команды** → `.claude/docs/dsh.md`
- **Settings/Config** → `.claude/docs/setting.md`

**Telegram Notification:**

```bash
docker exec uvicorn python3 -c "
import asyncio
from src.telegram_.telegram_notify import telegram_notify_send_owner
asyncio.run(telegram_notify_send_owner('your message'))
"
```

## Key Files

| File | Purpose |
|------|---------|
| `main_uvicorn.py` | App bootstrap (FastAPI/Uvicorn server) |
| `main_telegram.py` | Telegram bot entry point |
| `main_browser.py` | Контейнер-браузер: один Chromium, изолированные сессии. Сам сервис — `py_modules/browser_` (общий submodule), здесь только точка входа |

**Знакомства уехали.** Анкеты, живой чат и страница `/admin/dating` живут в отдельном
проекте **DatingAi**; он ходит сюда по HTTP за браузером (`/api/browser/*`) и за
агентом анкеты (`/agent/create`, `/agent/name/{name}`) под учёткой `dating_service`.
Здесь остались агенты, workflow `dating_talk` / `dating_girl_create` и коллекция
фактов `dating_girl` — они про агентов, а не про анкеты.
| `py_modules/ai/framework/ai_framework.py` | AI framework base (provider-agnostic) |
| `py_modules/ai/framework/ai_framework_manager.py` | Base manager: step execution primitives |
| `src/ai/framework/agent/ai_framework_manager.py` | Workflow engine: steps, transitions, tool invocation |
| `src/ai/ai_tool.py` | Tool auto-discovery & sync |
| `src/tool/` | All tools — auto-scanned by category |
| `src/uvicorn/routers/` | All API endpoints |
| `src/uvicorn/routers/dashboard.py` | HTML admin page routes + `dashboard_require_auth` |
| `src/telegram_bot.py` | Telegram bot handler |
| `src/auth/auth.py` | **Дверь** к скелету панели `py_modules/panel_/` (`.claude/docs-common/panel.md`): `AuthChecker` и `auth_get_current_user` остались именами, проверка уехала в слой. ⚠⚠ Модель прав взяли **отсюда** — у соседей панель умела только `is_admin`. ⚠ Дверь, а не переименование: `AuthChecker` стоит в 391 объявлении. ⚠⚠ В `__call__` аннотация `Request` **обязательна**: без неё FastAPI считает довод query-параметром и отвечает 422 на всех 391 точке |
| `src/auth/auth_access.py` | Переходник: наш каталог глазами скелета (⚠ `auth_permission.py`, `auth_role.py`, `auth_field_policy.py` не тронуты — они и были правильными) |
| `src/auth/auth_store.py` | Хранилище людей: роль **ссылкой** `user.role_id` на таблицу `role` (⚠⚠ чтение переводит номер в имя `JOIN`-ом, запись — имя обратно в номер; это та половина, которую подменяемым SQL не выразить. ⚠⚠ Правило «пользователь №1 всегда админ» живёт здесь, в одном месте: иначе разошлось бы между входом по сессии и по токену) |
| `src/uvicorn/routers/user/user.py` | Две точки, которых нет в скелете: «кто я» по токену и **мой токен** для окна мини-приложения (⚠⚠ не противоречит скрытым значениям: отдаётся свой ключ и только тому, у кого уже есть сессия. ⚠ Список, карточка, заведение, правка, удаление и токены — в `panel_user_api`, вместе с тремя запретами, которых здесь не было: роль себе, удаление себя, последний полноправный) |
| `src/uvicorn/routers/setting/setting.py` | Одна точка `/api/setting/config` — переменные для фронтенда этой установки. ⚠ Список, правка, удаление и личные настройки уехали в скелет панели (`panel_setting_api`), вместе с областью узла: столбец `node_id` стоит в таблице у всех трёх проектов |
| `src/cronjob/` | Cron job entry points |
| `src/worker/` | Все воркеры (Redis/rq): `project/task_worker.py` — очередь `default`, `project/planning_worker.py` — очередь `planning` |
| `migrations/*.sql` | Миграции yoyo, имя — метка времени `date +%Y%m%d%H%M%S` (секунды обязательны); начальная схема заморожена. **И схема, и данные** — отдельного пути для данных нет, `data/migration_manual/` упразднена |

## Docs Reference

Две папки: `.claude/docs-common/` — универсальные правила (симлинк на `py_modules/docs`,
один источник на все проекты), `.claude/docs/` — устройство этой инсталляции.

### Универсальные правила — `.claude/docs-common/`

| File | Contents |
|------|---------|
| `readme.md` | Индекс папки, разделение `docs-common/` и `docs/`, правила самой папки |
| `code_rules.md` | Префикс функций и констант, приватные внизу, дробление файлов, ветки размещения |
| `api_rules.md` | Контракт ответов, формат ошибок, разделение роутеров, валидация входа |
| `auth_rules.md` | Сессии, RBAC, проверка по возможностям (не по имени роли), полевые политики |
| `database_rules.md` | Единственный DDL-файл, DDL против данных, порядок FK, идемпотентность, прод |
| `backup_rules.md` | Seed против бэкапа, экспорт/восстановление, безопасность имён файлов |
| `env_config_rules.md` | `.env` / `.dist` / `.local`, секреты, таблица настроек, конфиг для фронтенда |
| `frontend_rules.md` | SSR-страницы админки, чек-лист новой страницы, локальность зависимостей |
| `deploy_rules.md` | Blue-Green, конфиг прокси как источник истины, healthcheck, откат |
| `tool_rules.md` | Два слоя (инструменты и общие библиотеки), куда что писать, контракт функции, докстринг для LLM, ошибки |
| `py_modules.md` | Общий слой библиотек: что внутри, как подключается, правка чужого репозитория |
| `project_runtime.md` | Разовое действие в проекте: корень и интерпретатор, прогон кода, запрос к базе без пароля в аргументах |
| `browser_control.md` | Браузер отдельным сервисом: сессии-контексты, память, живое окно, селекторы, скрипты в страницу |
| `browser_scenario.md` | Сценарий над страницей: действия, ожидание по признаку, переменные и секреты, сбор данных, трасса |
| `browser_page.md` | Вопросы к живой странице: текст для модели, снимок и PDF, наблюдатель DOM, консоль, вход без браузера |
| `mobile_device.md` | Телефон через adb: чем смотреть, снимки экрана, грабли vision-моделей |
| `mobile_control.md` | Телефон под управлением: карта экрана, нажатия и ввод, приложения, журнал |
| `mobile_steps.md` | Шаг с проверкой: замер и покой экрана, сравнение до/после, вырезка в натуральную величину |
| `vision_llm.md` | Локальные модели, читающие изображения: контракт `data:`-URI, цена картинки в токенах |
| `new_project.md` | Каркас нового проекта: что копируется, раскладка папок, контейнеры, настройки, чек-лист заведения |
| `llm_rules.md` | Маршрутизация по провайдерам, приоритет и фоллбэк, параллельность, журнал |
| `datetime_rules.md` | Время: хранение в UTC, показ в поясе настройки `timezone`, сравнение из одного источника |
| `observability_rules.md` | Трейс выполнения, «сбой журнала не роняет процесс», обрезка, чистка |
| `testing_rules.md` | Интеграционная сюита, тестовая учётка, проверка после реализации |
| `docs_rules.md` | Формат документации: структура файла, тон, что не писать |

### Проектная документация — `.claude/docs/`

**Основы**

| File | Contents |
|------|---------|
| `quickstart.md` | Запуск через Docker, порты, тесты, переменные `.env` |
| `testing.md` | Группы тестов по подсистемам: что запускать под свою правку, как делить новые |
| `testing_browser.md` | Живой Chromium (`tests_browser/`): контейнер ходит наружу мимо сторожа сети, пул вкладок общий. ⚠⚠ Вне `testpaths`: запуск только руками и с согласия человека |
| `e2e.md` | Страница «Тесты → E2E» (`/admin/e2e`): прогон снимает страницы панели, меряет названные области числами из DOM и рисует рамки на кадре. ⚠ Контейнер-браузер не нужен — голова своя, playwright-овская; ⚠⚠ под root Chrome молча не стартует без `--no-sandbox`. Случаи — `tests_e2e/*.yaml`, каркас — `py_modules/tests_e2e/` |
| `testing_llm.md` | Прогон workflow (`tests_llm/`): папка на workflow, утверждения только по трассе — текст ответа не проверяется никогда. ⚠ Метка `llm` идёт сама (подменная модель), `llm_live` — только руками: нода общая с продом |
| `architecture.md` | Модули, зависимости, Docker-сервисы, очереди |
| `architecture_rules.md` | Код-правила проекта (общая часть — `docs-common/code_rules.md`) |
| `worker.md` | Воркеры в `src/worker/`: очереди Redis/asyncio, таймауты, single-flight |
| `journal.md` | Страница «Журнал» (`/admin/journal`, пункт меню за Opensearch) и её подвкладки. **«Ошибки»:** всё, что пишется уровнем ERROR в любом процессе, попадает туда **само** (обработчик корневого логгера); писать в журнал руками не надо, но сбой сообщать `logger_exception`, а не `logger_info` — иначе он в журнал не попадёт. **«MySQL»:** запросы к базе — строка на **вид** запроса, числа складываются по отпечатку (`hits`, суммарное/среднее/макс время, строки в ответе, значения самого долгого прогона). Ответы базы не хранятся; секреты в значениях вырезаны. Считает `py_modules/mysql_/mysql_watch.py` в памяти процесса, сбрасывает `src/journal/journal_mysql.py` пачкой раз в полминуты; выключатель — настройка `journal_mysql_enabled` на `/admin/setting`, действует без перезапуска. ⚠ «Журнал» — раздел с подвкладками: соседние добавляются кнопкой и панелью в `admin/journal.html` |
| `browser.md` | Контейнер-браузер: как подключён `py_modules/browser_`, страница админки, прокси вебсокета, API :8014, инструменты над страницей. ⚠ Там же §4.3 — **реестр сетевых прокси** (своя страница `/admin/browser/proxy`, не вкладка сайта: выход общий на установку и к закладке не привязан): какие выходы есть и какие живые. **Раздачу он не ведёт** — про потребителей здесь не знают; кому какой выход достанется, решает тот, кто их ведёт, по `check_ip` из списка |
| `auth.md` | Роли, права, `AuthChecker`, field-level policies |
| `setting.md` | Таблица `setting`, REST API, `/setting/config` для фронтенда, `gx10_autocompact_limit` |
| `cronicle.md` | Страница «Настройки → Cronicle» (`/admin/cronicle`): расписание, включатель события, последний удачный прогон за сегодня. ⚠ Нужен `CRONICLE_API_KEY` в `.env` с правами `get_schedule` и `edit_events`; ⚠⚠ «сегодня» считается в поясе настройки `timezone`, а не в UTC |
| `dashboard_frontend.md` | Паттерны админ-страниц: JS, CSS, контракты API |
| `deploy.md` | Blue-Green деплой, `bluegreen.sh`, rollback |
| `worktree.md` | Выкладки задач: где работают роли, проверка контекста, git-хук |

**Данные**

| File | Contents |
|------|---------|
| `database.md` | Схема, порядок FK-таблиц |
| `migration.md` | yoyo, `20260101000000_initial_schema.sql`, `mysql_seed_up`, сброс БД |
| `seed.md` | Seed SQL: API, генерация, автозапуск |
| `backup.md` | mysqldump/python-fallback, gzip, restore |

**AI и workflow**

| File | Contents |
|------|---------|
| `ai_framework.md` | Execution flow, агенты, MCP, движок workflow |
| `llm.md` | Таблицы, цепочка вызова, провайдеры, параллельность, мониторинг |
| `workflow.md` | Типы шагов, transitions, переменные, правила `tool_invoke` |
| `tools.md` | Два слоя: общие библиотеки `py_modules` и инструменты `src/tool`; именование, auto-discovery, вызов из workflow |
| `workflow_trace.md` | Журнал выполнения: схема, токены, `/admin/workflow_trace` |
| `workflow_history.md` | **Спека, не реализация**: вкладка «History» — история правок workflow (кто, когда, что на что). Заведена после того, как потерянная метка `repeat.count` сломала инвайты **без единой ошибки**, и время поломки искали по чужой базе |
| `workflow/dating_talk.md` | Пример workflow: 17 шагов, 3 LLM |
| `detective.md` | Игра-детектив: PWA `/play/detective`, guest-сессии, динамические агенты, workflow 12/13/14 |

**Project-модули**

| File | Contents |
|------|---------|
| `project_planning.md` | Фазы, агенты, `research_loop` sub-workflow |
| `project_design.md` | Вкладки, API, таблицы, конфигуратор прототипа |
| `project_task.md` | `/admin/task`, устройство конвейера: состояния, отбор работы, схема БД, API |
| `project_task_roles.md` | Роли конвейера: Manager/Developer/QA/багфиксер — workflow, шаги, промпты, таймауты |
| `role_toolbox.md` | **Читают сами роли:** чем работать — команды, запреты, где писать |
| `role_developer.md` | Инструкция Developer: порядок круга, что не делать, когда спрашивать |
| `role_qa.md` | Инструкция QA: как проверять, чем доказывать цель, почему не чинить |
| `role_bugfixer.md` | Инструкция Bugfixer: воспроизвести → причина → минимальная правка |
| `role_manager.md` | Инструкция Manager: разведка, цели, разбиение по объёму контекста |
| `project_team.md` | Члены команды, `/admin/team`, heartbeat `/api/team/ping`, типы задач |
| `dsh.md` | Включатель ролей DeepSeek Harness: пульты `ds-shell --service`, `/api/team/dsh/*`, кнопки на карточках |

**API соседей и подсистемы `src/`**

| File | Contents |
|------|---------|
| `blog.md` | `/api/blog`: 9 точек BlogAi, 6 агентов под нодой `Blog` (`tag`/`compose`/`similar` — в `stt.md`) |
| `chat.md` | `/chat/*`: ask (агент), messages (журнал), voice (wav→whisper); LLM по ноде агента, i18n по ноде/юзеру |
| `translate.md` | `POST /translate`: перевод «вне ноды», агент ищется **по имени** `translator` |
| `node.md` | `/api/node`: CRUD нод LLM, `llm_ids` = полная замена, порядок — `rate_limit_at, position` |
| `gx10.md` | `/api/gx10`: статус и control SSH-хоста через sshpass (SSHPASS в env), кэш 3 с |
| `playwright.md` | `/admin/playwright` + роутер: **пустой** заглушка, зарезервировано под прокси к контейнеру-браузеру |
| `event.md` | `py_modules/event_` (fire-and-forget) + `src/event/event_handlers.py`: лог-системы и Telegram по `user.login` |
| `translator.md` | `src/translator/`: сканер папок MD-перевода, подсистема без вызовов |
| `parser.md` | `src/parser/`: YAML-конфиги парсеров (`html/json/md`→json/qdrant/fact), без вызовов |

**Базовые сущности движка**

| File | Contents |
|------|---------|
| `agent.md` | `/agent/*`: две дороги заведения — записью и «workflow заводит сам»; переменные агента (`agent_variable`) — шаблон промпта вместо записи на каждого |
| `role.md` | `/role/*`: CRUD ролей, право на каждое действие, привязка агентов через `agent_role` |
| `user.md` | `/user/*`: админский CRUD, bcrypt-хеш, токены доступа, привязка нод |
| `session.md` | `/session/*`: чтение журнала `agent_session` — список, последняя, диалог по `session_uuid` |
| `fact.md` | `/fact/*` и `/fact/collection/*`: факты и коллекции, пересинк в Qdrant |
| `companion.md` | `/companion/*`: справочник собеседников на две точки, get-or-create |

**Telegram и Claude Code**

| File | Contents |
|------|---------|
| `telegram_mini_app.md` | Архитектура Mini App, endpoints, голос, схема БД |
| `claude_session_registry.md` | Реестр сессий для вкладки Cloud в Mini App |
| `claude_shell.md` | `claude_shell_call`, удалённый сервер |
