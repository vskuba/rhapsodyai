# GEMINI.md

This file provides foundational guidance and instructions to the Gemini CLI agent when working with code in the **RhapsodyAi** repository. It defines architectural principles, development workflows, testing requirements, and code style conventions.

---

## 1. Project Overview & Architecture

**RhapsodyAi** is a highly modular, multi-modal AI agent framework with two main operating modes:
1. **Telegram Bot** (`main_telegram.py`) - Telegram-only agent interface.
2. **FastAPI/Uvicorn Server** (`main_uvicorn.py`) - Web API with a rich Jinja2/Vanilla JS HTML admin dashboard.

### Core Directory Layout

*   **`py_modules/` (Shared Core Libraries)**:
    *   `ai/` - AI framework core: agents, tasks, MCP, tools, and session managers.
    *   `config/` - Configuration wrapper utilizing dotenv.
    *   `flux_schnell/` - Image generation integrations (Flux/SDXL).
    *   `logging_/` - Uniform structured logging wrapper.
    *   `microphone/` - Local speech recognition utilities.
    *   `mysql_/` - MySQL database connection pools and migrations helper.
    *   `queue_/` - Dual-mode async queue (in-memory or Redis-queue based).
    *   `qdrant_/` - Vector database client operations.
    *   `sqllite3/` - Lightweight SQLite for short-term session/memory storage.
*   **`src/` (Application-Specific Code)**:
    *   `ai/` - Workflows, tool schemas, and automatic fact collection.
    *   `auth/` - Session-based authentication with Role-Based Access Control (RBAC).
    *   `cronjob/` - Background tasks (syncing facts, keep-alive pings).
    *   `parser/` - Markdown, HTML, and JSON data parsers feeding into Qdrant/Fact collections.
    *   `tool/` - Custom backend tools (GitHub, Weather, Jira, Dating, Session).
    *   `uvicorn/routers/` - FastAPI endpoint routers.
*   **`data/`**: Templates, assets, static files, and database schemas.
*   **`tests/`**: Pytest integration test suite.

---

## 2. Technical Stack & Key Dependencies

-   **Backend**: Python 3.11+, FastAPI, Uvicorn, Jinja2 (Templates).
-   **AI/LLM**: `pydantic-ai`, `anthropic`, `openai`, `google-genai`, `groq`.
-   **Vector Storage**: `qdrant-client`, `fastembed`.
-   **Primary DB**: MySQL via `pymysql` / `aiomysql` connection pooling.
-   **Database Migrations**: `yoyo-migrations`.
-   **Message Queue**: Redis & RQ (`redis`, `redis-queue`) or custom in-memory queues.
-   **Voice processing**: `faster-whisper`.
-   **Testing**: `pytest`, `pytest-asyncio`.

---

## 3. Core Development Workflows & Commands

All development must be validated against the following execution pipelines.

### Environment Setup & Dependency Installation

Always match the requirements to your targeted run target (Uvicorn or Telegram):

```bash
# Copy and edit environment variables
cp .env.dist .env

# Install dependencies for Web Server / Admin Dashboard
pip install -r docker/uvicorn/requirements.txt

# Install dependencies for Telegram Bot
pip install -r docker/telegram/requirements.txt
```

### Running the Applications

```bash
# Run FastAPI/Uvicorn Web Server (local dev)
python main_uvicorn.py

# Run Telegram Bot (local dev)
python main_telegram.py

# Running the complete service stack (Uvicorn, Qdrant, Redis, MySQL, phpMyAdmin, OpenSearch)
docker-compose up -d
```

### Database Schema Updates (Yoyo Migrations)

Database migrations live in `/migrations/` and are automatically executed upon Uvicorn server startup via `mysql_migration_up()`.

-   **`0001.sql`**: Complete DDL Schema (Tables, Indexes, Foreign Keys).
-   **`0002.sql`**: DML Seeds (Users, Nodes, Default Workflows, Agents).

-   **Table Dependency Order in `0001.sql`**: Must be preserved due to Foreign Key (FK) constraints:
    1. `llm` → 2. `user` → 3. `setting` → 4. `node` → 5. `session` → 6. `tool_group`/`tool` → 7. `agent_workflow`/`step_type`/`step`/`variable` → 8. `dating_girl` → 9. `fact_collection`/`fact` → 10. `agent` → 11. `agent_session`

**Important Reset Workflow**:
If you alter schemas, the database must be completely dropped and re-created so migrations run cleanly:
```bash
# Drop & re-create database locally (MySQL container on 3302)
mysql -u developer -ppassword -h localhost -P 3302 -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Restart the web server to trigger migrations
python main_uvicorn.py
```

