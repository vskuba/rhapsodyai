# Database Schema & Migrations

## Repositories (`src/mysql_/repository/`)

| Repository | Entity |
|-----------|--------|
| `AgentRepository` | Agent definitions |
| `ToolRepository` / `ToolGroupRepository` | Tools and groups |
| `LLMRepository` | LLM configurations |
| `UserRepository` | User management |
| `AgentWorkflowRepository` / `AgentWorkflowStepRepository` | Workflow definitions |
| `FactCollectionRepository` | Fact collections |
| `NodeRepository` | Workflow nodes |
| `DatingGirlRepository` | Dating app entities |

## Migration System (yoyo-migrations)

Migrations apply automatically on Uvicorn startup via `mysql_migration_up()`. Files are in `/migrations/`.

### File Structure

| File | Purpose |
|------|---------|
| `0001.sql` | DDL schema — CREATE TABLE, FK, indexes for ALL tables across all subprojects |
| `0002.sql` | System seed data (LLM, users, roles, nodes, settings, tools, system workflows: Cashier/Soko/Test/Dev, translator, fact_verify) |
| `0003.sql` | Dating subproject data (node_id=2): workflow, steps, variables, public vars, `dating_bot` agent |
| `0004.sql` | Detective subproject data (node_id=4): workflow, steps, variables, `detective_bot` agent |

Each node (subproject) gets its own migration file. `node.migration_file` stores the path; `mysql_export_node_to_migration(node_id)` exports changes. New subproject = new `000N.sql` with DML for that node; if it needs its own table (like `detective_case`), the DDL goes in `0001.sql`.

### Dynamic Data — Never in Migrations

- `agent.dynamic=1` — agents created at runtime by `agent_create_or_update` (dating girls, detective suspects/sergeant)
- `agent_session`, `detective_case` — conversation/game session history

### Table Order in 0001.sql (FK dependency order)

1. `llm` → 2. `user` → 3. `setting` → 4. `node` → 5. `session` → 6. `tool_group`/`tool` → 7. `agent_workflow`/`step_type`/`step`/`variable` → 8. `fact_collection`/`fact` → 9. `agent` → 10. `agent_session` → 11. `detective_case` (future subproject tables)

### 0001.sql Conventions

- `DROP TABLE IF EXISTS` at the top (clean recreation)
- `SET FOREIGN_KEY_CHECKS = 0/1` around drops to avoid FK errors
- Column comments on non-obvious columns (especially `fact`: `document_id`, `file_id`, `category`, `language`, `tags`, `qdrant_synced`)
- `UNIQUE INDEX` for uniqueness constraints, `INDEX` for search performance

## Changing the Schema

```bash
# 1. Edit 0001.sql (DDL) and/or 0002/0003/0004.sql (data for the relevant subproject)
# 2. Drop and recreate the database:
mysql -u developer -p -h localhost -P 3302 -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 3. Start the server — migrations apply automatically:
python3 main_uvicorn.py
```

In Docker:
```bash
docker-compose exec mysql mysql -u developer -ppassword -e "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
docker-compose restart uvicorn
```

## User Table Auth Columns

```sql
`password_hash` CHAR(100) NOT NULL  -- bcrypt hash
`role` CHAR(20) NOT NULL DEFAULT 'User'  -- 'Admin' | 'User'
```
