# Seed SQL — перенос архитектурных данных

> Seed — экспорт архитектурных данных (агенты, workflow, ноды, роли) из живой БД в
> SQL-файл. Управление — страница `/admin/seed`, автоприменение при старте сервера.
> Полный дамп всех данных — это `backup.md`, не seed.

## Назначение

Используется для:
- Автоматической загрузки данных в свежую БД при старте сервера
- Хранения нескольких версий данных с возможностью отката
- Переноса настроек на другую инсталляцию

## Страница `/admin/seed`

Навигация: Settings → Seed SQL

### Layout

- **Левый sidebar** — список всех таблиц БД, сгруппированных по первому сегменту имени (`agent_*`, `llm`, `node_*`, ...)
- **Правая панель** — таблица с файлами seed

### Sidebar: выбор таблиц

- Таблицы подгружаются из `INFORMATION_SCHEMA.TABLES` — всегда актуальный список
- Выбор сохраняется в `setting.seed_table_config` (JSON-массив имён таблиц)
- Debounce 400ms на изменение чекбоксов → автосохранение через `POST /seed/config`
- При открытии страницы `GET /seed/tables` возвращает `result` (группы) + `defaults` (сохранённый выбор)

### Таблица файлов

Колонки: Название | Размер | Дата | Действия (Скачать / Применить / Удалить)

**Удалить** скрыт, если в списке только один файл — защита от удаления последнего seed.

## API

| Метод | Путь | Описание |
|-------|------|---------|
| `GET` | `/seed/tables` | Список групп таблиц + сохранённый выбор |
| `POST` | `/seed/config` | Сохранить выбор таблиц в setting |
| `GET` | `/seed/files` | Список seed-файлов из `data/seeds/` |
| `POST` | `/seed/generate` | Сгенерировать новый seed из выбранных таблиц |
| `POST` | `/seed/apply/{filename}` | Применить seed к текущей БД (INSERT IGNORE) |
| `GET` | `/seed/download/{filename}` | Скачать .sql файл |
| `DELETE` | `/seed/{filename}` | Удалить файл |

**Файл роутера:** `src/uvicorn/routers/seed/seed.py`

## Генерация seed

`POST /seed/generate` body: `{"tables": ["node", "llm", ...]}`

Создаёт `data/seeds/seed_YYYY-MM-DD_HH-MM-SS.sql`:

```sql
-- Seed SQL
-- Generated: 2026-07-31 09:46:46
-- Tables: agent, llm, node, ...

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- TABLE: node
INSERT IGNORE INTO `node` (`id`, `name`, ...) VALUES
  (1, 'Dashboard', ...),
  (2, 'Dating', ...);

-- TABLE: llm
...

SET FOREIGN_KEY_CHECKS = 1;
```

- Значения экранируются через `pymysql.converters.escape_string`
- `INSERT IGNORE` — безопасен при повторном apply (существующие строки не трогает)
- Несколько файлов хранятся по дате — можно откатиться к предыдущей версии

## Применение seed через UI

`POST /seed/apply/{filename}` — выполняет все SQL-стейтменты из файла через pymysql.  
SQL парсится `_seed_split_sql()` — корректный сплиттер, игнорирующий `;` внутри строковых литералов (важно: в значениях полей могут быть точки с запятой).

## Автоматическое применение при старте

`py_modules/mysql_/mysql_seed.py` → вызывается в `main_uvicorn.py` после миграции.

Логика:
1. Берёт последний файл `seed_*.sql` из `data/seeds/` (reverse sort по имени)
2. `SELECT COUNT(*) FROM node` — если 0, БД свежая → применяем seed
3. Если нод уже есть → пропускаем (идемпотентно)

## Какие таблицы включать

**Включать** (архитектурные, ручные данные):
`node`, `node_llm`, `llm`, `role`, `role_node`, `setting`, `user`, `user_access_token`, `user_node`, `agent`, `agent_role`, `agent_workflow`, `agent_workflow_step`, `agent_workflow_step_type`, `agent_workflow_variable`, `agent_workflow_variable_workflow`, `node_variable`, `node_variable_role`, `node_variable_workflow`, `fact_collection`, `planning_phase`, `planning_phase_source`

**Не включать** (генерируются автоматически или runtime):
- `tool`, `tool_group` — синхронизируются через `ai_tool_sync()` при каждом старте
- `companion` — создаётся динамически
- `session`, `agent_session`, `agent_workflow_trace`, `agent_workflow_trace_step`, `llm_request`, `plan` — runtime/logs

## Файлы

| Путь | Роль |
|------|------|
| `src/uvicorn/routers/seed/seed.py` | API роутер |
| `py_modules/mysql_/mysql_seed.py` | Автоприменение при старте |
| `data/seeds/seed_*.sql` | Хранилище seed-файлов |
| `data/uvicorn/template/admin/seed.html` | UI страница |