**Direct MySQL Container Access**:
You can query and interact with the local MySQL container directly on port 3302 or through the container's MySQL command line. You are fully authorized to perform any operations directly on the database (such as SELECT, INSERT, UPDATE, DELETE, etc.) to examine the state, generate mock data, or debug database-related issues.

---

## 4. Key Architectural Patterns & Conventions

Gemini CLI MUST strictly follow these paradigms when modifying code.

### A. Queue Integration
We utilize a custom synchronous in-memory queue wrapper (`py_modules/queue_/queue_.py`) based on standard `queue.Queue`, which is accessed non-blockingly (e.g., via `get_nowait()`).
-   Initialize queues inside bootstrap files (`main_*.py`) using `queue_init(list_of_names)`.
-   Use `queue_get(name)` to retrieve queues. Do not instantiate queues manually.
-   The initialized queues differ by entry point:
    *   **FastAPI / Web mode (`main_uvicorn.py`)**: `'chat'`, `'chat_response'`, `'chat_input_send'`, `'task'`, `'task_abort'`, `'task_complete'`, `'task_continue'`, `'tool'`, `'agent_abort'`, `'agent_response'`, `'ai_framework_model'`.
    *   **Telegram bot mode (`main_telegram.py`)**: `'task'`, `'agent'`, `'agent_abort'`, `'agent_response'`, `'telegram_response'`.

### B. AI Framework Engine (`py_modules/ai/framework/`)
-   **Key Framework Components**:
    *   **`AbstractAiFramework`**: Base class handling standard lifecycle hooks.
    *   **`AiFrameworkAgent`**: Interactive conversation flow, multi-turn, with tool execution.
    *   **`AiFrameworkTask`**: Rigid multi-step YAML-defined workflow execution with typed outputs and state serialization.
    *   **`AiFrameworkManager` / `AiFrameworkTaskManager`**: Framework lifecycle managers.
-   **Core Execution Flow**:
    `Queue → ai_thread_framework_run() → Framework Instance → engine_prepare() → engine_run() → engine_result_handle() → on_complete callback`
-   **Model Context Protocol (MCP)**: Dynamic client-side integrations should utilize MCP server protocol configured under `data/mcp/*.json`. Configuration schemas and schema validations (e.g., `McpTool`, `McpToolInputSchema`, `McpConfig`) are managed inside `py_modules/mcp_/mcp_.py`.

### C. Admin Dashboard UI (`data/uvicorn/template/admin/`)
The frontend is a server-side Jinja2-rendered portal utilizing a **Master-Detail** layout with **Vanilla JS ES Modules**.
-   **DO NOT** introduce modern framework bundles (React/Vue/Tailwind) unless explicitly requested. Rely on `common.css` and custom inlined page CSS.
-   **Strict Separation of Concerns**: All scripts must be structured as `<script type="module">`.
-   **Module Script Initialization**: In many existing templates, DOM event listeners like `document.addEventListener('DOMContentLoaded', ...)` are used to call initialization functions. However, new/clean modules should run their custom initializer directly at the bottom of the module script (since ES modules defer execution naturally until the DOM is parsed).
-   **Page-Specific Initializers**: Pages utilize specific, self-contained manager initialization functions rather than a generic `initManager(activeId)`:
    *   Agents: `initAgentsManager(...)`
    *   Workflows: `initWorkflowManager()`
    *   Facts & Converter: `initFactManager(...)`
    *   Fact Collections: `initCollectionsManager(...)`
    *   Nodes: `initNodesManager()`
    *   Tools: `initToolsManager()`
    *   Users: `initUsersManager()`
-   **Layout Convention**: Follows a **Master-Detail** pattern: Sidebar on the left (260px, `.agents-sidebar`, with items grouped by node and active styling via `.active`) and Editor form on the right (`.editor-section`).
-   **CSS Class Conventions**:
    *   `.group-header` for Node category headers (gold, uppercase).
    *   `.form-layout-grid` for 3-column form layout: settings (2-col grid using `.form-grid`), prompt textareas, and variables.
    *   Unified input/select/textarea classes: `.form-control`.
    *   Action buttons: `.btn-create` (green), `.btn-save` (blue), `.btn-delete` (red outline).
-   **Common Utilities**: Utilize debouncing (`debounce(fn, ms)`) for search inputs, and escape HTML helper (`escapeHtml(t)`) where rendering dynamic content.
-   **AJAX Fetching**: Import and use fetch wrappers from `/static/js/api.js` (`getData`, `postData`, `putData`, `deleteData`) for error-handled JSON communication.

