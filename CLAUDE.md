# CLAUDE.md

## Project Overview

**RhapsodyAi** — multi-modal AI agent framework.
- **Telegram Bot** (`main_telegram.py`)
- **FastAPI/Uvicorn Server** (`main_uvicorn.py`) — Web API + HTML frontend

`py_modules/` — shared libraries (общий submodule, каталог — `.claude/docs-common/py_modules.md`) | `src/` — application code

See `.claude/docs/quickstart.md` for development commands and setup.

See `.claude/docs/ai_framework.md` for AI Framework architecture and usage.

See `.claude/docs/database.md` and `.claude/docs/migration.md` for database schema, migrations, and reset procedures.

**Универсальные правила — в `.claude/docs-common/`** (индекс: `.claude/docs-common/readme.md`).
Там правила без привязки к проекту: именование, контракт API, права, схема БД, деплой,
инструменты, LLM, трейс, время, тесты, формат документации. `.claude/docs/` описывает, как это
реализовано именно здесь. При расхождении конкретика из `.claude/docs/` — актуальнее.

## Development Patterns

See the documentation files in `.claude/docs/` for detailed patterns:

- **New Tool** → `.claude/docs/tools.md`
- **New Worker / фоновая обработка** → `.claude/docs/worker.md`
- **New Admin Page** → `.claude/docs/dashboard_frontend.md`
- **New Protected Endpoint** → `.claude/docs/auth.md`
- **Workflow** → `.claude/docs/workflow.md`
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
| `main_browser.py` | Контейнер-браузер: один Chromium, изолированные сессии |

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
| `src/auth/auth.py` | `AuthChecker`, `auth_get_current_user` |
| `src/cronjob/` | Cron job entry points |
| `src/worker/` | Все воркеры (Redis/rq): `project/task_worker.py` — очередь `default`, `project/planning_worker.py` — очередь `planning` |
| `migrations/*.sql` | Миграции yoyo, имя — метка времени `date +%Y%m%d%H%M%S` (секунды обязательны); начальная схема заморожена. **И схема, и данные** — отдельного пути для данных нет, `data/migration_manual/` упразднена |

## Docs Reference

Две папки: `.claude/docs-common/` — универсальные правила (переносимы в любой проект),
`.claude/docs/` — устройство этой инсталляции.

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
| `architecture.md` | Модули, зависимости, Docker-сервисы, очереди |
| `architecture_rules.md` | Код-правила проекта (общая часть — `docs-common/code_rules.md`) |
| `worker.md` | Воркеры в `src/worker/`: очереди Redis/asyncio, таймауты, single-flight |
| `browser.md` | Контейнер-браузер: сессии-контексты, API :8014, память, настройки compose |
| `auth.md` | Роли, права, `AuthChecker`, field-level policies |
| `setting.md` | Таблица `setting`, REST API, `/setting/config` для фронтенда, `gx10_autocompact_limit` |
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
| `agent.md` | `/agent/*`: две дороги заведения — записью и «workflow заводит сам» |
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
