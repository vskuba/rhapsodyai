-- Схема прода → к виду `migrations/0001.sql` (сверка 2026-08-18)
--
-- Зачем вручную: `migrations/0001.sql` — схема для чистой установки. На проде база
-- живёт своей жизнью, деплой её не трогает (собирает образ и поднимает контейнеры),
-- и накопленные `ALTER`/`RENAME` туда не доезжают. Этот файл догоняет прод.
--
-- **Без него новый код на проде не поднимется**: он обращается к `node_variable`,
-- которой там нет, и пишет в `browser_error`, которой там тоже нет.
--
-- Что расходится (сверка `information_schema` прода с локальной базой):
--
--   1. Старые имена таблиц переменных ноды. На проде:
--        agent_workflow_variable_public           (3 строки)
--        agent_workflow_variable_public_role      (5 строк)
--        agent_workflow_variable_public_workflow  (3 строки)
--      Локально они называются `node_variable`, `node_variable_role`,
--      `node_variable_workflow`, а колонка-ссылка — `node_variable_id` вместо
--      `public_variable_id`. Переименование, а не пересоздание: в таблицах живые
--      данные (переменные узла Dating — `girl_title`, `girl_prompt_system`,
--      `girl_bio_example`), и потерять их значит сломать разговор агентов.
--
--   2. Нет таблицы `browser_error` — журнал ошибок браузера. Код пишет в неё при
--      каждом сбое сценария; отсутствие таблицы превращает сбой сценария в
--      исключение внутри обработчика исключения.
--
--   3. Таблиц знакомств (`dating_*`) на проде нет вовсе — модуль туда не
--      выкладывался. Их снос описан отдельным файлом
--      (`2026-08-18_dating_move_out.sql`) и на проде просто ничего не сделает.
--
-- Идемпотентность: каждый шаг сверяется с `information_schema` и на повторном
-- прогоне ничего не делает. Файл можно гонять сколько угодно раз.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup`.

USE `project`;

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_variable_public') AS старая_таблица,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node_variable') AS новая_таблица,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_error') AS журнал_ошибок;

-- ------------------------------------------- 1. Переименование таблиц переменных
--
-- Порядок: сначала родитель, потом связки — иначе внешние ключи связок будут
-- секунду смотреть на несуществующее имя.
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_variable_public') = 1
    AND (SELECT COUNT(*) FROM information_schema.TABLES
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node_variable') = 0,
    'RENAME TABLE `agent_workflow_variable_public` TO `node_variable`',
    'SELECT ''node_variable уже на месте'' AS шаг');
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_variable_public_role') = 1
    AND (SELECT COUNT(*) FROM information_schema.TABLES
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node_variable_role') = 0,
    'RENAME TABLE `agent_workflow_variable_public_role` TO `node_variable_role`',
    'SELECT ''node_variable_role уже на месте'' AS шаг');
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_variable_public_workflow') = 1
    AND (SELECT COUNT(*) FROM information_schema.TABLES
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node_variable_workflow') = 0,
    'RENAME TABLE `agent_workflow_variable_public_workflow` TO `node_variable_workflow`',
    'SELECT ''node_variable_workflow уже на месте'' AS шаг');
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- ------------------------------------------- 2. Переименование колонки-ссылки
--
-- Код обращается к `node_variable_id`. Колонка со старым именем существует вместе
-- со своим внешним ключом, поэтому меняем через `CHANGE COLUMN` — он переносит и
-- ключ, в отличие от `DROP` + `ADD`, которые потеряли бы связи.
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node_variable_role'
        AND COLUMN_NAME = 'public_variable_id') = 1,
    'ALTER TABLE `node_variable_role` CHANGE COLUMN `public_variable_id` `node_variable_id` INT NOT NULL',
    'SELECT ''node_variable_role.node_variable_id уже на месте'' AS шаг');
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node_variable_workflow'
        AND COLUMN_NAME = 'public_variable_id') = 1,
    'ALTER TABLE `node_variable_workflow` CHANGE COLUMN `public_variable_id` `node_variable_id` INT NOT NULL',
    'SELECT ''node_variable_workflow.node_variable_id уже на месте'' AS шаг');
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- ------------------------------------------- 3. Журнал ошибок браузера
--
-- Без внешних ключей намеренно: сессия живёт в памяти контейнера, а сценарий к
-- моменту разбора могли удалить — ошибка переживает и то, и другое.
CREATE TABLE IF NOT EXISTS `browser_error` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `source` VARCHAR(50) NOT NULL COMMENT 'Откуда пришла: view, scenario, workflow, proxy, page',
    `message` TEXT NOT NULL COMMENT 'Текст ошибки — то, что увидел человек',
    `session_id` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'Сессия контейнера, если ошибка из окна',
    `url` VARCHAR(1000) NOT NULL DEFAULT '' COMMENT 'Адрес страницы на момент ошибки',
    `context` JSON NOT NULL COMMENT 'Что связано: сценарий, окружение, номер шага, сессия',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_browser_error_created` (`created_at`),
    INDEX `idx_browser_error_source` (`source`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'agent\_workflow\_variable\_public%') AS старых_осталось,
       (SELECT COUNT(*) FROM node_variable)          AS переменных,
       (SELECT COUNT(*) FROM node_variable_role)     AS связей_ролей,
       (SELECT COUNT(*) FROM node_variable_workflow) AS связей_workflow,
       (SELECT COUNT(*) FROM browser_error)          AS ошибок_в_журнале;
