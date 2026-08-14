-- `project`.`task_server_url` — адрес тест-сервера проекта
--
-- Зачем вручную: `migrations/0001.sql` — схема для чистой установки, накопленную
-- базу он не догоняет. Колонка там уже описана; здесь то же самое для живой БД.
--
-- Зачем колонка: рабочий каталог подзадачи заводится в репозитории того проекта,
-- которому принадлежит карточка, а проектов на машине несколько. Сервер для
-- проверки поднимает каждый проект своей командой и на своём порту — общего
-- адреса на установку не существует. Раньше он был один, из `.env`
-- (`PROJECT_TASK_QA_SERVER_URL`), и QA соседнего проекта проверял чужой сервер.
--
-- Пустое значение — не ошибка: остаётся прежнее поведение, адрес берётся из
-- `.env`. Так и работает проект самой установки, ему отдельное значение не нужно.
--
-- Идемпотентность: ADD COLUMN выполняется через prepared-запрос только тогда,
-- когда колонки нет. Повторный прогон ничего не делает.
--
-- На проде перед прогоном снять свежий бэкап через /admin/backup.

-- ─── До: есть ли колонка ──────────────────────────────────────────────────────
SELECT COUNT(*) AS `has_column`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'project'
  AND `COLUMN_NAME` = 'task_server_url';

-- ─── Правка ───────────────────────────────────────────────────────────────────
SET @ddl = IF(
    (SELECT COUNT(*)
       FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND `TABLE_NAME` = 'project'
        AND `COLUMN_NAME` = 'task_server_url') > 0,
    'SELECT 1',
    'ALTER TABLE `project` ADD COLUMN `task_server_url` VARCHAR(255) NOT NULL DEFAULT '''' AFTER `work_dir`');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ─── После: колонка на месте ──────────────────────────────────────────────────
SELECT `COLUMN_NAME`, `COLUMN_TYPE`, `IS_NULLABLE`, `COLUMN_DEFAULT`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'project'
  AND `COLUMN_NAME` = 'task_server_url';
