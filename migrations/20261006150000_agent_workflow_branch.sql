-- Ветки и темы: открытый слой управления разговором (2026-10-06)
--
-- ЗАЧЕМ. Особая тема разговора сегодня заведена одна — `photo_mail`, — и стоит
-- она в трёх местах текстом: перечень тем в промпте шага «Тема разговора»,
-- инструкции в промпте subflow `dating_talk_about_photo`, развилка переходом.
-- Вторая тема стоит subflow из трёх шагов, двух шагов у родителя и выкладки.
--
-- ⚠ Миграция, которой заведена первая тема, сама это предсказала: «ТЕМА —
-- СТРОКА, А НЕ ФЛАГ. Их будет больше одной: встречи, деньги, контакты».
--
-- УСТРОЙСТВО. Ветка — род разговора со своим контрактом и необязательным
-- subflow; тема — запись внутри ветки с метками и тремя текстами: что
-- разрешено, куда вести, что запрещено. Тему выбирает арифметика по меткам.
--
-- Спека целиком — docs/superpowers/specs/2026-10-06-branch-topic-layer-design.md.

CREATE TABLE IF NOT EXISTS `agent_workflow_branch` (
    `id`          INT NOT NULL AUTO_INCREMENT,
    `node_id`     INT NOT NULL,
    `name`        VARCHAR(64)  NOT NULL,
    `title`       VARCHAR(255) NOT NULL,
    `description` TEXT NULL,

    -- Subflow ветки. ⚠ NULL — законное значение и основной случай: ветка
    -- «сужает» общий ответ, своей дороги у неё нет.
    `workflow_id` INT NULL DEFAULT NULL,

    -- Порог: сколько меток темы должно совпасть, чтобы тема вообще участвовала
    -- в выборе. ⚠ Живёт здесь, а не на шаге: на шаге строгая ветка глушила бы и
    -- чужие темы — победила её тема со счётом 2 при пороге 3, и разговор остался
    -- бы без темы, хотя у соседней ветки была годная тройка.
    `match_min`   TINYINT NOT NULL DEFAULT 1,

    `is_enabled`  TINYINT NOT NULL DEFAULT 1,
    `position`    INT NOT NULL DEFAULT 0,
    `created_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_agent_workflow_branch_node_name` (`node_id`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agent_workflow_branch_topic` (
    `id`          INT NOT NULL AUTO_INCREMENT,
    `branch_id`   INT NOT NULL,
    `name`        VARCHAR(64)  NOT NULL,
    `title`       VARCHAR(255) NOT NULL,

    -- Метки через запятую, слова внутри метки через пробел: «обмен письмами».
    --
    -- ⚠⚠ Метки из двух слов и больше — не вкусовщина. Односложные не различают
    -- близкие темы: слово «письмо» ровно так же стоит в рассказе про письмо от
    -- деда, как и в просьбе прислать фотографии. «Обмен письмами» — различает.
    `tags`        TEXT NOT NULL,

    `acceptance`  TEXT NULL,
    `direction`   TEXT NULL,
    `restriction` TEXT NULL,
    `is_enabled`  TINYINT NOT NULL DEFAULT 1,
    `position`    INT NOT NULL DEFAULT 0,
    `created_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_agent_workflow_branch_topic_name` (`branch_id`, `name`),
    CONSTRAINT `fk_agent_workflow_branch_topic_branch` FOREIGN KEY (`branch_id`)
        REFERENCES `agent_workflow_branch` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── Объявленные выходы workflow ─────────────────────────────────────────────
--
-- ⚠ Без них «контракты ветки и subflow совпадают» непроверяемо: у workflow
-- сегодня объявлены только входы.
--
-- ⚠⚠ Побочная выгода крупнее повода. Сейчас `outputs_map` у tool-шагов движок
-- игнорирует молча, и в базе лежат тринадцать мёртвых карт в шести workflow
-- (workflow.md §4a-bis). Объявленный выход даёт редактору право отказать на
-- сохранении. Оживлять старые карты эта миграция не берётся — там нужен разбор
-- каждого случая.

SET @has_output = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_variable'
       AND COLUMN_NAME = 'type'
       AND COLUMN_TYPE LIKE '%output%'
);

SET @sql = IF(@has_output = 0,
    "ALTER TABLE `agent_workflow_variable` MODIFY `type` ENUM('global','input','workflow','output') NOT NULL DEFAULT 'workflow'",
    "SELECT 'ENUM уже содержит output' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── Тип шага ────────────────────────────────────────────────────────────────
--
-- ⚠ Колонки сверены с живой схемой 06.10.2026: `title` у таблицы нет, а `icon`,
-- `description` и `metadata` объявлены NOT NULL. У соседей `metadata` пустая
-- строка — проверено на `workflow_invoke`.

INSERT INTO `agent_workflow_step_type` (`name`, `icon`, `description`, `description_full`, `metadata`)
SELECT 'branch', '🌿', 'Ветка разговора',
       'Находит тему по меткам во всём реестре ноды и, если она принадлежит выбранной ветке, кладёт topic_* и вызывает subflow ветки',
       ''
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step_type`) x
                    WHERE x.`name` = 'branch');

SELECT 'ГОТОВО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_branch`) AS веток,
       (SELECT COUNT(*) FROM `agent_workflow_branch_topic`) AS тем,
       (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'branch') AS тип_шага;
