-- `project_task`.`pipeline_started_at` — начало текущей работы над строкой
--
-- Зачем вручную: `migrations/0001.sql` — схема для чистой установки, накопленную
-- базу он не догоняет. Колонка там уже описана; здесь то же самое для живой БД.
--
-- Зачем колонка: раньше началом работы служил `pipeline_locked_at`, но живой job
-- подновляет его раз в 45 секунд (`task_claim_lock_touch`), чтобы реклейм не
-- отобрал строку у работающего агента. После этого по блокировке видно только
-- «job жив», а не «сколько уже идёт прогон». Остаток до таймаута агента на
-- мини-карточках команды (`/admin/task`) считается от новой колонки.
--
-- Заполняется в момент захвата (`_task_claim`), при снятии блокировки не чистится:
-- значение читается только вместе с непустым `pipeline_locked_by`.
--
-- Идемпотентность: ADD COLUMN выполняется через prepared-запрос только тогда,
-- когда колонки нет. Повторный прогон ничего не делает.
--
-- На проде перед прогоном снять свежий бэкап через /admin/backup.

-- ─── До: есть ли колонка ──────────────────────────────────────────────────────
SELECT COUNT(*) AS `has_column`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'project_task'
  AND `COLUMN_NAME` = 'pipeline_started_at';

-- ─── Правка ───────────────────────────────────────────────────────────────────
SET @ddl = IF(
    (SELECT COUNT(*)
       FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND `TABLE_NAME` = 'project_task'
        AND `COLUMN_NAME` = 'pipeline_started_at') > 0,
    'SELECT 1',
    'ALTER TABLE `project_task` ADD COLUMN `pipeline_started_at` DATETIME DEFAULT NULL AFTER `pipeline_locked_by`');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ─── После: колонка на месте ──────────────────────────────────────────────────
SELECT `COLUMN_NAME`, `COLUMN_TYPE`, `IS_NULLABLE`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'project_task'
  AND `COLUMN_NAME` = 'pipeline_started_at';
