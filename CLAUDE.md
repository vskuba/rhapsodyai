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
- `TELEGRAM_TOKEN_RHAPSODY`, `TELEGRAM_OWNER_CHAT_ID` — Telegram Mini App

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

Да, все верно, эти миграции не будут запускаться при дефлоре. Но ты можешь сам зайти на прот и вручную выполнить все. ### Sending the user a Telegram notification (as Claude Code)
Don't rely on the Telegram MCP plugin being connected — it can disconnect mid-session. `TELEGRAM_TOKEN_RHAPSODY` and `TELEGRAM_OWNER_CHAT_ID` are already in `.env`/the running container, which is enough to message the user directly over the Bot API, no plugin needed. Reuse the existing helper instead of hand-rolling an HTTP call:

```bash
docker exec uvicorn python3 -c "
import asyncio
from src.telegram_.telegram_notify import telegram_send_owner
asyncio.run(telegram_send_owner('your message'))
"
```

`telegram_send_owner()` (`src/telegram_/telegram_notify.py`) posts to `https://api.telegram.org/bot{TELEGRAM_TOKEN_RHAPSODY}/sendMessage` with `chat_id=TELEGRAM_OWNER_CHAT_ID`. Use this whenever asked to "send me a Telegram message" and the MCP plugin route isn't available.

### Claude session registry — mirroring responses to the Mini App chat
If `.claude/session_uuid` exists in this checkout, this terminal is a registered session (see `.claude/docs/claude_session_registry.md`) tracked in `ai_claude_session_registry` and shown in the Mini App "Cloud" tab. When registered:

- Immediately start `python3 .claude/hooks/session_client.py watch --session-uuid "$(cat .claude/session_uuid)"` in the background (`run_in_background: true`) if it isn't already running. This is a token-free heartbeat+inbox poller (~5s tick) — it's what keeps the session visible in the Mini App (staleness cutoff is 15s). It naturally dies when the terminal closes, so don't treat killing it as a normal shutdown step. The session is always "on" while the terminal is open — there's no pause/resume toggle (it was tried and removed: it didn't block anything real, `watch`/`Monitor` woke the LLM on any message regardless of status).
- Arm a `Monitor` (`persistent: true`) on that background process. Its `NEW_MESSAGES` marker lines are the wake signal — drain `inbox` and process any real messages as normal user prompts, replying via `respond`. `watch` itself already sends a canned "Получено, разбираюсь…" push the instant it sees a new message (no LLM involved — this doesn't depend on the agent remembering), so the baseline ack is covered automatically. Still send your own richer intermediate update once you actually understand what's being asked, same `--no-notify` pattern as below.
- Don't run a separate fixed-interval or backoff `/loop` purely to keep heartbeat alive — `watch` already does that continuously, independent of whether the LLM itself is awake. A `/loop`/`ScheduleWakeup` cadence is only useful here if you want the LLM itself to periodically re-check things beyond what `Monitor` triggers.
- Mirror your responses — intermediate progress *and* the final answer, not just the final one — into the Mini App chat via `.claude/hooks/session_client.py respond --session-uuid "$(cat .claude/session_uuid)" --response "..."`. Use `--no-notify` for intermediate steps (chat history only, no push) and the default (push) for the final answer, so the user sees live progress instead of just an end result.
- Use `.claude/hooks/session_client.py` for all registry calls (`heartbeat`, `inbox`, `respond`, `finalize`, `watch`) instead of hand-rolling curl — it already reads the secret/base URL from `.env.local`/`.env` (`.env.local` wins if both exist). This whole session-registry setup (`session_tool.py`, `session_client.py`, `session_start.py`, the `SessionStart` hook in `settings.json`, this section) is portable — copy it verbatim into another project's `.claude/`, add the same `TELEGRAM_TOKEN_RHAPSODY`/`TELEGRAM_MINI_APP_URL` to that project's `.env`, and it registers there automatically (`project_label` comes from the cwd basename).
- For one-off authorized calls to other `/telegram-app/...` endpoints (hook-secret auth only), use `.claude/hooks/session_tool.py call METHOD PATH [--params k=v] [--body JSON]` instead of writing an inline-python heredoc each time. If you notice yourself repeating the same multi-step diagnostic dance more than once in a session, add it as a new tool there (grouped under a `# === ... ===` section) rather than repeating it by hand again.

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
