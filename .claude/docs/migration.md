# Migration & Seed System

## Последовательность при старте

```
main_uvicorn.py → mysql_migration_up() → mysql_seed_up()
```

## 1. Миграция схемы — `mysql_migration_up()`

**Файл:** `py_modules/mysql_/migration/mysql_migration_up.py`  
**Движок:** [yoyo-migrations](https://ollycope.com/software/yoyo/latest/)  
**Папка:** `migrations/`

### Два шага

1. **Создаёт БД**, если не существует:
   ```python
   cursor.execute("CREATE DATABASE IF NOT EXISTS `project` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
   ```
   Подключается без указания DB (только host/user/pass), затем переключается на `project`.

2. **Запускает yoyo** — применяет все `.sql` файлы из `migrations/` в алфавитном порядке. Статус хранится в служебной таблице `_yoyo_migration`. При каждом старте — только новые файлы (diff).

### Единственный файл: `migrations/0001.sql`

Содержит полную схему БД:
```sql
CREATE DATABASE IF NOT EXISTS `project` ...;
USE `project`;
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS `project_design_prototype_page_block`;
-- ... все таблицы в порядке FK-зависимостей ...
CREATE TABLE `node` (...);
-- ...
SET FOREIGN_KEY_CHECKS = 1;
```

- `DROP TABLE IF EXISTS` + `CREATE TABLE` — идемпотентно
- Не содержит никаких данных

> ⚠️ **Файл сам выбирает БД.** Из-за `USE \`project\`` во второй строке команда вида
> `mysql ... schema_check < migrations/0001.sql` **не** проверяет схему в песочнице:
> MySQL переключается на `project` и сносит рабочую базу. Чтобы прогнать схему с нуля
> в отдельную БД, сначала срезать первые две строки (`sed '1,2d'`).

**Правило:** `0001.sql` — единственная миграция. Новые таблицы добавлять сюда же (или создавать `0002.sql`, если изменения несовместимы с существующей БД).

## 2. Seed данных — `mysql_seed_up()`

**Файл:** `src/mysql_/seed/mysql_seed_up.py`  
**Папка:** `data/seeds/`

Загружает начальные архитектурные данные (ноды, агенты, workflow, LLM и т.д.) в свежую БД.

### Логика выполнения

1. Ищет последний файл по имени (reverse sort): `seed_YYYY-MM-DD_HH-MM-SS.sql`
2. Проверяет свежесть БД: `SELECT COUNT(*) FROM node`
   - count == 0 → применяем seed
   - count > 0 → пропускаем
   - `pymysql.Error` (таблица не существует и т.п.) → пропускаем (`return False`)
3. Парсит SQL через `_mysql_seed_split` — корректный сплиттер, игнорирует `;` внутри строк
4. Выполняет все statements через pymysql, при ошибке — `rollback`

### Формат seed-файла

```sql
-- Seed SQL
-- Generated: 2026-07-31 09:46:46
-- Tables: node, llm, role, ...

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- TABLE: node
INSERT IGNORE INTO `node` (`id`, `name`, ...) VALUES
  (1, 'Dashboard', ...),
  (2, 'Dating', ...);

-- TABLE: llm
INSERT IGNORE INTO `llm` (...) VALUES ...;

SET FOREIGN_KEY_CHECKS = 1;
```

`INSERT IGNORE` — безопасно при повторном запуске (существующие записи не перезаписываются).

## 3. Генерация seed через UI

`/admin/seed` — страница управления seed-файлами.

### API эндпоинты (`src/uvicorn/routers/seed/seed.py`)

| Метод | URL | Действие |
|-------|-----|----------|
| `GET` | `/seed/tables` | Список всех таблиц БД, сгруппированных по префиксу; возвращает также сохранённый выбор из `setting.seed_table_config` |
| `POST` | `/seed/config` | Сохранить выбор таблиц в `setting.seed_table_config` |
| `GET` | `/seed/files` | Список файлов в `data/seeds/` |
| `POST` | `/seed/generate` | Создать `data/seeds/seed_YYYY-MM-DD_HH-MM-SS.sql` из переданного списка таблиц |
| `POST` | `/seed/apply/{filename}` | Применить seed-файл к текущей БД (использует свой `_seed_split_sql`) |
| `GET` | `/seed/download/{filename}` | Скачать файл |
| `DELETE` | `/seed/{filename}` | Удалить файл |

> **Два парсера:** `_mysql_seed_split` в `mysql_seed_up.py` (авто-старт) и `_seed_split_sql` в `seed.py` (ручное применение через UI) — одинаковая логика, разные функции.

### Какие таблицы включать в seed

**Включать** (архитектурные данные):  
`node`, `llm`, `node_llm`, `role`, `role_node`, `setting`, `agent_workflow_step_type`, `agent_workflow_variable`, `agent_workflow`, `agent_workflow_step`, `agent_workflow_variable_*`, `agent`, `agent_role`, `planning_phase`, `planning_phase_source`, `fact_collection`, `user`, `user_access_token`, `user_node`

**Не включать** (динамические/runtime данные):  
`tool`, `tool_group` — генерируются через `ai_tool_sync()` при каждом старте  
`companion` — создаётся динамически  
`session`, `agent_session`, `agent_workflow_trace`, `agent_workflow_trace_step`, `llm_request`, `plan` — runtime/logs

## 4. Backup через UI

`/admin/backup` — полный дамп БД:

- `POST /backup/create` → mysqldump (или Python-fallback) + gzip → `data/backups/backup_YYYY-MM-DD_HH-MM-SS.sql.gz`
- Скачать / Восстановить / Удалить (Удалить скрыт, если бэкап один)
- **Файл:** `src/uvicorn/routers/backup/backup.py`

## 5. Сброс БД для разработки

```bash
# 1. Сгенерировать свежий seed через /admin/seed (или использовать существующий)
# 2. Дропнуть и пересоздать БД:
docker exec <mysql-container> mysql -u developer -ppassword -e \
  "DROP DATABASE IF EXISTS project; CREATE DATABASE project CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 3. Рестартовать uvicorn — миграция + seed применятся автоматически:
docker restart uvicorn
```

## 6. Добавление новой таблицы

1. Добавить `CREATE TABLE` в `migrations/0001.sql` в правильном порядке FK (+ соответствующий `DROP TABLE IF EXISTS` в начале)
2. Если нужны начальные данные — добавить таблицу в seed через UI (`/admin/seed`)
3. Если БД уже существует — применить изменение вручную (ALTER TABLE или пересоздать схему через сброс БД)
