# Database — репозитории, схема, миграции

> Список репозиториев `src/mysql_/repository/`, группы таблиц, порядок создания с учётом
> FK и правила правки схемы. Схема живёт в единственном файле `migrations/20260101000000_initial_schema.sql`;
> механика прогона и сидов — `migration.md`.

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
| `20260101000000_initial_schema.sql` | DDL schema — CREATE TABLE, FK, indexes for ALL tables; includes DROP TABLE IF EXISTS at the top for clean recreation |

Seed data (LLM providers, users, roles, nodes, tools, agents, workflows) is managed through the **Seed UI** at `/admin/seed`, not via SQL files. See `seed.md`.

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
- `node_variable`, `node_variable_role`, `node_variable_workflow`
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

### Browser
- `browser_scenario` — UI scenarios: goal + JSON steps (no secrets in `steps`), `site_id` → `browser_site` (ON DELETE SET NULL)
- `browser_scenario_run` — run journal: trace, extract, duration; written on success too
- `browser_error` — error journal: `source`, `message`, `session_id`, `url`, JSON `context` (no FKs on purpose)
- `browser_workflow` — scenario chains: `site_id`, unique `name`, `position`
- `browser_workflow_step` — chain links: `workflow_id` → `scenario_id` (both cascade), `position`
- `browser_site` — bookmarks for the browser container: unique `name` + `url` (scheme required), `position` for the drag-and-drop order, `tags` (comma-separated, lowercase) so neighbours can filter their own sites via `GET /api/browser/site?tag=dating`

## Table Order in 0001.sql (FK dependency order)

1. `llm` → `role` → `user` → `user_access_token`
2. `node` → `setting` → `user_node` → `llm_request` → `node_llm` → `role_node`
3. `session`
4. `tool_group` → `tool`
5. `agent_workflow` → `agent_workflow_step_type` → `agent_workflow_step`
6. `agent_workflow_variable` → `agent_workflow_variable_workflow`
7. `node_variable` → `node_variable_role` → `node_variable_workflow`
8. `companion` → `fact_collection` → `agent` → `agent_role` → `plan` → `fact` → `agent_session`
9. `ai_claude_session` → `ai_claude_session_registry`
10. `agent_workflow_trace` → `agent_workflow_trace_step`
11. `event_log`
12. `project_task` → `developing_project` → `developing_task`
13. `project` → `project_planning_phase_source` → `project_planning_phase` → `project_planning_document`
14. `project_design_prototype_browser_history`
15. `project_state` → `project_design_prototype_page` → `project_design_prototype_widget` → `project_design_prototype_page_block`
16. `project_design_ui_component` → `project_design_ui_block_type` → `project_design_ui_block` → `project_design_ui_block_size` → `project_design_token`
17. `browser_site` → `browser_scenario` → `browser_scenario_run`; `browser_workflow` → `browser_workflow_step`

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

## Connecting to Prod MySQL

Prod MySQL runs in the `rhapsodyai-mysql-1` container on the Oracle A1 host, published as `0.0.0.0:3302 -> 3306`. There is **no `mysql` client on the local host** — every route below ends up inside a container.

Credentials are the same names as locally (`MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` in `.env`; on prod they come from the `ENV_FILE` GitHub secret). Never paste the literal password into a doc, a commit, or a shell transcript — read it from `.env` at call time.

### Route A — one-shot command over SSH (default for schema deltas)

```bash
PW=$(grep '^MYSQL_PASSWORD=' .env | cut -d= -f2-)

ssh -o ClearAllForwardings=yes rhapsody-prod \
  "docker exec -i rhapsodyai-mysql-1 mysql -u developer -p$PW --default-character-set=utf8mb4 project" \
  < delta.sql
```

`-o ClearAllForwardings=yes` is not optional in practice. The `rhapsody-prod` alias carries `LocalForward` for 9634 / 5601 / 3012 / 9181 / 6333 with `ExitOnForwardFailure yes`, and while the local docker-compose stack is up those ports are taken — the session dies with `bind [::1]:9634: Cannot assign requested address` before the remote command ever runs. Clearing the forwards keeps the alias usable without stopping the local stack.

`--default-character-set=utf8mb4` is also not optional: without it the client renders Cyrillic as `??????` even though the stored data is fine.

Drop `-i` and the redirect for an interactive shell; add `-e "SELECT ..."` for a single read-only query.

### Route B — tunnel via `rhapsody-prod-db` (when you need prod and local at once)

For schema diffing, data comparison or any tool that speaks the MySQL protocol, use the dedicated alias:

```bash
ssh -f -N rhapsody-prod-db     # LocalForward 0.0.0.0:3307 -> prod localhost:3302
```

It exists precisely because `rhapsody-prod` cannot coexist with the local stack. It forwards one port, 3307, which nothing local uses, so it can stay up indefinitely alongside `docker-compose`. It binds `0.0.0.0` (not `127.0.0.1`) on purpose — otherwise containers can't reach it through `host.docker.internal`. `AddressFamily inet` avoids the IPv6 bind failure that breaks the other alias.

Through the tunnel, from the local MySQL container:
```bash
docker exec -i $(docker ps --format '{{.Names}}' | grep mysql) \
  mysql -h host.docker.internal -P 3307 -u developer -p"$PW" \
        --default-character-set=utf8mb4 project -e "SHOW TABLES;"
```

Kill it when done: `pkill -f 'ssh.*rhapsody-prod-db'`.

### Cautions

- **Never pipe the initial schema at prod.** It starts with `DROP TABLE IF EXISTS` for every table. The old `USE \`project\`` line is gone (the DB name now comes from the connection), so the file no longer self-selects the live database — but piping it at a live DB still wipes it.
- **The initial schema is frozen** and never re-applies (yoyo marked it applied). New tables and `ALTER TABLE` go into their own timestamped migration in `migrations/` — yoyo applies it on the next start, on every install alike. Editing the frozen file would change an already-applied migration: live DBs would never see it, fresh installs would.
- **Don't run ad-hoc `mysql_pool_get()` scripts against prod** without a guaranteed pool close — leaked connections accumulate on the server.
- Data (not schema) goes through the Seed UI `/admin/seed`; a full dump is `/admin/backup`.

## 0001.sql Conventions

- `DROP TABLE IF EXISTS` at the top (clean recreation on local reset)
- `SET FOREIGN_KEY_CHECKS = 0/1` around drops to avoid FK errors
- Column comments on non-obvious columns
- `UNIQUE INDEX` for uniqueness constraints, `INDEX` for search performance
