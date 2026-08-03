# CLAUDE.md

## Project Overview

**RhapsodyAi** — multi-modal AI agent framework.
- **Telegram Bot** (`main_telegram.py`)
- **FastAPI/Uvicorn Server** (`main_uvicorn.py`) — Web API + HTML frontend

`py_modules/` — shared libraries | `src/` — application code

## Development Commands

```bash
python3 main_uvicorn.py                        # web server
python3 main_telegram.py                       # telegram bot
docker-compose up -d                           # all services
docker-compose up -d uvicorn qdrant redis mysql
.venv/bin/python3 -m pytest tests/ -v          # tests (requires uvicorn on :8011)
```

**After editing .py files:** restart uvicorn.

## AI Framework

Core: `py_modules/ai/framework/`

Execution flow: `Queue → ai_thread_framework_run() → engine_prepare() → engine_run() → engine_result_handle() → on_complete`

- **Agent** (`py_modules/ai/framework/agent/`) — conversational, tool use
- **MCP**: `AiMcpManager` in `py_modules/ai/ai_mcp.py`, config via `data/mcp/*.json`

Queue usage: `from queue_.queue_ import queue_get` → `queue_get('agent').put(framework_model)`

## Database (MySQL)

Migrations via `yoyo-migrations`, auto-applied on startup.

Reset schema:
```bash
mysql -u developer -p -h localhost -P 3302 -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python3 main_uvicorn.py
```

See `.claude/docs/database.md` for schema, FK order, migration details.

## Development Patterns

### New Tool
1. Create `src/tool/<category>/<name>.py` (можно вкладывать в подпапки, например `src/tool/project/planning/`)
2. Инструменты автообнаруживаются через `rglob` в `src/ai/ai_tool.py` — ручная регистрация не нужна
3. После перемещения/переименования файлов вызвать `POST /tool/sync` для обновления путей в БД

### New Admin Page
1. Template: `data/uvicorn/template/admin/new_page.html` (extends `base.html`)
2. Route: `src/uvicorn/routers/dashboard.py` (HTML-роуты) или отдельный роутер `src/uvicorn/routers/<entity>/<entity>.py`
3. API: `src/uvicorn/routers/<entity>/<entity>.py`
4. Register router in `main_uvicorn.py`

See `.claude/docs/dashboard_frontend.md` for page patterns, JS architecture, CSS classes.

### New Protected Endpoint
1. Add `AuthPermission` in `src/auth/auth_permission.py`
2. Add to role map in `src/auth/auth_role.py`
3. Use `Depends(AuthChecker([AuthPermission.NEW_PERM]))` in router

See `.claude/docs/auth.md` for full auth details and field-level policies.

### Telegram Notification (Claude Code → Owner)

MCP plugin may disconnect mid-session — use this instead:

```bash
docker exec uvicorn python3 -c "
import asyncio
from src.telegram_.telegram_notify import telegram_send_owner
asyncio.run(telegram_send_owner('your message'))
"
```

`telegram_send_owner()` is in `src/telegram_/telegram_notify.py`.

## Key Files

| File | Purpose |
|------|---------|
| `main_uvicorn.py` | App bootstrap |
| `main_telegram.py` | Telegram bot entry |
| `py_modules/ai/framework/ai_framework.py` | AI framework base |
| `py_modules/ai/framework/agent/` | Agent execution engine |
| `src/uvicorn/routers/` | All API endpoints |
| `src/uvicorn/routers/dashboard.py` | HTML admin page routes |
| `src/ai/ai_tool.py` | Tool auto-discovery & sync (`ai_tool_sync`, `ai_tool_args_prepare`) |
| `src/tool/project/planning/` | Planning tools: project, phase, prototype, block, widget |
| `src/tool/project/design/` | Design tools: block, page, widget, wireframe |
| `src/telegram_bot.py` | Telegram bot handler |
| `src/auth/auth.py` | AuthChecker, get_current_user |
| `src/auth/auth_field_policy.py` | Field-level access policy |

## Docs Reference

| File | Contents |
|------|---------|
| `.claude/docs/architecture.md` | Modules, dependencies, Docker services, env vars, queue names |
| `.claude/docs/database.md` | Schema, migrations, FK table order |
| `.claude/docs/dashboard_frontend.md` | Admin page patterns, JS, CSS, API contracts |
| `.claude/docs/auth.md` | Auth system, field-level policies, code examples |
| `.claude/docs/deploy.md` | Blue-Green deployment, `bluegreen.sh`, rollback |
| `.claude/docs/telegram_mini_app.md` | Mini App architecture, API endpoints, voice, DB schema |
| `.claude/docs/workflow.md` | Workflow system overview and development directions |
| `.claude/docs/claude_session_registry.md` | Multi-session registry for Telegram Mini App Cloud tab |
| `.claude/docs/project_planning.md` | Planning node: фазы, агенты, research_loop sub-workflow, инструменты |
| `.claude/docs/llm.md` | LLM-архитектура: таблицы, цепочка вызова, провайдеры, параллельность, мониторинг |
| `.claude/docs/workflow_trace.md` | Workflow Trace: схема БД, запись из движка, токены, API, страница `/admin/workflow_trace` |
| `.claude/docs/migration.md` | Migration & Seed system: yoyo, 0001.sql, mysql_seed_up, сброс БД |
| `.claude/docs/seed.md` | Seed SQL: API, генерация, какие таблицы включать, автозапуск |
| `.claude/docs/backup.md` | Backup: mysqldump/python-fallback, gzip, restore, отличие от seed |
| `.claude/docs/project_design.md` | Design модуль: вкладки, API, таблицы, AI-токены, конфигуратор прototипа |
