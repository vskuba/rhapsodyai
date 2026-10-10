-- Ветки и темы → группы тем, темы и вопросы (2026-10-10)
--
-- ЗАЧЕМ. Шаг `branch` становится `topic_action` и работает в два приёма: сперва
-- КОД ищет метки темы в тексте истории, и только выжившие темы идут в подпоток,
-- где их проверяют вопросами. Старое имя «ветка» описывало прежний приём —
-- развилку, выбиравшую одну тему из словаря меток; теперь сущность стала просто
-- группой тем, и имя обязано это сказать.
--
-- Переименования:
--   `agent_workflow_branch`       → `agent_workflow_topic_group`
--   `agent_workflow_branch_topic` → `agent_workflow_topic`
--   `agent_workflow_topic.branch_id` → `topic_group_id`
-- Заводится: `agent_workflow_topic_question` — вопросы темы, строка на вопрос.
--
-- ⚠⚠ ПЕРЕИМЕНОВАНИЕ ТАБЛИЦЫ ОПАСНЕЕ СНОСА КОЛОНКИ, и поэтому здесь есть мост.
-- Миграции накатывает новый контейнер ДО переключения слота, а трафик в этот
-- момент держит ещё старый код (`deploy.md`). Снесённую колонку он читает мимо
-- (её никто не выбирает по имени), а вот исчезнувшую ТАБЛИЦУ не читает никак:
-- `ai_workflow_branch_topics()` зовётся из шага `branch` на КАЖДОМ ответе в чат,
-- и на проде это один прогон примерно в двадцать минут. Девяносто секунд
-- healthcheck'а дают реальный шанс уронить живой ответ собеседнику.
--
-- Поэтому старые имена остаются представлениями на новые таблицы (§5). Старый
-- код читает их как читал, новый читает настоящие таблицы. Представления
-- одноколоночных переименований обновляемы, так что и админский CRUD в окне
-- живёт — но держатся они ради ЧТЕНИЯ движком: правка веток в эти секунды
-- никого не ждёт.
--
-- ⚠⚠ Представления — ВРЕМЕННЫЕ ПОДПОРКИ СО СРОКОМ. Их сносит следующая
-- миграция, вместе с мёртвыми `match_min`, `workflow_id`, `acceptance`,
-- `direction`, `restriction` — второй выкладкой, по тому же правилу, по
-- которому заведён сам мост.
--
-- ⚠ Имя ограничения внешнего ключа (`fk_agent_workflow_branch_topic_branch`)
-- оставлено как есть. Переименовать его можно только снос-плюс-заведение, то
-- есть взять блокировку метаданных на обеих таблицах ради опрятности имени,
-- которое читает лишь сообщение об ошибке. Индексы переименованы: там это
-- `RENAME INDEX`, без перестройки.
--
-- Устройство слоя — `.claude/docs/workflow_branch.md`.

-- ── 0. Что было до ──────────────────────────────────────────────────────────

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
           AND TABLE_NAME IN ('agent_workflow_branch', 'agent_workflow_branch_topic')
       ) AS старых_таблиц,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
           AND TABLE_NAME IN ('agent_workflow_topic_group', 'agent_workflow_topic')
       ) AS новых_таблиц;

-- ── 1. Таблицы ──────────────────────────────────────────────────────────────
--
-- ⚠ Проверка идёт по BASE TABLE, а не по наличию имени вовсе: после §5 имя
-- `agent_workflow_branch` снова занято — уже представлением, — и повторный
-- прогон миграции обязан это различать.

SET @group_old = (
    SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_branch'
       AND TABLE_TYPE = 'BASE TABLE'
);

SET @sql = IF(@group_old = 1,
    "RENAME TABLE `agent_workflow_branch` TO `agent_workflow_topic_group`",
    "SELECT 'Группа тем уже переименована' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @topic_old = (
    SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_branch_topic'
       AND TABLE_TYPE = 'BASE TABLE'
);

