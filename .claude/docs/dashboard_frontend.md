# Frontend / Dashboard Architecture (Admin Panel)

The web dashboard is a **server-side rendered Jinja2** application served by FastAPI/Uvicorn. All admin pages are under `/admin/*` routes.

## Template Structure

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

## Base Layout (`base.html`)

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

## Common Page Pattern (Sidebar + Editor)

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

## Shared JS Modules (`data/uvicorn/public/js/`)

| Module | Exports | Purpose |
|--------|---------|---------|
| `api.js` | `getData`, `postData`, `putData`, `deleteData` | Fetch wrappers with error handling, auto-detects `FormData` |
| `notification.js` | `showNotification(msg, type)` | Toast system (success/error/warning/info) with auto-dismiss |
| `setting.js` | `SettingGet(key, user_id)` | User preference persistence |

```javascript
import {getData, putData, postData, deleteData} from '/static/js/api.js';
import {showNotification} from '/static/js/notification.js';
```

## Universal Page Initialization Pattern

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
    document.querySelectorAll('.entity-item').forEach(e => e.classList.remove('active'));
    el.classList.add('active');
    const data = await getData(`/entity/${id}`);
    const entity = data.result;
    document.getElementById('entityId').value = entity.id;
    document.getElementById('name').value = entity.name;
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
        await initManager(id);
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

// 8. Event Listeners (at bottom, NO DOMContentLoaded — modules defer automatically)
initManager();
form.addEventListener('submit', saveConfig);
createBtn.addEventListener('click', resetFormForCreate);
deleteBtn.addEventListener('click', deleteEntity);
```

## Page Types

### A. Master-Detail CRUD (agent.html, node.html, user.html, fact_collection.html)
- Sidebar list grouped by `node_id`, sorted by `position`
- Right panel: 3-col grid (settings | prompt | variables)
- `workflow_variable` edited as dynamic key-value rows → `JSON.stringify()` on save
- Selects (Node, LLM, Workflow) populated in `initManager()` via `Promise.all`

### B. Complex Editor with Sub-Resources (workflow.html)
- **Two modes**: Settings View ↔ Steps View (toggled via sidebar clicks)
- **Steps**: Drag-drop reorder (native HTML5 DnD) → `PUT /workflow/{id}/steps/reorder`
- **Step Types** (`agent_workflow_step_type`): Each has dynamic fields via `WORKFLOW_STEP_CONFIG`
  - `widget_json_variable` — Variable array with "Prompt Updater" button
  - `widget_tool_invoke` — Tool selector + Input/Output mapping to workflow variables
  - `widget_variable_conversion` — Key-value mapping
- **Transitions**: Before/After conditions (variable, operator, value, target_step_id)
- **Variables**: Separate CRUD via `/workflow/{id}/variables`

### C. Read-Only Detail + Test Runner (tool.html)
- **Sidebar**: Collapsible groups (accordion) by `tool_group`
- **Detail View**: Read-only display of `args.input`, `args.output`, `description`
- **Test Runner**: Dynamic form from `args.input` schema → `POST /tool/test/{id}`

### D. Table + Pagination + Filters (fact.html)
- **State object**: `{currentPage, limit, query, collectionId, status}`
- **Debounced search** (500ms): `state.query = input; state.currentPage=1; loadFacts()`
- `/fact/collection/{name}?page&limit&query`
- **Markdown Editor**: CodeMirror integration for fact content

### E. Session Browser (session.html)
- Read-only audit view: filters (Agent, User, Date) + sidebar (sessions) + detail (messages)
- No edit/delete

## CSS Architecture

**Shared styles** (`data/uvicorn/public/css/`):
| File | Scope |
|------|-------|
| `common.css` | Global: body, `.page-content`, `.main-wrapper`, inputs, buttons |
| `menu_top.css` | Top navigation bar (`.top-nav`, `.nav-item`, `.submenu`) |
| `notification.css` | Toast animations (`.notification`, `.fade-out`) |
| `code_mirror_*.css` | CodeMirror editor theming |

Page-specific styles are inlined in `{% block head %}` of each template. Key classes:

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

## API Response Contract

All list endpoints: `{ "result": [...] }`
Single item: `{ "result": {...} }`
Errors: `{ "detail": "message" }` or `{ "status": "error", "message": "..." }`

| Page | List | Get One | Create | Update | Delete | Special |
|------|------|---------|--------|--------|--------|---------|
| Agent | `GET /agent/list` | `GET /agent/{id}` | `POST /agent` | `PUT /agent/{id}` | - | `POST /agent/list` (filter) |
| Workflow | `GET /workflow/list` | `GET /workflow/{id}` | `POST /workflow` | `PUT /workflow/{id}` | `DELETE /workflow/{id}` | `/workflow/{id}/steps`, `/workflow/{id}/variables` |
| Node | `GET /node/list` | - | - | - | - | - |
| User | `GET /user/list` | `GET /user/{id}` | `POST /user` | `PUT /user/{id}` | `DELETE /user/{id}` | - |
| Tool | `GET /tool/list` | - | - | - | - | - |
| LLM | `GET /llm/list` | - | - | - | - | - |
| Fact | `GET /fact/list` | - | - | - | `/fact/collection/{name}?page&limit&query` | - |

Special responses:
- `/workflow/{id}/steps` → `{ "result": [{id, type_id, title, position, metadata, icon}, ...] }`
- `/workflow/{id}/variables` → `{ "result": [{id, name, default, id}, ...] }`

## Common Gotchas

1. **Jinja2 vs JS templating conflict:** Use `{{ '{{' }}` or move complex JS to separate `.js` files
2. **FormData vs JSON:** `api.js` auto-detects `FormData` for file uploads (voice)
3. **Module scripts:** No `DOMContentLoaded` needed — modules defer automatically
4. **Async init:** Call `initManager()` at bottom of script, not in event listener
5. **Variable editor:** Always `JSON.stringify()` before sending `workflow_variable`
6. **Drag-Drop:** Update positions via `PUT /workflow/{id}/steps/reorder` with `{positions: [{id, position}, ...]}`

## Common Utilities

```javascript
// Debounce (fact.html)
function debounce(fn, ms=300) {
    let t; return (...a) => { clearTimeout(t); t=setTimeout(()=>fn(...a), ms); };
}

// Escape HTML
function escapeHtml(t) {
    return (t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Parse metadata JSON with newline fix (workflow.html)
function parseMetadata(v) {
    if (!v) return {};
    if (typeof v !== 'string') return v;
    try { return JSON.parse(v); }
    catch { return JSON.parse(v.replace(/\n/g,'\\n').replace(/\r/g,'\\r').replace(/\t/g,'\\t')); }
}
```

## Adding a New Admin Page (Checklist)

1. **Template:** `data/uvicorn/template/admin/new_entity.html` extends `base.html`
2. **Route:** Add to `src/uvicorn/routers/html.py`
3. **API Router:** `src/uvicorn/routers/new_entity/new_entity.py` with CRUD endpoints
4. **Register:** Import router in `main_uvicorn.py`
5. **Follow pattern:** Copy structure from `agent.html` or `user.html`
6. **Static refs:** `/static/js/api.js`, `/static/js/notification.js`, `/static/css/common.css`

Static files served via:
```python
app.mount("/static", StaticFiles(directory="data/uvicorn/public"), name="static")
```
