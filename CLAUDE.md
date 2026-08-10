# CLAUDE.md

## Project Overview

**RhapsodyAi** — multi-modal AI agent framework.
- **Telegram Bot** (`main_telegram.py`)
- **FastAPI/Uvicorn Server** (`main_uvicorn.py`) — Web API + HTML frontend

`py_modules/` — shared libraries | `src/` — application code

See `.claude/docs/quickstart.md` for development commands and setup.

See `.claude/docs/ai_framework.md` for AI Framework architecture and usage.

See `.claude/docs/database.md` and `.claude/docs/migration.md` for database schema, migrations, and reset procedures.

## Development Patterns

See the documentation files in `.claude/docs/` for detailed patterns:

- **New Tool** → `.claude/docs/workflow_tool.md`
- **New Admin Page** → `.claude/docs/dashboard_frontend.md`
- **New Protected Endpoint** → `.claude/docs/auth.md`
- **Workflow** → `.claude/docs/workflow.md`
- **Team / Ping System** → `.claude/docs/project_team.md`
- **Settings/Config** → `.claude/docs/setting.md`

**Telegram Notification:**

```bash
docker exec uvicorn python3 -c "
import asyncio
from src.telegram_.telegram_notify import telegram_send_owner
asyncio.run(telegram_send_owner('your message'))
"
```

## Key Files

| File | Purpose |
|------|---------|
| `main_uvicorn.py` | App bootstrap (FastAPI/Uvicorn server) |
| `main_telegram.py` | Telegram bot entry point |
| `py_modules/ai/framework/ai_framework.py` | AI framework base (provider-agnostic) |
| `py_modules/ai/framework/ai_framework_manager.py` | Base manager: step execution primitives |
| `src/ai/framework/agent/ai_framework_manager.py` | Workflow engine: steps, transitions, tool invocation |
| `src/ai/ai_tool.py` | Tool auto-discovery & sync |
| `src/tool/` | All tools — auto-scanned by category |
| `src/uvicorn/routers/` | All API endpoints |
| `src/uvicorn/routers/dashboard.py` | HTML admin page routes + `require_auth` |
| `src/telegram_bot.py` | Telegram bot handler |
| `src/auth/auth.py` | `AuthChecker`, `get_current_user` |
| `src/cronjob/` | Cron job entry points |
| `migrations/0001.sql` | Единственный источник схемы БД |

## Docs Reference

Все файлы — в `.claude/docs/`.

**Основы**

| File | Contents |
|------|---------|
| `quickstart.md` | Запуск через Docker, порты, тесты, переменные `.env` |
| `architecture.md` | Модули, зависимости, Docker-сервисы, очереди |
| `architecture_rules.md` | Код-правила: функция-префикс = имя файла, дробление файлов |
| `auth.md` | Роли, права, `AuthChecker`, field-level policies |
| `setting.md` | Таблица `setting`, REST API, `/setting/config` для фронтенда |
| `dashboard_frontend.md` | Паттерны админ-страниц: JS, CSS, контракты API |
| `deploy.md` | Blue-Green деплой, `bluegreen.sh`, rollback |

**Данные**

| File | Contents |
|------|---------|
| `database.md` | Схема, порядок FK-таблиц |
| `migration.md` | yoyo, `0001.sql`, `mysql_seed_up`, сброс БД |
| `seed.md` | Seed SQL: API, генерация, автозапуск |
| `backup.md` | mysqldump/python-fallback, gzip, restore |

**AI и workflow**

| File | Contents |
|------|---------|
| `ai_framework.md` | Execution flow, агенты, MCP, движок workflow |
| `llm.md` | Таблицы, цепочка вызова, провайдеры, параллельность, мониторинг |
| `workflow.md` | Типы шагов, transitions, переменные, правила `tool_invoke` |
| `workflow_tool.md` | Создание инструментов, auto-discovery, best practices |
| `workflow_trace.md` | Журнал выполнения: схема, токены, `/admin/workflow_trace` |
| `workflow/dating_talk.md` | Пример workflow: 17 шагов, 3 LLM |

**Project-модули**

| File | Contents |
|------|---------|
| `project_planning.md` | Фазы, агенты, `research_loop` sub-workflow |
| `project_design.md` | Вкладки, API, таблицы, конфигуратор прототипа |
| `project_task.md` | `/admin/task`, конвейер агентов Manager/Developer/QA |
| `project_team.md` | Члены команды, `/admin/team`, heartbeat `/api/team/ping`, типы задач |

**Telegram и Claude Code**

| File | Contents |
|------|---------|
| `telegram_mini_app.md` | Архитектура Mini App, endpoints, голос, схема БД |
| `claude_session_registry.md` | Реестр сессий для вкладки Cloud в Mini App |
| `claude_shell.md` | `claude_shell_call`, удалённый сервер |
