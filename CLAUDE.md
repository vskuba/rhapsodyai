# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**RhapsodyAi** is a multi-modal AI agent framework with two operating modes:
1. **Telegram Bot** (`main_telegram.py`) - Telegram-only agent mode
2. **FastAPI/Uvicorn Server** (`main_uvicorn.py`) - Web API with HTML frontend

The project uses a modular architecture with `py_modules/` for shared libraries and `src/` for application-specific code.

## Common Development Commands

### Running the Application

```bash
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
| `flux_schnell/` | Image generation (SDXL-Turbo/Flux) |
| `logging_/` | Structured logging |
| `microphone/` | Speech recognition (speech_recognition library) |
| `mysql_/` | MySQL connection pooling & repositories |
| `queue_/` | In-memory async queue system |
| `redis_/` & `redis_queue/` | Redis connection & RQ queue |
| `qdrant_/ ` | Vector database client |
| `setting_/` | Settings persistence |
| `sqllite3/` | SQLite for LLM short-term memory |
| `state/` | Global state management |
| `thread_/` | Thread utilities |
| `mcp_/` | Model Context Protocol client |
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
queue_init([
    'chat',
    'chat_response', 
    'chat_input_send',
    'task',
    'task_abort',
    'task_complete',
    'task_continue',
    'tool',
    'agent_abort',
    'agent_response',
    'ai_framework_model',
])

# Access queues
from queue_.queue_ import queue_get
queue_get('agent').put(framework_model)
```

Key queues: `chat`, `chat_response`, `chat_input_send`, `task`, `task_abort`, `task_complete`, `task_continue`, `tool`, `agent_abort`, `agent_response`, `ai_framework_model`

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

### Migrations (`/migrations/`)

Проект использует **yoyo-migrations** для управления схемой БД. Миграции применяются автоматически при старте Uvicorn через `mysql_migration_up()`.

**Структура:**
| Файл | Назначение |
|------|------------|
| `0001.sql` | DDL схема (CREATE TABLE, FK, индексы) |
| `0002.sql` | DML сиды (INSERT: LLM, users, nodes, workflows, agents, fact_collections) |
| `0003.sql` | Инкрементальная фича-миграция (детективная игра: таблица `detective_case`, workflow `detective_bot`/`detective_talk`). В отличие от 0001/0002 — идемпотентна (`CREATE TABLE IF NOT EXISTS`, `INSERT IGNORE`), применяется поверх уже существующей БД без полного пересоздания |

**Порядок таблиц в 0001.sql** важен из-за FK:
1. `llm` → 2. `user` → 3. `setting` → 4. `node` → 5. `session` → 6. `tool_group`/`tool` → 7. `agent_workflow`/`step_type`/`step`/`variable` → 8. `dating_girl` → 9. `fact_collection`/`fact` → 10. `agent` → 11. `agent_session`

**Особенности 0001.sql:**
- `DROP TABLE IF EXISTS` в начале (чистое пересоздание)
- `SET FOREIGN_KEY_CHECKS = 0/1` для дропа без ошибок FK
- Комментарии к колонкам (особенно `fact`: `document_id`, `file_id`, `category`, `language`, `tags`, `qdrant_synced`)
- Индексы: `UNIQUE INDEX` (уникальность), `INDEX` (поиск)

**Процесс изменения схемы:**
```bash
# 1. Редактируете 0001.sql (схему) и/или 0002.sql (сиды)
# 2. Очищаете БД полностью:
mysql -u developer -p -h localhost -P 3302 -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 3. Запускаете сервер — миграции применятся автоматически:
python main_uvicorn.py
```

Или внутри Docker:
```bash
docker-compose exec mysql mysql -u developer -ppassword -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
docker-compose restart uvicorn
```

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

### Running Tests

```bash
# Run all tests (requires running uvicorn server on localhost:8011)
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_user_crud.py -v
python3 -m pytest tests/test_login.py -v

# Run specific test
python3 -m pytest tests/test_user_crud.py::TestUserCRUD::test_create_user -v
```

**Test Configuration:**
- Tests are integration tests that require a running uvicorn server on `http://localhost:8011`
- Test fixtures in `tests/conftest.py`:
  - `cleanup_test_users` (session-scoped, autouse) - automatically cleans up test users with `test_` prefix before and after test session
  - `event_loop` - async event loop for pytest-asyncio
- Test users created during tests have usernames prefixed with `test_` (e.g., `test_user_crud`, `test_admin_crud`)
- Cleanup runs automatically via `tests/conftest.py` fixture

