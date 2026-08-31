# Migration & Seed — прогон схемы и данных при старте

> При старте `main_uvicorn.py` последовательно вызывает `mysql_migration_up()` (yoyo,
> единственный файл схемы `migrations/20260101000000_initial_schema.sql`) и `mysql_seed_up()` (данные из
> `data/seeds/`). Здесь же — как добавить таблицу и как сбросить локальную БД.

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

### Единственный файл: `migrations/20260101000000_initial_schema.sql`

Содержит полную схему БД:
```sql
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS `project_design_prototype_page_block`;
-- ... все таблицы в порядке FK-зависимостей ...
CREATE TABLE `node` (...);
-- ...
SET FOREIGN_KEY_CHECKS = 1;
```

- `DROP TABLE IF EXISTS` + `CREATE TABLE` — идемпотентно
- Не содержит никаких данных

> ✅ **Имени базы в файле больше нет.** Раньше во второй строке стоял `USE \`project\``,
> и прогон «в песочницу» молча переключался на рабочую базу и сносил её. Имя задаёт
> подключение: yoyo берёт его из `MYSQL_DATABASE` и сам создаёт базу
> (`mysql_migration_up`), ручной прогон получает имя аргументом `mysql`.

**Правило: имя миграции — метка времени.** `YYYYMMDDHHMMSS_<что делаем>.sql`,
например `20260101000000_initial_schema.sql` (начальная схема) или
`20260826143000_task_metric_table.sql`.

**Метку берут командой, а не сочиняют:**

```bash
date +%Y%m%d%H%M%S      # 20260831150226
```

Секунды обязательны, и это не формальность. Часть меток в проекте «круглая»
(`...150000`, `...140500`) — их писали руками, округляя до минуты, — и две работы,
начатые в один час, берут один номер. Живьём: подзадача #5219 собиралась завести
`20260831150000_wf57_qa_mode.sql`, а такой номер за четверть часа до неё занял
соседний файл. Два файла на одну метку yoyo применит в неопределённом порядке, а при
слиянии веток это конфликт — ровно то, от чего метка времени и придумана.

Почему так, а не `0001`, `0002`. Миграции пишутся в ветках подзадач параллельно, и
номерами они столкнулись бы: две ветки завели бы `0002.sql` с разным содержимым, и
слияние молча оставило бы одну. Метка времени уникальна сама по себе, а
алфавитный порядок файлов совпадает с хронологическим — yoyo применяет их именно
в этом порядке, и ничего дополнительно сортировать не нужно.

> ⚠️ **Переименовать применённую миграцию — значит применить её заново.** yoyo
> помнит применённое по имени файла (`_yoyo_migration.migration_id`), и файл под
> новым именем для него новый. Для начальной схемы это `DROP TABLE` по всей базе.
> Переименование обязано идти в паре с записью в журнал; хеш там — sha256 **от
> имени** миграции, а не от содержимого, поэтому запись считается точно:
> `hashlib.sha256(name.encode()).hexdigest()`.

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

## 3.1 Миграция данных — там же, в `migrations/`

**Данные переносятся обычной миграцией.** Отдельного пути для них нет: и `ALTER TABLE`,
и `UPDATE` промпта workflow лежат в `migrations/<метка времени>_<что делаем>.sql` и
применяются yoyo при старте приложения — так же, как схема.

> ⛔ **`data/migration_manual/` больше не используется.** Папку убрали: файлы там
> применялись руками по туннелю к прод-базе, журнал yoyo о них не знал, и «применено
> или нет» приходилось держать в голове. Новых файлов туда не кладут. Ссылки на
> `data/migration_manual/...` в старых комментариях и доках — история, а не указание.

Почему данные нельзя оставить на seed: seed применяется **только к пустой БД**
(`SELECT COUNT(*) FROM node` = 0). На проде база заполнена, поэтому новый seed туда не
доедет никогда — workflow, добавленный локально, на проде не появится ни при деплое, ни
при рестарте. Догоняет его миграция.

Схему по-прежнему начинают с `migrations/20260101000000_initial_schema.sql` — он
источник правды о том, как выглядит пустая база. Но на уже созданной базе `CREATE TABLE`
не перевыполняется, поэтому изменение существующей таблицы (`ALTER TABLE`, `DROP COLUMN`)
нужно **и там, и отдельной миграцией**: первая описывает результат, вторая догоняет его
на живой базе. Делать надо оба.

Что в такой миграции должно быть:

1. **Шапка**: что было, почему ломалось, что делаем и чего намеренно не трогаем.
   `DROP COLUMN` необратим — скажи в шапке, что теряется.
2. **Идемпотентность.** Повторный прогон обязан быть безвредным: `INSERT ... ON DUPLICATE
   KEY UPDATE` вместо `INSERT IGNORE` (догонять изменения, а не молча пропускать строку),
   `REPLACE(...)` по исходной формулировке (второй раз она уже не найдётся), сверка с
   `information_schema.COLUMNS` перед `ALTER`.
3. **Явные id** и порядок таблиц по FK: родитель → переменные → связи → шаги.

> ⚠️ **Id шагов workflow переносятся как есть.** Шаги ссылаются друг на друга по явному
> id внутри `metadata.transitions_after` (`{"step_id": "420", ...}`). Переназначить id
> при вставке — сломать переходы молча. Инструменты, наоборот, адресуются по имени
> (`tool_name`) и синхронизируются из кода при старте — переносить их не нужно.

> ⚠️ **Промпт хранится JSON-строкой.** В `agent_workflow_step.metadata` переводы строк
> лежат как `\n`, и в SQL-литерале их пишут `\\n`. Подстроку для `REPLACE` надёжнее
> вывести из самих данных, чем набрать руками: несовпадение в один символ — тихий
> ноль-строк вместо правки. Пример — `20260827004500_wf56_mr_url_optional.sql`.

Проверка перед выпуском — вкладка «Миграции» рядом с diff подзадачи: она показывает файлы
ветки, отмечает применённые по `_yoyo_migration` и умеет прогнать новую в песочнице
(`migration_sandbox`) — одноразовой базе, где не жалко. Руками применять нельзя: журнал
yoyo не обновится, и при старте файл прогонится ещё раз.

Перед выкаткой на прод — свежий бэкап через `/admin/backup`.

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

1. Добавить `CREATE TABLE` в `migrations/20260101000000_initial_schema.sql` в правильном порядке FK (+ соответствующий `DROP TABLE IF EXISTS` в начале)
2. Если нужны начальные данные — добавить таблицу в seed через UI (`/admin/seed`)
3. Если БД уже существует — применить изменение вручную (ALTER TABLE или пересоздать схему через сброс БД)