### D. Authentication & Session-Based RBAC
Auth is fully implemented inside `src/auth/` and verified with `SessionMiddleware` inside `main_uvicorn.py`.
-   **Session Structure**: Uses signed cookies via Starlette's `SessionMiddleware` under the cookie name `uvicorn_session`. Session dictionaries store `user_id`, `username`, and `role`. Password validation is processed via `bcrypt`.
-   **Role-Based Access Control (RBAC)**: Supports roles (`admin`, `user`) mapping to a broad list of enums in `src/auth/auth_permission.py`. While `admin` bypasses checks implicitly, `user` checks permission lists mapped in `AUTH_ROLE_PERMISSIONS` in `src/auth/auth_role.py`.
-   **Protected Endpoints**: Endpoints are protected using the `AuthChecker` dependency injecting requested permissions:
    ```python
    from src.auth.auth import AuthChecker
    from src.auth.auth_permission import AuthPermission

    @router.get("/protected")
    async def get_endpoint(user: AuthSession = Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
        return {"data": "secure"}
    ```

### E. Extending Backend Tools
To add a new custom backend tool to the AI framework:
1.  **Create Tool Module**: Implement the tool logic under a dedicated folder in `src/tool/<name>/<name>.py`. Define its parameters with clear Python type hints and descriptive docstrings.
2.  **Automated Registration**: The framework automatically discovers tools dynamically by parsing the AST of any Python files under the `src/tool/` directory. On server startup, `ai_tool_sync()` (called in `main_uvicorn.py`) scans these directories, extracts tool signatures and descriptions, and registers/synchronizes them into the database (`tool` and `tool_group` tables). To force sync, trigger the `/tool/sync` API endpoint or restart the web server. There is no need to manually register tools in any configuration file or function.

---

## 5. Testing & Verification Requirements

### Mandatory Verification Flow
A change is **not complete** without running the test suite. Gemini CLI MUST follow these rules:
1.  **Test Environment**: Tests are **integration tests** that query a running local Uvicorn instance on `http://localhost:8011`. You must have the uvicorn server running before executing pytest!
2.  **Test Fixtures**: Check `tests/conftest.py`. It includes automatic cleanups (`cleanup_test_users`) which run before and after the session to wipe any test-created DB accounts prefixed with `test_`.
3.  **Command Execution**:
    ```bash
    # Run entire suite (ensure uvicorn is running on 8011!)
    python3 -m pytest tests/ -v

    # Run specific test suite/module
    python3 -m pytest tests/test_user_crud.py -v
    ```

---

## 6. Gemini CLI Operational Directives

When implementing changes, modifying code, or resolving bugs, you must strictly follow these instructions:

-   **Zero Hacks Policy**: Do not introduce casts, suppress warnings, or bypass types unless directly instructed. Maintain strict type safety in Python (use Type Hints and Pydantic models where applicable).
-   **Do Not Stage/Commit unprompted**: Only stage/commit if specifically requested by the user. Propose draft commit messages when asked to commit.
-   **Testing as Finality**: If you add new endpoints or modify logic, write an integration test verifying the behavior under `tests/`. Do not consider a task complete without executing existing tests and adding new coverage where necessary.
-   **Preserve Style**: Match the code patterns, indentation (typically 4 spaces for Python), formatting, and directory layout of the existing application. Refer directly to `CLAUDE.md` if specific implementation nuances need verification.
-   **Headless Tool Compatibility**: Backend tools must remain headless-compatible. Never invoke desktop-oriented or interactive UI actions (like `webbrowser.open()`) inside tool implementations, since they execute in headless Docker containers and VPS environments. Return URLs/links as response strings instead.
-   **Standardized Logging**: Avoid standard `print()` statements for operational logging. Always use the structured logging framework (`from logging_.logging_ import logger_info`).
-   **Unified Configuration Access**: Always retrieve secrets, tokens, and environment parameters using the config manager wrapper (`from config.config import config_get`) instead of directly querying `os.getenv()`.
-   **Safe HTTP Parameter Handling in Tools**: When building backend tools that perform HTTP requests, always pass query parameters as a dictionary via the client (e.g., `params` in `httpx.get(...)`) rather than using direct string interpolation in the URL. This prevents encoding failures on spaces, accents, and special characters.
-   **Strict Headless Compatibility**: Never import or invoke desktop-bound interfaces (e.g., the `webbrowser` module or GUI libraries) in backend tools. All output must be returned strictly as data or text so that it runs safely inside headless containerized and production environments.
-   **File Deletion Rules**: You can ONLY delete files in the current directory (current folder) using explicit local commands. Any command to delete files must start with `rm ./` (e.g., `rm -rf ./`, `rm -f ./`, `rm ./`). Never use commands targeting paths outside the current directory for deletion.