SET @sql = IF(@topic_old = 1,
    "RENAME TABLE `agent_workflow_branch_topic` TO `agent_workflow_topic`",
    "SELECT 'Тема уже переименована' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 2. Ссылка на группу и имена индексов ────────────────────────────────────
--
-- ⚠ `RENAME COLUMN` сам переносит на новое имя внешний ключ и уникальный
-- индекс, в которые колонка входит: пересоздавать их руками не нужно.

SET @has_branch_id = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_topic'
       AND COLUMN_NAME = 'branch_id'
);

SET @sql = IF(@has_branch_id = 1,
    "ALTER TABLE `agent_workflow_topic` RENAME COLUMN `branch_id` TO `topic_group_id`",
    "SELECT 'Ссылка на группу уже переименована' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_topic = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_topic'
       AND INDEX_NAME = 'uq_agent_workflow_branch_topic_name'
);

SET @sql = IF(@idx_topic > 0,
    "ALTER TABLE `agent_workflow_topic` RENAME INDEX `uq_agent_workflow_branch_topic_name` TO `uq_agent_workflow_topic_name`",
    "SELECT 'Индекс темы уже переименован' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_group = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_topic_group'
       AND INDEX_NAME = 'uq_agent_workflow_branch_node_name'
);

SET @sql = IF(@idx_group > 0,
    "ALTER TABLE `agent_workflow_topic_group` RENAME INDEX `uq_agent_workflow_branch_node_name` TO `uq_agent_workflow_topic_group_name`",
    "SELECT 'Индекс группы уже переименован' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 3. Два порога у темы ────────────────────────────────────────────────────
--
-- ⚠⚠ Порогов теперь ДВА, и они про разное. `tags_qty_accept` — сколько РАЗНЫХ
-- меток темы обязано найтись в тексте истории, чтобы тему вообще проверять;
-- повтор одной метки счёта не прибавляет. `questions_qty_yes_accept` — сколько
-- ответов «yes» на вопросы темы означает, что тема поднята. Первый считает код
-- до всякой модели, второй — подпоток, которому его передают.
--
-- ⚠ Оба живут у ТЕМЫ, а не у группы. У прежней ветки порог стоял один
-- (`match_min`) и на ней, потому что словарь меток был общий и строгая ветка
-- глушила бы чужую тему. Общего словаря больше нет: каждая тема судится по
-- своим меткам и своим вопросам, независимо от соседей.
--
-- ⚠ Умолчание 1, а не 2: это перенос прежнего `match_min = 1`, а не выбор
-- политики. Единица означает «одного повода достаточно» — число, которое
-- человек обязан увидеть на форме и назначить сам.

SET @has_tags_qty = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_topic'
       AND COLUMN_NAME = 'tags_qty_accept'
);

SET @sql = IF(@has_tags_qty = 0,
    "ALTER TABLE `agent_workflow_topic` ADD COLUMN `tags_qty_accept` TINYINT NOT NULL DEFAULT 1 AFTER `tags`",
    "SELECT 'Колонка tags_qty_accept уже есть' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_yes_qty = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_topic'
       AND COLUMN_NAME = 'questions_qty_yes_accept'
);

