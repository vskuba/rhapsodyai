# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**RhapsodyAi** is a multi-modal AI agent framework with three operating modes:
1. **Telegram Bot** (`main_telegram.py`) - Telegram-only agent mode
2. **GUI Desktop App** (`main_gui.py`) - Tkinter-based desktop application
3. **FastAPI/Uvicorn Server** (`main_uvicorn.py`) - Web API with HTML frontend

The project uses a modular architecture with `py_modules/` for shared libraries and `src/` for application-specific code.

## Common Development Commands

### Running the Application

```bash
# GUI mode (desktop app)
python main_gui.py

# Telegram bot mode
python main_telegram.py

# FastAPI/Uvicorn web server
python main_uvicorn.py

# Docker Compose (full stack with all services)
docker-compose up -d

# Specific services
docker-compose up -d uvicorn qdrant redis mysql
```

### Environment Setup

```bash
# Install dependencies (uvicorn mode)
pip install -r docker/uvicorn/requirements.txt

# Install dependencies (telegram mode)
pip install -r docker/telegram/requirements.txt

# Copy environment template
cp .env.dist .env
# Edit .env with your API keys
```

### Database & Migrations

```bash
# Run MySQL migrations (handled automatically on uvicorn startup)
# Migrations are in /migrations directory and use yoyo-migrations
```

### Key Dependencies

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
| `ai/` | AI framework core - agents, tasks, MCP, tools, sessions |
| `config/` | Configuration management via `.env` |
| `logging_/` | Structured logging |
| `queue_/` | In-memory async queue system |
| `state/` | Global state management |
| `thread_/` | Thread utilities |
| `mysql_/` | MySQL connection pooling & repositories |
| `redis_/` & `redis_queue/` | Redis connection & RQ queue |
| `qdrant_/ ` | Vector database client |
| `mcp_/` | Model Context Protocol client |
| `setting_/` | Settings persistence |
| `async_/` | Async utilities |
| `json_/` | JSON utilities |
| `translator/` | Translation utilities |

### Application Code (`src/`)

| Path | Purpose |
|------|---------|
| `ai/` | AI workflow, tools, fact collection |
| `auth/` | Authentication (session, role, permission) |
| `cronjob/` | Scheduled jobs (fact sync, google ping) |
| `faster_whisper/` | Speech-to-text |
| `mysql_/repository/` | Database repositories for all entities |
| `parser/` | Data parsers (HTML→JSON, JSON→Qdrant, MD→Qdrant, MD→Fact) |
| `tool/` | Tool implementations (weather, github, qdrant, session, text, agent, dating) |
| `translator/` | Markdown translator |
| `uvicorn/routers/` | FastAPI route handlers |
| `window/` | Tkinter GUI components (tabs, UI, agents, tasks) |

### Data & Configuration (`data/`)

| Path | Purpose |
|------|---------|
| `agent/*.yml` | Agent definitions (soko, weather, jira, github, thinker, fact_extractor, fact_compressor) |
| `tasks/*.yml` | Task workflow definitions |
| `tools/*.py` | Tool implementations |
| `mcp/*.json` | MCP server configurations |

## AI Framework Architecture

The AI framework (`py_modules/ai/framework/`) is the core orchestration layer:

### Key Classes

1. **`AbstractAiFramework`** - Base class for all AI frameworks
2. **`AiFrameworkAgent`** - Conversational agent framework
3. **`AiFrameworkTask`** - Multi-step task execution framework
4. **`AiFrameworkModel` / `AiFrameworkTaskModel`** - Data models for framework execution
5. **`AiFrameworkManager` / `AiFrameworkTaskManager`** - Lifecycle managers

### Execution Flow

```
Queue → ai_thread_framework_run() → Framework Instance → engine_prepare() → engine_run() → engine_result_handle() → on_complete callback
```

### Agent vs Task Framework

- **Agent Framework** (`py_modules/ai/framework/agent/`) - Single-turn or multi-turn conversations with tool use
- **Task Framework** (`py_modules/ai/framework/task/`) - Structured multi-step workflows with YAML-defined sub-tasks, typed outputs, and state persistence

