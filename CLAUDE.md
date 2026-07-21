# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**RhapsodyAi** is a multi-modal AI agent framework with two operating modes:
1. **Telegram Bot** (`main_telegram.py`) - Telegram-only agent mode
2. **FastAPI/Uvicorn Server** (`main_uvicorn.py`) - Web API with HTML frontend

Modular architecture: `py_modules/` for shared libraries, `src/` for application-specific code.

## Common Development Commands

```bash
# Run modes
python3 main_uvicorn.py
python3 main_telegram.py

# Docker
docker-compose up -d
docker-compose up -d uvicorn qdrant redis mysql

# Dependencies
pip install -r docker/uvicorn/requirements.txt
pip install -r docker/telegram/requirements.txt

# Tests (requires running uvicorn on localhost:8011)
python3 -m pytest tests/ -v
python3 -m pytest tests/test_user_crud.py -v
python3 -m pytest tests/test_login.py -v
python3 -m pytest tests/test_agent_crud.py -v
```

**After editing .py files:** restart uvicorn for changes to take effect.

## Key Dependencies

- **AI/LLM**: `pydantic-ai`, `anthropic`, `openai`, `groq`, `google-genai`
- **Vector DB**: `qdrant-client`, `fastembed`
- **Database**: `pymysql`, `aiomysql`, `yoyo-migrations`
- **Web**: `fastapi`, `uvicorn`, `jinja2`
- **Telegram**: `aiogram`
- **Voice**: `faster-whisper`
- **Queue**: `redis`, `redis-queue`
- **Tools**: `crawl4ai`, `PyGithub`

## Architecture Overview

### Core Modules (`py_modules/`)

| Module | Purpose |
|--------|---------|
| `ai/` | AI framework core — agents, tasks, MCP, tools, sessions |
| `config/` | Configuration management via `.env` |
| `flux_schnell/` | Image generation (SDXL-Turbo/Flux) |
| `logging_/` | Structured logging |
| `microphone/` | Speech recognition |
| `mysql_/` | MySQL connection pooling & repositories |
| `queue_/` | In-memory async queue system |
| `redis_/` & `redis_queue/` | Redis connection & RQ queue |
| `qdrant_/` | Vector database client |
| `setting_/` | Settings persistence |
| `sqllite3/` | SQLite for LLM short-term memory |
| `state/` | Global state management |
| `mcp_/` | Model Context Protocol client |

### Application Code (`src/`)

| Path | Purpose |
|------|---------|
| `ai/` | AI workflow, tools, fact collection |
| `auth/` | Authentication (session, role, permission, field policy) |
| `cronjob/` | Scheduled jobs |
| `faster_whisper/` | Speech-to-text |
| `mysql_/repository/` | Database repositories for all entities |
| `parser/` | Data parsers (HTML→JSON, MD→Qdrant, MD→Fact) |
| `tool/` | Tool implementations (weather, github, qdrant, session, text, agent, dating) |
| `uvicorn/routers/` | FastAPI route handlers |

## AI Framework

Core: `py_modules/ai/framework/`

**Key classes:** `AbstractAiFramework`, `AiFrameworkAgent`, `AiFrameworkTask`, `AiFrameworkModel`, `AiFrameworkManager`

**Execution flow:**
```
Queue → ai_thread_framework_run() → Framework Instance → engine_prepare() → engine_run() → engine_result_handle() → on_complete callback
```

- **Agent Framework** (`py_modules/ai/framework/agent/`) — conversational, single/multi-turn with tool use
- **Task Framework** (`py_modules/ai/framework/task/`) — multi-step workflows, typed outputs, state persistence
- **MCP**: `AiMcpManager` in `py_modules/ai/ai_mcp.py`, configured via `data/mcp/*.json`

## Queue System

Custom in-memory queue: `py_modules/queue_/queue_.py`

```python
from queue_.queue_ import queue_get
queue_get('agent').put(framework_model)
```

