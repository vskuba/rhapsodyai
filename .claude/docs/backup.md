# Backup — полный дамп базы

> Полный дамп БД в сжатый файл. В отличие от seed (только архитектурные таблицы), backup
> содержит все данные всех таблиц — используется для восстановления после сбоя.
> Управление — страница `/admin/backup`. Про seed — `seed.md`.

## Страница `/admin/backup`

Навигация: Settings → Backup

### Layout

Одна панель: таблица файлов + кнопка «Создать бэкап» в шапке.

### Таблица файлов

Колонки: Название | Размер | Дата | Действия (Скачать / Восстановить / Удалить)

**Удалить** скрыт, если в списке только один файл — защита от удаления последнего бэкапа.

## API

| Метод | Путь | Описание |
|-------|------|---------|
| `GET` | `/backup/list` | Список файлов из `data/backups/` |
| `POST` | `/backup/create` | Создать новый бэкап |
| `GET` | `/backup/download/{filename}` | Скачать `.sql.gz` файл |
| `POST` | `/backup/restore/{filename}` | Восстановить БД из бэкапа |
| `DELETE` | `/backup/{filename}` | Удалить файл |

**Файл роутера:** `src/uvicorn/routers/backup/backup.py`

## Создание бэкапа

`POST /backup/create` → `data/backups/backup_YYYY-MM-DD_HH-MM-SS.sql.gz`

Два пути:

### 1. mysqldump (приоритет)
```python
mysqldump --single-transaction --routines --triggers --default-character-set=utf8mb4 <db>
# stdout → gzip.open(filepath, 'wb', compresslevel=6)
```
Пароль передаётся через `MYSQL_PWD` env-переменную (не в командной строке).

### 2. Python-fallback (если mysqldump не найден)
Использует `pymysql`: для каждой таблицы — `SHOW CREATE TABLE` + `SELECT *`, всё собирается в строку и сжимается через `gzip.open`.  
Менее надёжен (нет триггеров, процедур, но для обычных таблиц достаточен).

**Сжатие:** gzip level 6, расширение `.sql.gz`.  
**Таймаут:** 300 сек на создание, 600 сек на восстановление.

## Восстановление

`POST /backup/restore/{filename}`:
1. Читает `.sql.gz` через `gzip.open(filepath, 'rb')`
2. Передаёт распакованные байты на stdin команды `mysql --default-character-set=utf8mb4`
3. Требует наличия `mysql`-клиента в контейнере

**Примечание:** `default-mysql-client` добавлен в `docker/uvicorn/dockerfile` — доступен после пересборки образа. До пересборки работает только create (через Python-fallback), но не restore.

## Безопасность имён файлов

`_backup_filename_safe(filename)`:
- Запрещает `/` и `..` в имени (path traversal)
- Разрешает только `.sql.gz` расширение

## Хранение файлов

`data/backups/` — монтируется в Docker-томе вместе с проектом.  
Файлы отсортированы по имени (новые сверху, т.к. имя содержит timestamp).

## Файлы

| Путь | Роль |
|------|------|
| `src/uvicorn/routers/backup/backup.py` | API роутер |
| `data/backups/backup_*.sql.gz` | Хранилище бэкапов |
| `data/uvicorn/template/admin/backup.html` | UI страница |
| `docker/uvicorn/dockerfile` | `default-mysql-client` для mysqldump/mysql |

## Отличие от Seed

| | Seed | Backup |
|--|------|--------|
| Содержимое | Выбранные таблицы (архитектура) | Вся БД |
| Формат | `.sql` (текст) | `.sql.gz` (gzip) |
| Назначение | Первичный запуск свежей БД | Полное восстановление |
| Применение | `INSERT IGNORE` (безопасно) | Полная перезапись через `mysql` |
| Автоприменение | Да (при старте на пустой БД) | Нет (только вручную) |