### MCP Integration

- `AiMcpManager` in `py_modules/ai/ai_mcp.py` handles MCP server connections
- Tools from MCP servers are dynamically added to agents
- Configured via `data/mcp/*.json`

## Queue System

The project uses a custom in-memory queue system (`py_modules/queue_/queue_.py`):

```python
# Initialize queues (done in each main_*.py)
queue_init(['chat', 'chat_response', 'task', 'agent', 'agent_response', 'telegram_response', ...])

# Access queues
from queue_.queue_ import queue_get
queue_get('agent').put(framework_model)
```

Key queues: `chat`, `chat_response`, `task`, `task_abort`, `task_complete`, `task_continue`, `tool`, `agent`, `agent_abort`, `agent_response`, `telegram_response`, `ai_framework_model`

## Database Schema (MySQL)

Repositories in `src/mysql_/repository/` cover:
- `AgentRepository` - Agent definitions
- `ToolRepository` / `ToolGroupRepository` - Tools and groups
- `LLMRepository` - LLM configurations
- `UserRepository` - User management
- `AgentWorkflowRepository` / `AgentWorkflowStepRepository` - Workflow definitions
- `FactCollectionRepository` - Collected facts
- `NodeRepository` - Workflow nodes
- `DatingGirlRepository` - Dating app entities

## Docker Services (docker-compose.yml)

| Service | Port | Purpose |
|---------|------|---------|
| `uvicorn` | 8011 | Main FastAPI application |
| `telegram` | - | Telegram bot (production profile) |
| `mysql` | 3302 | Primary database |
| `redis` | 6379 | Queue & caching |
| `qdrant` | 6333/6334 | Vector database |
| `opensearch` | 9200/9600 | Log search |
| `opensearch-dashboards` | 5601 | Log visualization |
| `logstash` | - | Log processing |
| `cronicle` | 3012 | Job scheduler |
| `rq-dashboard` | 9181 | Redis queue monitoring |
| `phpmyadmin` | 9634 | MySQL admin |
| `worker` | - | RQ background worker |

## Configuration

Environment variables in `.env` (from `.env.dist`):
- `LLM` - Default model (e.g., `ollama/gpt-oss:20b`)
- `LLM_ALLOWED` - Comma-separated allowed models
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY` - API keys
- `GITHUB_TOKEN` - GitHub API token
- `JIRA_URL`, `JIRA_API_TOKEN`, `JIRA_EMAIL` - Jira MCP credentials
- `WHISPER_MODEL_NAME`, `WHISPER_LANGUAGE` - Speech-to-text settings
- `DATA_DIR`, `HISTORY_DIR`, `REPORT_DIR`, `TASK_DIR`, `LOG_DIR` - Data directories
- `SESSION_SECRET_KEY` - FastAPI session secret

## Development Notes

### Adding a New Tool

1. Create tool in `src/tool/<name>/<name>.py`
2. Register in `py_modules/ai/tool/ai_tool.py` via `ai_tools_get()`
3. Add to agent's tool list in `data/agent/<agent>.yml`

### Adding a New Agent

1. Create YAML in `data/agent/<name>.yml`
2. Define: `name`, `llm_id`, `system_prompt`, `tools`, `specializations`
3. Use in Telegram bot or GUI via agent manager

### Running Tests

No formal test suite exists. Test manually via:
- GUI: `python main_gui.py`
- Telegram: `python main_telegram.py` (requires valid token)
- API: `python main_uvicorn.py` then visit `http://localhost:8011`

### Key Files to Understand

1. `main_uvicorn.py` - Full application bootstrap with all routers
2. `py_modules/ai/framework/ai_framework.py` - Core AI framework base
3. `py_modules/ai/framework/task/ai_framework.py` - Task execution engine
4. `src/uvicorn/routers/` - All API endpoints
5. `src/window/` - GUI implementation
6. `src/telegram_bot.py` - Telegram bot handler