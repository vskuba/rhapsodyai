# Database Schema & Migrations

## Repositories (`src/mysql_/repository/`)

| Repository | Entity |
|-----------|--------|
| `AgentRepository` | Agent definitions |
| `AgentWorkflowRepository` / `AgentWorkflowStepRepository` / `AgentWorkflowStepTypeRepository` | Workflow definitions |
| `AgentWorkflowVariableRepository` | Workflow variables |
| `AiClaudeSessionRegistryRepository` | Claude Code terminal sessions |
| `CompanionRepository` | Companions |
| `EventLogRepository` | System event log |
| `FactCollectionRepository` | Fact collections |
| `LLMRepository` | LLM configurations |
| `NodeRepository` | Workflow nodes |
| `PlanRepository` | User plans (Mini App) |
| `ToolRepository` / `ToolGroupRepository` | Tools and groups |
| `UserRepository` / `UserAccessTokenRepository` | User management |
| `project/ProjectRepository` | Planning projects |
| `project/planning/PlanningProjectRepository` | Planning project CRUD |
| `project/planning/PlanningPhaseRepository` | Planning phases |
| `project/planning/PlanningDocumentRepository` | Planning documents |

Design repos are accessed via raw SQL in routers — no separate repository files yet.

## Migration System (yoyo-migrations)

Migrations apply automatically on Uvicorn startup via `mysql_migration_up()`. Files are in `/migrations/`.

### File Structure

| File | Purpose |
|------|---------|
| `0001.sql` | DDL schema — CREATE TABLE, FK, indexes for ALL tables; includes DROP TABLE IF EXISTS at the top for clean recreation |

Seed data (LLM providers, users, roles, nodes, tools, agents, workflows) is managed through the **Seed UI** at `/admin/seed`, not via SQL files. See `.claude/docs/seed.md`.

### Dynamic Data — Never in Migrations

- `agent.dynamic=1` — agents created at runtime (dating girls, etc.)
- `agent_session`, `llm_request` — conversation history / request log

## Table Groups

### Core / Auth
- `role`, `user`, `user_access_token`, `user_node`
- `node`, `setting`, `role_node`, `session`

### LLM
- `llm`, `node_llm`, `llm_request`

### Agents / Workflows
- `agent`, `agent_role`, `companion`
- `agent_workflow`, `agent_workflow_step_type`, `agent_workflow_step`
- `agent_workflow_variable`, `agent_workflow_variable_workflow`
- `agent_workflow_variable_public`, `agent_workflow_variable_public_role`, `agent_workflow_variable_public_workflow`
- `agent_session` — conversation memory
- `agent_workflow_trace`, `agent_workflow_trace_step` — execution trace

### Tools / Facts / Plans
- `tool_group`, `tool`
- `fact_collection`, `fact`
- `plan`
- `event_log`

### Claude Code sessions
- `ai_claude_session` — inbox queue for Mini App → terminal messages
- `ai_claude_session_registry` — active terminal session registry (fields: `session_uuid`, `role`, `project_label`, `status`, `server_llm`, `summary`, `last_seen_at`, `closed_at`)

### Project / Planning
- `project` — planning projects (was `planning_project`)
- `project_planning_phase` — planning phases per project (was `planning_phase`)
- `project_planning_phase_source` — phase templates/sources
- `project_planning_document` — generated documents per project (was `planning_document`)

### Tasks / Developing
- `project_task` — task list linked to project
- `developing_project` — dev-cycle project (links to planning project)
- `developing_task` — dev tasks with role/priority/status

### Project Design
- `project_state` — page state types (anon/auth); seeded: id=1 anon, id=2 auth
- `project_design_prototype_page` — wireframe pages per project
- `project_design_prototype_page_block` — blocks placed in page sections
- `project_design_prototype_widget` — widgets per block
- `project_design_prototype_browser_history` — URL history per project
- `project_design_ui_block_type` — block type categories
- `project_design_ui_block` — reusable UI block library (html/css/vars/slots)
- `project_design_ui_block_size` — measured pixel sizes per viewport
- `project_design_ui_component` — UI component metadata
- `project_design_token` — design token sets (JSON)

## Table Order in 0001.sql (FK dependency order)

1. `llm` → `role` → `user` → `user_access_token`
2. `node` → `setting` → `user_node` → `llm_request` → `node_llm` → `role_node`
3. `session`
4. `tool_group` → `tool`
5. `agent_workflow` → `agent_workflow_step_type` → `agent_workflow_step`
6. `agent_workflow_variable` → `agent_workflow_variable_workflow`
7. `agent_workflow_variable_public` → `agent_workflow_variable_public_role` → `agent_workflow_variable_public_workflow`
8. `companion` → `fact_collection` → `agent` → `agent_role` → `plan` → `fact` → `agent_session`
9. `ai_claude_session` → `ai_claude_session_registry`
10. `agent_workflow_trace` → `agent_workflow_trace_step`
11. `event_log`
12. `project_task` → `developing_project` → `developing_task`
13. `project` → `project_planning_phase_source` → `project_planning_phase` → `project_planning_document`
14. `project_design_prototype_browser_history`
15. `project_state` → `project_design_prototype_page` → `project_design_prototype_widget` → `project_design_prototype_page_block`
16. `project_design_ui_component` → `project_design_ui_block_type` → `project_design_ui_block` → `project_design_ui_block_size` → `project_design_token`

## Changing the Schema

```bash
# 1. Edit 0001.sql (DDL)
# 2. Drop and recreate the database:
mysql -u developer -p -h localhost -P 3302 -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 3. Start the server — migrations apply automatically:
python3 main_uvicorn.py
```

In Docker:
```bash
docker-compose exec rhapsodyai-mysql-1 mysql -u developer -ppassword -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
docker-compose restart uvicorn
```

### Prod schema updates

On prod, `0001.sql` won't re-apply automatically (yoyo tracks it as already applied). Changes to existing tables must be applied manually via `ALTER TABLE` / `RENAME TABLE` / `CREATE TABLE`.

Connect to prod MySQL:
```bash
ssh -o ExitOnForwardFailure=no rhapsody-prod \
  "docker exec rhapsodyai-mysql-1 mysql -u developer -ppassword --default-character-set=utf8mb4 project"
```

Or pipe a SQL file:
```bash
ssh -o ExitOnForwardFailure=no rhapsody-prod \
  "docker exec -i rhapsodyai-mysql-1 mysql -u developer -ppassword --default-character-set=utf8mb4 project" \
  < delta.sql
```

## 0001.sql Conventions

- `DROP TABLE IF EXISTS` at the top (clean recreation on local reset)
- `SET FOREIGN_KEY_CHECKS = 0/1` around drops to avoid FK errors
- Column comments on non-obvious columns
- `UNIQUE INDEX` for uniqueness constraints, `INDEX` for search performance
