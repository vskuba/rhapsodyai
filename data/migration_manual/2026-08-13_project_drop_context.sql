-- Удаление колонки `project`.`context`
--
-- Зачем вручную: `migrations/0001.sql` описывает схему для чистой базы, а на проде база
-- уже создана — новая версия CREATE TABLE туда не доедет ни при деплое, ни при рестарте.
-- Колонку убираем тем же одноразовым скриптом, что и переносы данных.
--
-- Что удаляется: одна колонка `context` TEXT NULL в таблице `project`.
-- Функционал, который её писал (кнопка «Обновить контекст» на /admin/project,
-- endpoint'ы `/project/context-generate` и `/project/get_context`, генератор
-- `project_context_generate`), удалён из кода в этом же изменении.
--
-- Проверено перед выпуском: локально в обеих строках `project` колонка была пустой
-- (CHAR_LENGTH = 0). На проде перед прогоном сверить тем же SELECT из блока «до» ниже
-- и снять свежий бэкап через /admin/backup — DROP COLUMN необратим.

-- ─── До: сколько текста потеряем ──────────────────────────────────────────────
SELECT `id`, `title`, CHAR_LENGTH(COALESCE(`context`, '')) AS `ctx_len`
FROM `project`
ORDER BY `id`;

-- ─── Удаление (идемпотентно: повторный прогон ничего не делает) ────────────────
SET @drop_sql := (
    SELECT IF(COUNT(*) > 0,
              'ALTER TABLE `project` DROP COLUMN `context`',
              'SELECT ''колонка context уже удалена'' AS `note`')
    FROM `information_schema`.`COLUMNS`
    WHERE `TABLE_SCHEMA` = DATABASE()
      AND `TABLE_NAME` = 'project'
      AND `COLUMN_NAME` = 'context'
);
PREPARE stmt FROM @drop_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ─── После: колонки быть не должно ────────────────────────────────────────────
SELECT COUNT(*) AS `context_columns_left`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'project'
  AND `COLUMN_NAME` = 'context';