SET @sql = IF(@has_yes_qty = 0,
    "ALTER TABLE `agent_workflow_topic` ADD COLUMN `questions_qty_yes_accept` TINYINT NOT NULL DEFAULT 1 AFTER `tags_qty_accept`",
    "SELECT 'Колонка questions_qty_yes_accept уже есть' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Перенос прежнего порога группы в тему: число то же, место новое.
-- ⚠ Условие `tags_qty_accept = 1` держит идемпотентность: назначенное человеком
-- значение повторный прогон миграции не затирает.
UPDATE `agent_workflow_topic` t
  JOIN `agent_workflow_topic_group` g ON g.`id` = t.`topic_group_id`
   SET t.`tags_qty_accept` = GREATEST(1, g.`match_min`)
 WHERE t.`tags_qty_accept` = 1;

-- ── 4. Вопросы темы ────────────────────────────────────────────────────────
--
-- ⚠ Строка на вопрос, а не текст списком в колонке: вопрос — единица, у которой
-- есть свой порядок и свой выключатель, и его надо уметь погасить, не трогая
-- соседние. Пустой список — законное состояние: тема без вопросов поднимается
-- одними метками, и подпоток предусматривает этот случай сам.

CREATE TABLE IF NOT EXISTS `agent_workflow_topic_question` (
    `id`         INT NOT NULL AUTO_INCREMENT,
    `topic_id`   INT NOT NULL,
    `question`   TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `is_enabled` TINYINT NOT NULL DEFAULT 1,
    `position`   INT NOT NULL DEFAULT 0,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_agent_workflow_topic_question_topic` (`topic_id`, `position`),
    CONSTRAINT `fk_agent_workflow_topic_question_topic`
        FOREIGN KEY (`topic_id`) REFERENCES `agent_workflow_topic` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 5. Мост на время выкладки ───────────────────────────────────────────────
--
-- ⚠⚠ Старые имена как представления. Это и есть страховка из шапки: старый код
-- в окне выкладки читает `agent_workflow_branch` и `agent_workflow_branch_topic`
-- и не знает, что под ними другие таблицы. Колонка `branch_id` отдаётся
-- псевдонимом — переименование колонки в представлении остаётся простой
-- ссылкой, и представление поэтому обновляемо.
--
-- ⚠ Колонки перечислены ИМЕНАМИ, а не `SELECT *`. Представление со звёздочкой
-- запоминает состав колонок на момент создания, и дальше расходится с таблицей
-- молча — в том числе с теми колонками, которые снесёт следующая миграция.
--
-- ⚠ Новые пороги в мост НЕ отдаются: старый код их не знает, а место для них в
-- старых `INSERT` не предусмотрено. Умолчание таблицы сделает своё.

SET @branch_is_table = (
    SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_branch'
       AND TABLE_TYPE = 'BASE TABLE'
);

SET @sql = IF(@branch_is_table = 0,
    "CREATE OR REPLACE VIEW `agent_workflow_branch` AS
        SELECT `id`, `node_id`, `name`, `title`, `description`, `workflow_id`,
               `match_min`, `is_enabled`, `position`, `created_at`, `updated_at`
          FROM `agent_workflow_topic_group`",
    "SELECT 'agent_workflow_branch ещё таблица — мост не нужен' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @topic_is_table = (
    SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_branch_topic'
       AND TABLE_TYPE = 'BASE TABLE'
);

SET @sql = IF(@topic_is_table = 0,
    "CREATE OR REPLACE VIEW `agent_workflow_branch_topic` AS
        SELECT `id`, `topic_group_id` AS `branch_id`, `name`, `title`, `tags`,
               `instructions`, `acceptance`, `direction`, `restriction`,
               `is_enabled`, `position`, `created_at`, `updated_at`
          FROM `agent_workflow_topic`",
    "SELECT 'agent_workflow_branch_topic ещё таблица — мост не нужен' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 6. Что стало ────────────────────────────────────────────────────────────
--
-- ⚠ Считаются и темы: переименование таблицы — операция словаря, и «строки на
-- месте» надо увидеть числом, а не предположить.

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
           AND TABLE_NAME IN ('agent_workflow_topic_group', 'agent_workflow_topic',
                              'agent_workflow_topic_question')
       ) AS новых_таблиц,
       (SELECT COUNT(*) FROM information_schema.VIEWS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME IN ('agent_workflow_branch', 'agent_workflow_branch_topic')
       ) AS мостов,
       (SELECT COUNT(*) FROM `agent_workflow_topic_group`) AS групп,
       (SELECT COUNT(*) FROM `agent_workflow_topic`) AS тем;
