-- `detective_case` — таблица, которой не было в схеме
--
-- Зачем вручную: игра-детектив работает на проде с весны, таблицу тогда завели прямо
-- в базе, а в `migrations/0001.sql` не внесли. В итоге чистая установка поднималась
-- без неё, и `/play/detective` падал на первом же ходе: `detective_case` читают
-- `src/tool/detective/detective_.py` и `src/uvicorn/routers/detective/detective.py`.
-- Локальная база — как раз такая установка, таблицы в ней нет.
--
-- Сама схема теперь в `0001.sql` (рядом с `ai_claude_session_registry`), взята с прода
-- дословно. Этот скрипт — для уже поднятых баз, которым `0001.sql` больше не прогоняют.
--
-- Идемпотентность: `CREATE TABLE IF NOT EXISTS`. На проде таблица есть и с данными
-- (11 партий) — скрипт её не тронет.
--
-- На проде перед прогоном снять свежий бэкап через /admin/backup.

-- ─── До ───────────────────────────────────────────────────────────────────────
SELECT COUNT(*) AS `таблица_есть`
FROM `information_schema`.`TABLES`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'detective_case';

-- ─── Правка ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `detective_case` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL,
    `user_id` INT NULL,
    `victim_name` CHAR(100) NOT NULL,
    `crime_description` TEXT NOT NULL,
    `guilty_suspect_name` CHAR(100) NOT NULL,
    `solution_reveal` TEXT NOT NULL,
    `solved` TINYINT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_detective_case_session` (`session_uuid`),
    CONSTRAINT `fk_detective_case_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── После ────────────────────────────────────────────────────────────────────
SELECT COUNT(*) AS `колонок`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'detective_case';

SELECT COUNT(*) AS `партий` FROM `detective_case`;
