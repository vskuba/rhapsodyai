# Architecture Reference

## Core Modules (`py_modules/`)

| Module | Purpose |
|--------|---------|
| `ai/` | AI framework core — agents, tasks, MCP, tools, sessions |
| `config/` | Configuration via `.env` |
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

## Application Code (`src/`)

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

## Key Dependencies

- **AI/LLM**: `pydantic-ai`, `anthropic`, `openai`, `groq`, `google-genai`
- **Vector DB**: `qdrant-client`, `fastembed`
- **Database**: `pymysql`, `aiomysql`, `yoyo-migrations`
- **Web**: `fastapi`, `uvicorn`, `jinja2`
- **Telegram**: `aiogram`
- **Voice**: `faster-whisper`
- **Queue**: `redis`, `redis-queue`
- **Tools**: `crawl4ai`, `PyGithub`

Install: `pip install -r docker/uvicorn/requirements.txt` / `docker/telegram/requirements.txt`

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

## Environment Variables (`.env`)

- `LLM`, `LLM_ALLOWED` — default model and allowed models list
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`
- `GITHUB_TOKEN`, `JIRA_URL`, `JIRA_API_TOKEN`, `JIRA_EMAIL`
- `WHISPER_MODEL_NAME`, `WHISPER_LANGUAGE`
- `DATA_DIR`, `HISTORY_DIR`, `REPORT_DIR`, `TASK_DIR`, `LOG_DIR`
- `SESSION_SECRET_KEY` — FastAPI session secret
- `TELEGRAM_TOKEN_RHAPSODY`, `TELEGRAM_OWNER_CHAT_ID` — Telegram Mini App

## Queue Names

Key queues used across the system:
`chat`, `chat_response`, `chat_input_send`, `task`, `task_abort`, `task_complete`, `task_continue`, `tool`, `agent_abort`, `agent_response`, `ai_framework_model`