**Test Files:**
| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_user_crud.py` | 11 tests | User CRUD: create, read, update, delete, role handling, partial updates |
| `tests/test_login.py` | 19 tests | Auth flow: login, logout, session, protected routes, UI elements |
| `tests/test_agent_crud.py` | 12 tests | Agent CRUD: create, read, update, delete, workflow_variable handling |

### Key Files to Understand

1. `main_uvicorn.py` - Full application bootstrap with all routers
2. `py_modules/ai/framework/ai_framework.py` - Core AI framework base
3. `py_modules/ai/framework/task/ai_framework.py` - Task execution engine
4. `src/uvicorn/routers/` - All API endpoints
5. `src/telegram_bot.py` - Telegram bot handler

## Frontend / Dashboard Architecture (Admin Panel)

The web dashboard is a **server-side rendered Jinja2** application served by FastAPI/Uvicorn. All admin pages are under `/admin/*` routes.

### Template Structure

**Location:** `data/uvicorn/template/`

```
template/
├── base.html                          # Base layout with top navigation
├── login.html                         # Login page (standalone, does NOT extend base.html)
├── admin/
│   ├── chat.html                      # Chat interface with agent/user selectors
│   ├── agent.html                     # Agent CRUD + variable editor
│   ├── workflow.html                  # Workflow + Step editor (complex drag-drop)
│   ├── node.html                      # Node management
│   ├── user.html                      # User management
│   ├── tool.html                      # Tool/ToolGroup management
│   ├── fact.html                      # Fact CRUD
│   ├── fact_collection.html           # Fact Collection management
│   ├── session.html                   # Agent session viewer
│   └── queue.html                     # Queue monitor (in-memory)
```

### Base Layout (`base.html`)

- **Top Navigation Bar** with dropdown menus for:
  - 💬 Chat (→ `/`, `/admin/session`, `/admin/user`)
  - ⛓ Nodes (→ `/admin/node`, `/admin/tool`, `/admin/workflow`, `/admin/agent`)
  - 🔄 Collections (→ `/admin/fact_collection`, `/admin/fact`)
  - 📜 Logs (→ OpenSearch Dashboard)
  - 📊 Queues (→ `/admin/queue`, Redis RQ Dashboard)
  - 🗄️ Databases (→ PhpMyAdmin, Qdrant)
  - ⏰ Scheduler (→ Cronicle)
- **Notification Container** (`#event-notification`) for toast messages
- **Content Block** (`{% block content %}`) for page-specific HTML

### Common Page Pattern (Sidebar + Editor)

All admin pages follow a **Master-Detail** pattern:

```html
<div class="editor-container">
  <!-- LEFT: Sidebar (260px) -->
  <div class="agents-sidebar">
    <div class="sidebar-header">
      <button class="btn-create">+ Create</button>
    </div>
    <div class="agent-list" id="entityList">
      <!-- Grouped by Node: -->
      <div class="group-header">NODE NAME</div>
      <div class="agent-item active">Entity Title</div>
    </div>
  </div>

  <!-- RIGHT: Editor Form -->
  <div class="editor-section">
    <div class="form-header"><h2 id="formTitle">Select entity</h2></div>
    <form id="entityForm">
      <input type="hidden" id="entityId">
      <div class="form-layout-grid">
        <div class="settings-column">
          <!-- Fields in 2-col grid -->
          <div class="form-grid">
            <div class="form-group"><label>Field</label><input class="form-control"></div>
          </div>
        </div>
        <div class="prompt-column">
          <!-- Large textareas (System Prompt, etc.) -->
        </div>
        <div class="variable-column">
          <!-- Dynamic key-value editor -->
        </div>
      </div>
      <div class="editor-footer">
        <button class="btn-save">Save</button>
        <button class="btn-delete">Delete</button>
      </div>
    </form>
  </div>
</div>
```

### JavaScript Architecture (ES Modules)

All pages use **`<script type="module">`** with shared utilities:

**Shared Modules (`data/uvicorn/public/js/`):**
| File | Purpose |
|------|---------|
| `api.js` | `getData()`, `postData()`, `putData()`, `deleteData()` - fetch wrappers with error handling |
| `notification.js` | `showNotification(msg, type)` - toast notifications (success/error/warning/info) |
| `setting.js` | User preference persistence |

**Page Script Pattern:**
```javascript
import {getData, putData, postData, deleteData} from '/static/js/api.js';
import {showNotification} from '/static/js/notification.js';

// 1. DOM references
const listContainer = document.getElementById('entityList');
const form = document.getElementById('entityForm');

// 2. init() - Load lists + populate selects (Nodes, LLMs, Workflows)
async function initManager() {
  const [entitiesRes, nodesRes, llmRes] = await Promise.all([
    getData('/entity/list'), getData('/node/list'), getData('/llm/list')
  ]);
  renderList(entitiesRes.result, nodesRes.result);
  populateSelects(llmRes.result, ...);
}

// 3. renderList() - Groups by node_id, sorts by position
function renderList(entities, nodes) {
  const byNode = entities.reduce((acc, e) => {
    const nid = e.node_id || 'none';
    (acc[nid] ||= []).push(e);
    return acc;
  }, {});
  nodes.forEach(n => renderSection(n.id, n.name));
  renderSection('none', 'Без ноды');
}

// 4. selectForEdit(id, element) - Load single entity, populate form
async function selectForEdit(id, el) {
  document.querySelectorAll('.agent-item').forEach(e => e.classList.remove('active'));
  el.classList.add('active');
  const data = await getData(`/entity/${id}`);
  fillForm(data.result);
}

// 5. saveConfig() - PUT or POST based on hidden ID
async function saveConfig() {
  const payload = collectFormData();
  if (id) await putData(`/entity/${id}`, payload);
  else await postData('/entity', payload);
  await initManager(); // Refresh list
}

// 6. Event listeners (NO DOMContentNeeded - script is module)
initManager();
```

### CSS Architecture

**Shared styles** (`data/uvicorn/public/css/`):
| File | Scope |
|------|-------|
| `common.css` | Global: body, `.page-content`, `.main-wrapper`, `.sidebar`, inputs, buttons |
| `menu_top.css` | Top navigation bar (`.top-nav`, `.nav-item`, `.submenu`) |
| `notification.css` | Toast animations (`.notification`, `.fade-out`) |
| `code_mirror_*.css` | CodeMirror editor theming |

**Page-specific styles:** Inlined in `{% block head %}` of each template (duplicated for isolation). Key classes:
- `.editor-container` - Flex layout (sidebar + editor)
- `.agents-sidebar` / `.user-list` - Left column
- `.group-header` - Node group label (gold text, uppercase)
- `.agent-item` / `.user-item` - List items with hover/active states
- `.form-layout-grid` - 3-column: settings | prompt | variables
- `.form-grid` - 2-col grid inside settings column
- `.form-control` - Unified input/textarea/select styling
- `.btn-create` (green), `.btn-save` (blue), `.btn-delete` (red outline)
- `.variable-row` - Dynamic key-value pair with delete button
- `.steps-sortable-list` / `.step-item-block` - Drag-drop workflow steps

### Key Pages Deep Dive

#### 1. **Chat** (`chat.html`)
- **Purpose:** Live chat with agents
- **Selectors:** `#userSelect` (users), `#agentSelect` (grouped by node), `#llmModelSelect`
- **Flow:** Select user → loads agents filtered by user role → select agent → loads last session → chat
- **WebSocket/HTTP:** REST polling via `/chat/ask`, `/chat/voice`, `/chat/messages`
- **Voice:** MediaRecorder API → `/chat/voice` (multipart/form-data)

#### 2. **Agent** (`agent.html`)
- **Features:** CRUD + `workflow_variable` JSON editor (dynamic key-value rows)
- **Selects:** Node, LLM, Workflow (populated on init)
- **Data:** `agent.workflow_variable` stored as JSON string in DB

#### 3. **Workflow** (`workflow.html`) — Most Complex
- **Two Modes** (toggled via sidebar):
  1. **Settings View** — Workflow metadata (title, name, node, position, description, variables)
  2. **Steps View** — Drag-drop step editor
- **Step Types** (from `agent_workflow_step_type`):
  - `return_response_llm`, `llm_to_json`, `tool_invoke`, `return_response_text`, `variable_conversion`
- **Dynamic Fields** per step type via `WORKFLOW_STEP_CONFIG`:
  - `widget_json_variable` — Variable array with "Prompt Updater" button
  - `widget_tool_invoke` — Tool selector + Input/Output mapping to workflow variables
  - `widget_variable_conversion` — Key-value mapping
- **Transitions:** Before/After conditions (variable, operator, value, target step)
- **Drag-Drop:** Native HTML5 DnD for step reordering → `/workflow/{id}/steps/reorder`

#### 4. **User** (`user.html`)
- Simple CRUD: username, email, llm_id
- **Note:** No role selector in UI yet (role stored in `user.role` column)

### API Contract (Expected by Frontend)

All list endpoints return `{ "result": [...] }`. Single item: `{ "result": {...} }`.

| Page | List | Get One | Create | Update | Delete | Special |
|------|------|---------|--------|--------|--------|---------|
| Agent | `GET /agent/list` | `GET /agent/{id}` | `POST /agent` | `PUT /agent/{id}` | - | `POST /agent/list` (filter) |
| Workflow | `GET /workflow/list` | `GET /workflow/{id}` | `POST /workflow` | `PUT /workflow/{id}` | `DELETE /workflow/{id}` | `/workflow/{id}/steps`, `/workflow/{id}/variables` |
| Node | `GET /node/list` | - | - | - | - | - |
| User | `GET /user/list` | `GET /user/{id}` | `POST /user` | `PUT /user/{id}` | `DELETE /user/{id}` | - |
| Tool | `GET /tool/list` | - | - | - | - | - |
| LLM | `GET /llm/list` | - | - | - | - | - |
| Fact | `GET /fact/list` | - | - | - | - | - |

### Adding a New Admin Page

1. **Create template:** `data/uvicorn/template/admin/new_page.html` extending `base.html`
2. **Add route:** In `src/uvicorn/routers/html.py`:
   ```python
   @router.get("/admin/new_page", response_class=HTMLResponse)
   async def new_page(request: Request):
       return request.app.state.jinja2_template.TemplateResponse(request, "admin/new_page.html")
   ```
3. **Follow pattern:** Copy structure from `agent.html` or `user.html`
4. **Add API endpoints** in `src/uvicorn/routers/new_entity/new_entity.py`
5. **Register router** in `main_uvicorn.py`

### Static Files Serving

In `main_uvicorn.py`:
```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="data/uvicorn/public"), name="static")
```
Templates reference: `/static/js/api.js`, `/static/css/common.css`

### Common Gotchas

1. **Jinja2 vs JS templating conflict:** Use `{{ '{{' }}` or move complex JS to separate `.js` files
2. **FormData vs JSON:** `api.js` auto-detects `FormData` for file uploads (voice)
3. **Module scripts:** No `DOMContentLoaded` needed — modules defer automatically
4. **Async init:** Call `initManager()` at bottom of script, not in event listener
5. **Variable editor:** Always `JSON.stringify()` before sending `workflow_variable`
6. **Drag-Drop:** Update positions via `PUT /workflow/{id}/steps/reorder` with `{positions: [{id, position}, ...]}`

## JavaScript Architecture & Common Patterns (Admin Dashboard)

All admin pages use **Vanilla JS ES Modules** (`<script type="module">`) with a consistent architecture.

### 1. Shared Modules (`data/uvicorn/public/js/`)

| Module | Exports | Purpose |
|--------|---------|---------|
| `api.js` | `getData`, `postData`, `putData`, `deleteData` | Fetch wrappers with error handling, auto-detects `FormData` |
| `notification.js` | `showNotification(msg, type)` | Toast system (success/error/warning/info) with auto-dismiss |
| `setting.js` | `SettingGet(key, user_id)` | User preference persistence |

**Usage pattern:**
```javascript
import {getData, putData, postData, deleteData} from '/static/js/api.js';
import {showNotification} from '/static/js/notification.js';
```

### 2. Universal Page Initialization Pattern

Every admin page follows this structure:

```javascript
// 1. DOM References (cached at top)
const listContainer = document.getElementById('entityList');
const form = document.getElementById('entityForm');
const saveBtn = document.getElementById('saveBtn');
const createBtn = document.getElementById('createNewEntity');
const deleteBtn = document.getElementById('deleteBtn');

// 2. initManager() - Load all reference data + render list
async function initManager(activeId = null) {
    try {
        const [entitiesRes, refsRes] = await Promise.all([
            getData('/entity/list'),
            getData('/reference/list') // nodes, llms, workflows, etc.
        ]);
        renderList(entitiesRes.result, refsRes.result);
        
        // Auto-select first or previously active
        if (activeId) selectById(activeId);
        else selectFirst();
    } catch (e) { console.error(e); }
}

// 3. renderList(items, refs) - Group by node_id, sort by position
function renderList(entities, nodes) {
    listContainer.innerHTML = '';
    const byNode = entities.reduce((acc, e) => {
        const nid = e.node_id || 'none';
        (acc[nid] ||= []).push(e);
        return acc;
    }, {});
    
    // Sort nodes by position
    nodes.sort((a, b) => (a.position||0) - (b.position||0));
    
    nodes.forEach(n => renderSection(n.id, n.name));
    renderSection('none', 'Без ноды');
}

function renderSection(nid, title) {
    if (!byNode[nid]) return;
    const header = document.createElement('div');
    header.className = 'group-header';
    header.textContent = title;
    listContainer.appendChild(header);
    
    byNode[nid].sort((a,b) => (a.title||a.name).localeCompare(b.title||b.name))
        .forEach(e => {
            const div = document.createElement('div');
            div.className = 'entity-item';
            div.textContent = e.title || e.name;
            div.onclick = () => selectForEdit(e.id, div);
            listContainer.appendChild(div);
        });
}

// 4. selectForEdit(id, element) - Load single entity, populate form
async function selectForEdit(id, el) {
    // Highlight
    document.querySelectorAll('.entity-item').forEach(e => e.classList.remove('active'));
    el.classList.add('active');
    
    const data = await getData(`/entity/${id}`);
    const entity = data.result;
    
    // Fill form fields
    document.getElementById('entityId').value = entity.id;
    document.getElementById('name').value = entity.name;
    // ... other fields
    
    document.getElementById('formTitle').textContent = `Editing: ${entity.name}`;
    saveBtn.disabled = false;
    deleteBtn.style.display = 'block';
}

// 5. resetFormForCreate() - Clear form for new entity
function resetFormForCreate() {
    document.querySelectorAll('.entity-item').forEach(e => e.classList.remove('active'));
    form.reset();
    document.getElementById('entityId').value = '';
    document.getElementById('formTitle').textContent = 'New Entity';
    saveBtn.disabled = false;
    deleteBtn.style.display = 'none';
}

// 6. saveConfig() - PUT or POST based on hidden ID
async function saveConfig(e) {
    e.preventDefault();
    const id = document.getElementById('entityId').value;
    const payload = collectFormData();
    
    saveBtn.disabled = true;
    try {
        if (id) {
            await putData(`/entity/${id}`, payload);
            showNotification(`Updated: ${payload.name}`, 'success');
        } else {
            await postData('/entity', payload);
            showNotification(`Created: ${payload.name}`, 'success');
        }
        await initManager(id); // Refresh list, preserve selection
        if (!id) resetFormForCreate();
    } catch (err) {
        showNotification(`Error: ${err.message}`, 'error');
    } finally {
        saveBtn.disabled = false;
    }
}

// 7. deleteEntity()
async function deleteEntity() {
    const id = document.getElementById('entityId').value;
    const name = document.getElementById('name').value;
    if (!confirm(`Delete "${name}"?`)) return;
    
    try {
        await deleteData(`/entity/${id}`);
        showNotification(`Deleted: ${name}`, 'success');
        resetFormForCreate();
        await initManager();
    } catch (err) {
        showNotification(`Error: ${err.message}`, 'error');
    }
}

// 8. Event Listeners (at bottom, NO DOMContentLoaded)
initManager();
form.addEventListener('submit', saveConfig);
createBtn.addEventListener('click', resetFormForCreate);
deleteBtn.addEventListener('click', deleteEntity);
```

### 3. Key Patterns by Page Type

#### A. **Master-Detail CRUD** (agent.html, node.html, user.html, fact_collection.html)
- Sidebar list grouped by `node_id`, sorted by `position`
- Right panel: 3-col grid (settings | prompt | variables)
- `workflow_variable` edited as dynamic key-value rows → `JSON.stringify()` on save
- Selects (Node, LLM, Workflow) populated in `initManager()` via `Promise.all`

#### B. **Complex Editor with Sub-Resources** (workflow.html)
- **Two modes**: Settings View ↔ Steps View (toggled via sidebar clicks)
- **Steps**: Drag-drop reorder (native HTML5 DnD) → `PUT /workflow/{id}/steps/reorder`
- **Step Types** (`agent_workflow_step_type`): Each has dynamic fields via `WORKFLOW_STEP_CONFIG`
  - `widget_json_variable` — Variable array with "Prompt Updater" button
  - `widget_tool_invoke` — Tool selector + Input/Output mapping to workflow variables
  - `widget_variable_conversion` — Key-value mapping
- **Transitions**: Before/After conditions (variable, operator, value, target_step_id)
- **Variables**: Separate CRUD via `/workflow/{id}/variables`

#### C. **Read-Only Detail + Test Runner** (tool.html)
- **Sidebar**: Collapsible groups (accordion) by `tool_group`
- **Detail View**: Read-only display of `args.input`, `args.output`, `description`
- **Test Runner**: Dynamic form generation from `args.input` schema
  - Type-aware inputs: text/number/checkbox/textarea (for dict/list)
  - JSON Pretty/Minify buttons for complex types
  - Client-side validation → `POST /tool/test/{id}` → formatted result display

#### D. **Table + Pagination + Filters** (fact.html)
- **Layout**: Horizontal filter bar (collection select, search, status) + full-width table
- **State object**: `{currentPage, limit, query, collectionId, status}`
- **Debounced search** (500ms): `state.query = input; state.currentPage=1; loadFacts()`
- **Pagination**: `loadFacts()` calls `/fact/collection/{name}?page&limit&query`
- **Inline delete**: `window.deleteFact = async (id) => { await fetch(...); loadFacts(); }`
- **Markdown Editor**: CodeMirror integration for fact content

#### F. **Session Browser** (session.html)
- **Layout**: Horizontal filters (Agent, User, Date) + Sidebar (sessions) + Detail (messages)
- **Session List**: Cards with UUID, message count, date
- **Detail**: Rendered messages with role badges (system/user/llm)
- **No edit/delete** — read-only audit view

### 4. CSS Class Conventions (Consistent Across Pages)

| Purpose | Class | Used In |
|---------|-------|---------|
| Layout | `.editor-container`, `.agents-sidebar`, `.editor-section` | All CRUD pages |
| List Group | `.group-header` (gold, uppercase), `.agent-item`/`.user-item`/`.node-item` | All sidebars |
| Active Item | `.active` (blue left border, bg `#eef6fc`) | All lists |
| Form Grid | `.form-layout-grid` (3-col), `.form-grid` (2-col), `.form-group` | All forms |
| Inputs | `.form-control` (unified input/select/textarea) | All forms |
| Buttons | `.btn-create` (green), `.btn-save` (blue), `.btn-delete` (red outline) | All footers |
| Variables | `.variable-row` (key + value + delete btn) | agent, workflow |
| Tables | `.fact-table` (sticky header, fixed col widths) | fact.html |
| Badges | `.status-badge.synced/.pending`, `.tag-chip` | fact, tool |
| Accordion | `.group-header.collapsed`, `.group-wrapper.collapsed` | tool.html |

### 5. API Response Contract (Expected by Frontend)

All list endpoints: `{ "result": [...] }`
Single item: `{ "result": {...} }`
Errors: `{ "detail": "message" }` or `{ "status": "error", "message": "..." }`

Special:
- `/workflow/{id}/steps` → `{ "result": [{id, type_id, title, position, metadata, icon}, ...] }`
- `/workflow/{id}/variables` → `{ "result": [{id, name, default, id}, ...] }`
- `/fact/collection/{name}?page&limit&query` → `{ "result": [...], "pagination": {current_page, total_pages, total_records} }`

### 6. Common Utilities (Copied/Reused)

```javascript
// Debounce (fact.html)
function debounce(fn, ms=300) {
    let t; return (...a) => { clearTimeout(t); t=setTimeout(()=>fn(...a), ms); };
}

// Escape HTML (fact.html)
function escapeHtml(t) {
    return (t||'').replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>');
}

// Parse metadata JSON with newline fix (workflow.html)
function parseMetadata(v) {
    if (!v) return {};
    if (typeof v !== 'string') return v;
    try { return JSON.parse(v); }
    catch { return JSON.parse(v.replace(/\n/g,'\\n').replace(/\r/g,'\\r').replace(/\t/g,'\\t')); }
}
```

### 7. Adding a New Admin Page (Checklist)

1. **Template:** `data/uvicorn/template/admin/new_entity.html` extends `base.html`
2. **Route:** Add to `src/uvicorn/routers/html.py`
3. **API Router:** `src/uvicorn/routers/new_entity/new_entity.py` with CRUD endpoints
4. **Register:** Import router in `main_uvicorn.py`
5. **Follow pattern:** Copy structure from `agent.html` or `user.html`
6. **Static refs:** `/static/js/api.js`, `/static/js/notification.js`, `/static/css/common.css`

## Authentication & Authorization System

The project has a **session-based authentication** system with **role-based access control (RBAC)**.

### File Structure

```
src/
├── auth/
│   ├── auth.py              # Main AuthChecker dependency, get_current_user()
│   ├── auth_session.py      # AuthSession Pydantic model
│   ├── auth_role.py         # AuthRole enum + AUTH_ROLE_PERMISSIONS mapping
│   └── auth_permission.py   # AuthPermission enum
└── uvicorn/routers/auth/
    └── auth.py              # /auth/login, /auth/logout, /auth/me endpoints

data/uvicorn/template/
└── login.html               # Login page (standalone, not extending base.html)
```

### Core Components

#### 1. **Session Middleware** (`main_uvicorn.py:144-155`)
```python
Middleware(
    SessionMiddleware,  # type: ignore
    secret_key=config_get('SESSION_SECRET_KEY'),
    session_cookie="uvicorn_session",
    max_age=3600,           # 1 hour
    same_site="lax",
    https_only=False
),
Middleware(BaseHTTPMiddleware, dispatch=auth_middleware),
```
- Uses **Starlette's `SessionMiddleware`** (signed cookies, client-side storage)
- Cookie name: `uvicorn_session`
- Requires `SESSION_SECRET_KEY` in `.env`
- Custom `auth_middleware` protects admin routes, redirects unauthenticated users to `/login`

#### 2. **AuthSession Model** (`src/auth/auth_session.py`)
```python
class AuthSession(BaseModel):
    user_id: int
    username: str
    role: str   # "admin" | "user"
```

#### 3. **Permissions** (`src/auth/auth_permission.py`)
```python
class AuthPermission(str, Enum):
    # User permissions
    USERS_VIEW = "users:view"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"

    # Agent permissions
    AGENT_VIEW = "agent:view"
    AGENT_CREATE = "agent:create"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"

    # Workflow permissions
    WORKFLOW_VIEW = "workflow:view"
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"

    # Node permissions
    NODE_VIEW = "node:view"
    NODE_CREATE = "node:create"
    NODE_UPDATE = "node:update"
    NODE_DELETE = "node:delete"

    # Tool permissions
    TOOL_VIEW = "tool:view"
    TOOL_CREATE = "tool:create"
    TOOL_UPDATE = "tool:update"
    TOOL_DELETE = "tool:delete"
    TOOL_TEST = "tool:test"

    # LLM permissions
    LLM_VIEW = "llm:view"
    LLM_CREATE = "llm:create"
    LLM_UPDATE = "llm:update"
    LLM_DELETE = "llm:delete"

    # Fact permissions
    FACT_VIEW = "fact:view"
    FACT_CREATE = "fact:create"
    FACT_UPDATE = "fact:update"
    FACT_DELETE = "fact:delete"

    # Fact Collection permissions
    FACT_COLLECTION_VIEW = "fact_collection:view"
    FACT_COLLECTION_CREATE = "fact_collection:create"
    FACT_COLLECTION_UPDATE = "fact_collection:update"
    FACT_COLLECTION_DELETE = "fact_collection:delete"

    # Session permissions
    SESSION_VIEW = "session:view"

    # Setting permissions
    SETTING_VIEW = "setting:view"
    SETTING_UPDATE = "setting:update"

    # Queue permissions
    QUEUE_VIEW = "queue:view"
```

#### 4. **Roles & Permissions Map** (`src/auth/auth_role.py`)
```python
class AuthRole(str, Enum):
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"


AUTH_ROLE_PERMISSIONS = {
    AuthRole.ROLE_USER: {
        AuthPermission.USER_VIEW,
        AuthPermission.AGENT_VIEW,
        AuthPermission.WORKFLOW_VIEW,
        AuthPermission.NODE_VIEW,
        AuthPermission.TOOL_VIEW,
        AuthPermission.LLM_VIEW,
        AuthPermission.FACT_VIEW,
        AuthPermission.FACT_COLLECTION_VIEW,
        AuthPermission.SESSION_VIEW,
        AuthPermission.SETTING_VIEW,
        AuthPermission.QUEUE_VIEW,
    },
    # Admin gets all permissions implicitly in AuthChecker
}
```

#### 5. **AuthChecker Dependency** (`src/auth/auth.py`)
```python
class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> AuthSession:
        current_user = await get_current_user(request)

        logger_info('🔒 Текущий пользователь: ' + str(current_user))

        if current_user.role == "admin":
            return current_user

        user_permissions = AUTH_ROLE_PERMISSIONS.get(current_user.role, [])

        # Check if user has ALL required permissions for the endpoint
        for perm in self.required_permissions:
            if perm not in user_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас недостаточно прав для выполнения этой операции"
                )

        return current_user
```

**Usage in routers:**
```python
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

@router.get("/protected")
async def protected_endpoint(user: AuthSession = Depends(AuthChecker([AuthPermission.USER_VIEW]))):
    return {"user": user.username}
```

#### 6. **get_current_user() Implementation** (`src/auth/auth.py:34-46`)
```python
async def get_current_user(request: Request) -> AuthSession:
    """Extract user from session cookie."""
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    role = request.session.get("role")

    if not user_id or not username or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    return AuthSession(user_id=user_id, username=username, role=role)
```
- **Fully implemented** — extracts `user_id`, `username`, `role` from `request.session`
- Raises `401 Unauthorized` if session is missing or incomplete
- No hardcoded fallback — pure session-based auth

#### 7. **Login/Logout/Me Endpoints** (`src/uvicorn/routers/auth/auth.py`)
```python
import bcrypt
from fastapi import APIRouter, Request, HTTPException
from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.post("/auth/login")
async def login(request: Request, data: dict):
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, username, email, password_hash, role, llm_id FROM `user` WHERE username = %s",
            (username,)
        )
        user = await db.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password with bcrypt
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create session
    request.session["user_id"] = user['id']
    request.session["username"] = user['username']
    request.session["role"] = user['role']

    return {
        "message": "Успешный вход! Сессия создана.",
        "user": {
            "id": user['id'],
            "username": user['username'],
            "email": user['email'],
            "role": user['role']
        }
    }


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Сессия успешно завершена."}


@router.get("/auth/me")
async def me(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, username, email, role, llm_id FROM `user` WHERE id = %s",
            (user_id,)
        )
        user = await db.fetchone()

    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="User not found")

    return {"user": user}
```

- **Login**: Queries DB for user by username, verifies `password_hash` with `bcrypt.checkpw`, creates session with `user_id`, `username`, `role`
- **Logout**: POST endpoint that clears session
- **Me**: Returns current user info from DB (validates session still matches a valid user)

#### 8. **Login Page** (`data/uvicorn/template/login.html`)
- **Standalone** (does NOT extend `base.html`) — clean centered card
- POSTs to `/auth/login` with `username` + `password`
- Uses shared CSS classes: `.form-input`, `.form-label`, `.login-btn`
- Loads `/static/js/api.js` and `/static/js/notification.js`

### Database Integration (Implemented)

The `user` table has a `password_hash` column and `role` column:
```sql
`password_hash` CHAR(100) NOT NULL  -- bcrypt hash
`role` CHAR(20) NOT NULL DEFAULT 'User'  -- 'Admin' | 'User'
```

- **bcrypt hashing** implemented in `/auth/login` endpoint
- **DB credential check** implemented — queries user by username, verifies password_hash
- Migration handles schema updates

### Adding Protected Endpoints

1. **Define permission** in `auth_permission.py`
2. **Add to role map** in `auth_role.py`
3. **Use dependency** in router:
```python
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

@router.get("/my-endpoint")
async def my_endpoint(user: AuthSession = Depends(AuthChecker([AuthPermission.MY_PERMISSION]))):
    ...
```

### Field-Level Access Policy (сохранение полей для не-админов)

Поверх RBAC-проверок на уровне эндпоинтов есть **политика доступа на уровне полей** — она определяет, какие именно колонки сущности роль может читать и сохранять.

**Файл:** `src/auth/auth_field_policy.py`

```python
ALL_FIELDS = '*'  # маркер "все поля"

AUTH_FIELD_POLICY = {
    'agent_workflow_variable': {
        'fields': {'name', 'description', 'default', 'workflow_id', 'node_id', 'pattern'},  # колонки таблицы
        'write': {
            '*': {'default'},  # любая не-админская роль пишет только `default`
            # 'manager_dating': {'default', 'description'},  # точечная настройка конкретной роли
        },
        'read': {
            '*': ALL_FIELDS,
        },
    },
}
```

**Структура политики:** `entity → action ('write'|'read') → role → set полей`. Роли динамические (таблица `role`), поэтому ключ `'*'` — fallback для любой не-админской роли; конкретная роль переопределяет `'*'`. Роль `admin` в политике не описывается — она всегда получает `ALL_FIELDS`.

**Функции:**

| Функция | Назначение |
|---------|------------|
| `auth_fields_allowed(entity, action, role)` | Возвращает `ALL_FIELDS` (для admin или политики `'*'`) либо `set` разрешённых полей |
| `auth_fields_filter_for_update(entity, action, role, data)` | Возвращает `(fields, data)`: список полей сущности для SQL SET и отфильтрованный payload — оба урезаны до разрешённых роли полей |

**Применение в роутере** (`src/uvicorn/routers/workflow/workflow_variable.py`):

```python
# PUT /agent_workflow_variable/{id} — сохранение
@router.put("/agent_workflow_variable/{variable_id}")
async def variable_update(request: Request, variable_id: int, data: dict,
                          user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_UPDATE]))):
    # Не-админ: из payload остаются только разрешённые поля (по умолчанию — `default`)
    fields, data = auth_fields_filter_for_update('agent_workflow_variable', 'write', user.role, data)

    if fields:
        set_clause = ', '.join(f"`{f}`=%s" for f in fields)  # динамический UPDATE только разрешённых колонок
        await db.execute(f"UPDATE agent_workflow_variable SET {set_clause} WHERE id=%s", [data[f] for f in fields] + [variable_id])

    # Связи (role_ids) обновляются только если поле пережило фильтрацию
    if 'role_ids' in data:
        ...

# GET /agent_workflow_variable/list — чтение
allowed = auth_fields_allowed('agent_workflow_variable', 'read', user.role)
if allowed != ALL_FIELDS:
    results = [{k: v for k, v in row.items() if k in allowed} for row in results]
```

**Ключевые моменты:**
- Эндпоинт-уровень (`AuthChecker` + permission) и поле-уровень (`AUTH_FIELD_POLICY`) — независимые слои: сначала проверяется permission, затем payload режется по политике
- Для workflow-переменных заведены отдельные permissions `WORKFLOW_VARIABLE_VIEW` / `WORKFLOW_VARIABLE_UPDATE` (в `AUTH_PERMISSIONS_DEFAULT`), чтобы обычные пользователи могли сохранять `default` переменных, не имея `WORKFLOW_UPDATE`
- `variable_list` дополнительно фильтрует **строки** для не-админов: только переменные из нод пользователя (`user_node`) и только без ролей либо с совпадающей ролью (`agent_workflow_variable_role`)
- Поля-связи (например `role_ids`), не являющиеся колонками таблицы, в `fields` не попадают, но фильтруются в `data` — обновление связей выполняется только если поле разрешено роли

**Добавление политики для новой сущности:**
1. Добавить ключ сущности в `AUTH_FIELD_POLICY` с `fields` (колонки таблицы) и правилами `write`/`read`
2. В PUT-роутере заменить статический UPDATE на `auth_fields_filter_for_update()` + динамический SET
3. В list/get-роутере отфильтровать ответ через `auth_fields_allowed(entity, 'read', user.role)`

### Current State Summary

| Component | Status |
|-----------|--------|
| Session Middleware | ✅ Configured |
| Session Cookie | ✅ `uvicorn_session` |
| Login/Logout/Me Routes | ✅ Fully implemented |
| Login Page | ✅ `login.html` |
| RBAC Model | ✅ Roles + Permissions enums (60+ permissions) |
| AuthChecker Dependency | ✅ Implemented (async, Request-aware) |
| `get_current_user()` | ✅ **Implemented** — extracts from session |
| Password Hashing | ✅ **bcrypt implemented** in `/auth/login` |
| DB Credential Check | ✅ **Implemented** in `/auth/login` |
| Protected Endpoints | ✅ **20+ endpoints** across 10+ routers using `AuthChecker` with specific permissions |
| Field-Level Policy | ✅ `auth_field_policy.py` — per-role field read/write filtering (`agent_workflow_variable`) |