Key queues: `chat`, `chat_response`, `chat_input_send`, `task`, `task_abort`, `task_complete`, `task_continue`, `tool`, `agent_abort`, `agent_response`, `ai_framework_model`

## Database (MySQL)

Repositories in `src/mysql_/repository/`. Migrations via `yoyo-migrations`, applied automatically on startup.

Migration files: `0001.sql` (DDL schema), `0002.sql` (system seed), `0003.sql` (Dating node), `0004.sql` (Detective node).

To reset schema:
```bash
mysql -u developer -p -h localhost -P 3302 -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python3 main_uvicorn.py
```

See `.claude/docs/database.md` for full migration structure, FK table order, and conventions.

## Docker Services

| Service | Port | Purpose |
|---------|------|---------|
| `uvicorn` | 8011 | Main FastAPI application |
| `mysql` | 3302 | Primary database |
| `redis` | 6379 | Queue & caching |
| `qdrant` | 6333/6334 | Vector database |
| `opensearch` | 9200 | Log search |
| `opensearch-dashboards` | 5601 | Log visualization |
| `cronicle` | 3012 | Job scheduler |
| `rq-dashboard` | 9181 | Redis queue monitoring |
| `phpmyadmin` | 9634 | MySQL admin |

## Configuration (`.env`)

- `LLM`, `LLM_ALLOWED` — Default model and allowed models list
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`
- `GITHUB_TOKEN`, `JIRA_URL`, `JIRA_API_TOKEN`, `JIRA_EMAIL`
- `WHISPER_MODEL_NAME`, `WHISPER_LANGUAGE`
- `DATA_DIR`, `HISTORY_DIR`, `REPORT_DIR`, `TASK_DIR`, `LOG_DIR`
- `SESSION_SECRET_KEY` — FastAPI session secret
- `TELEGRAM_NOTIFY_TOKEN`, `TELEGRAM_OWNER_CHAT_ID` — Telegram Mini App

## Development Notes

### Adding a New Tool
1. Create `src/tool/<name>/<name>.py`
2. Register in `py_modules/ai/tool/ai_tool.py` via `ai_tools_get()`

### Adding a New Admin Page
1. Template: `data/uvicorn/template/admin/new_page.html` (extends `base.html`)
2. Route: `src/uvicorn/routers/html.py`
3. API: `src/uvicorn/routers/new_entity/new_entity.py`
4. Register router in `main_uvicorn.py`

See `.claude/docs/frontend.md` for page patterns, JS architecture, CSS classes, API contracts.

Detailed workflow docs:
- `.claude/docs/workflow.md` — Workflow system overview, nuances, development directions
- `.claude/docs/workflow_dating_talk.md` — Analysis of `dating_talk` workflow (17 steps)
- `.claude/docs/workflow_trace_plan.md` — Plan for execution trace / observability

### Adding a Protected Endpoint
1. Add `AuthPermission` in `src/auth/auth_permission.py`
2. Add to role map in `src/auth/auth_role.py`
3. Use `Depends(AuthChecker([AuthPermission.NEW_PERM]))` in router

See `.claude/docs/auth.md` for full auth system details, field-level policies, code examples.

### Telegram Mini App
Located at `GET /telegram-app`. Uses Telegram WebApp initData auth (not admin session). Three tabs: Events, Chat, Plans.

See `.claude/docs/telegram_mini_app.md` for full architecture, API endpoints, voice input, and DB schema.

### Key Files

| File | Purpose |
|------|---------|
| `main_uvicorn.py` | Full application bootstrap |
| `py_modules/ai/framework/ai_framework.py` | AI framework base |
| `py_modules/ai/framework/task/ai_framework.py` | Task execution engine |
| `src/uvicorn/routers/` | All API endpoints |
| `src/telegram_bot.py` | Telegram bot handler |
| `src/auth/auth.py` | AuthChecker, get_current_user |
| `src/auth/auth_field_policy.py` | Field-level access policy |
