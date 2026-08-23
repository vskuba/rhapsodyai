# task/898 — SQL-экспорт и бэкап в py_modules

Вынесены модули сериализации SQL и dump/restore бэкапа в общий слой:
`py_modules/mysql_/sql_export.py` и `py_modules/mysql_/backup_engine.py`.
Подключение приходит аргументами (host/port/user/password/db) — без привязки к проекту.

## Что в модулях

`sql_export.py` — сериализация, без файла и без подключения:
- `sql_export_value(value)` — значение в SQL-литерал: NULL, bool в 1/0, int/float,
  bytes/строки через `pymysql.converters.escape_string` (экранирует драйвер, не мы).
- `sql_export_tables(connection, tables, database='')` — текст дампа: DDL и строки
  таблица за таблицей; принимает живое pymysql-соединение с dict-курсором, возвращает текст.

`backup_engine.py` — съёмка и восстановление, подключение аргументами:
- `backup_engine_dump(path, host, port, user, password, db)` — сначала `mysqldump`
  (`--single-transaction --routines --triggers`), при её отсутствии — pymysql через
  `sql_export_tables`; пароль в `MYSQL_PWD`, не аргументом (не виден в `ps`).
- `backup_engine_restore(path, host, port, user, password, db)` — распаковка gzip и
  подача клиенту `mysql`; без клиента — `RuntimeError` в момент, когда он нужен.
- `BACKUP_ENGINE_DUMP_TIMEOUT = 300`, `BACKUP_ENGINE_RESTORE_TIMEOUT = 600`.

Донор — DatingAi/src/uvicorn/routers/backup.py (стр. 159-269) и seed.py (стр. 270-282).

## Как закрыты цели

1. **sql_export генерирует дамп с escape.** `sql_export_value` на образцах (None, bool,
   int, float, кавычка+обратный слеш, bytes, кириллица); `sql_export_tables` на фейковом
   dict-соединении — DDL + INSERT с экранированными значениями, NULL-строка, пустая таблица
   = только DDL. Проверено smoke.
2. **backup_engine снимает dump и восстанавливает, подключение аргументами.** pymysql-ветка
   через monkeypatch `pymysql.connect`: параметры host/port/user/password/db ушли аргументами,
   соединение закрыто, на выходе валидный gzip. `restore` без клиента mysql — `RuntimeError`.
   Проверено smoke.

## Чем проверял

- `py_compile` обоих файлов — синтаксис ок.
- Smoke (scratchpad, импорт из `feature_task_898/py_modules`): 5/5 — value-экранирование,
  полный дамп таблицы, pymysql-ветка dump с аргументами, restore, таймауты 300/600.
- `grep` реальных импортов `sql_export_tables`/`sql_export_value`/`backup_engine_dump`/
  `backup_engine_restore`/`from mysql_.sql_export`/`from mysql_.backup_engine` по `src/` — 0
  совпадений: новых импортов не появилось, старые имена не сломаны.
- Grep исходника `backup_engine.py` — нет `mysql_conn_get`/`config_get`/`from mysql_.mysql_`
  и имён БД: без хардкода проекта.

## Что не коммитилось и почему

Код лежит в `py_modules/mysql_/sql_export.py` и `backup_engine.py` — в **master py_modules**
(`/home/vasyl/PycharmProjects/py_modules`) и в сабмодуле worktree (`feature_task_898/py_modules`).
По правилу задачи в py_modules **не коммитить** и **пин gitlink не двигать**: `git status` =
только `?? mysql_/backup_engine.py` + `?? mysql_/sql_export.py` (untracked), `HEAD` = `fee4a23`,
пин не сдвинут.

Этот MR — в RhapsodyAi, и несущий диффа артефакт — данный отчёт, а не код: merge этого MR
**не ставит** код в общий слой py_modules — код ставится отдельным коммитом py_modules, который
делает человек. Отчёт здесь только для видимости работы на странице задач.
