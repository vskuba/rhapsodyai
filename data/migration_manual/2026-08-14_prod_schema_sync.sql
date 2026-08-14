-- Схема прода → к виду `migrations/0001.sql`
--
-- Зачем вручную: `migrations/0001.sql` — схема для чистой установки. На проде база
-- живёт с весны, деплой её не трогает (собирает образ и поднимает контейнеры), и
-- накопленные за месяцы `ALTER`-ы туда не доезжают. Этот скрипт догоняет прод до
-- `0001.sql` — один раз, перед выкладкой конвейера задач.
--
-- Что расходится (сверка `information_schema` прода с `0001.sql` от 2026-08-14):
--   нет трёх таблиц      — `project_task_type`, `project_team`, `project_task_plan_revision`;
--   нет колонок          — `project`.{work_dir, task_server_url, description},
--                          `project_task`.{task_type_id, pipeline_attempt_count,
--                          pipeline_from_plan, pipeline_started_at, trace_meta, metadata},
--                          `ai_claude_session`.status,
--                          `ai_claude_session_registry`.{work_dir, agent_status,
--                          agent_status_reason};
--   старый набор состояний — `project_task`.`pipeline_state` (7 значений против 14);
--   старая привязка       — `project_task_attempt` смотрит на `project_task_subtask`,
--                           которой в `0001.sql` нет: единица работы конвейера теперь
--                           живёт строкой в дереве задач;
--   лишняя таблица        — `project_task_subtask` (её сносит и сам `0001.sql`, строка 25).
--
-- Почему это безопасно: на проде конвейер задач не работал ни дня — `project`,
-- `project_task`, `project_task_attempt` и `project_task_subtask` пустые (проверено
-- перед выпуском, блок «До» это показывает). Поэтому перестройка `project_task_attempt`
-- и снятие `project_task_subtask` не теряют ни строки. Если блок «До» покажет
-- ненулевые счётчики — скрипт эти два шага пропустит и напишет об этом; разбираться
-- тогда руками.
--
-- Чего здесь нет:
--   `node`.`migration_file` — колонка есть на проде, в `0001.sql` её нет, в коде на неё
--     не ссылается ничто. Данные в ней есть (6 строк), удаление — потеря без выгоды;
--     оставляем как есть.
--   `project`.`node_id` DEFAULT — на проде 9, в `0001.sql` 6. Значение по умолчанию,
--     нумерация нод у установок своя; трогать без разбора нельзя.
--   `detective_case` — таблица есть на проде и в коде (`src/tool/detective/detective_.py`),
--     но её нет в `0001.sql`, и локальной базе она недостаёт. Это пробел в `0001.sql`,
--     а не лишняя таблица прода: сносить её нельзя, чинить надо в другую сторону.
--
-- Идемпотентность: каждый шаг сначала спрашивает `information_schema` и выполняется,
-- только если нужного ещё нет. Повторный прогон ничего не делает.
--
-- На проде перед прогоном снять свежий бэкап через /admin/backup.

-- ─── До: что расходится и пусты ли таблицы конвейера ──────────────────────────
SELECT
    (SELECT COUNT(*) FROM `information_schema`.`TABLES`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND `TABLE_NAME` IN ('project_task_type', 'project_team',
                             'project_task_plan_revision'))            AS `есть_из_3_таблиц`,
    (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND ((`TABLE_NAME` = 'project'
              AND `COLUMN_NAME` IN ('work_dir', 'task_server_url', 'description'))
          OR (`TABLE_NAME` = 'project_task'
              AND `COLUMN_NAME` IN ('task_type_id', 'pipeline_attempt_count',
                                    'pipeline_from_plan', 'pipeline_started_at',
                                    'trace_meta', 'metadata'))
          OR (`TABLE_NAME` = 'ai_claude_session' AND `COLUMN_NAME` = 'status')
          OR (`TABLE_NAME` = 'ai_claude_session_registry'
              AND `COLUMN_NAME` IN ('work_dir', 'agent_status',
                                    'agent_status_reason'))))          AS `есть_из_13_колонок`,
    (SELECT COUNT(*) FROM `project`)                                   AS `строк_project`,
    (SELECT COUNT(*) FROM `project_task`)                              AS `строк_project_task`,
    (SELECT COUNT(*) FROM `project_task_attempt`)                      AS `строк_attempt`;

-- ─── Правка ───────────────────────────────────────────────────────────────────

-- Две подсобные процедуры на время прогона: без них тот же самый запрос к
-- `information_schema` пришлось бы переписывать двадцать раз, и разница между шагами
-- терялась бы в повторе. В конце файла обе снимаются.
DROP PROCEDURE IF EXISTS `_sync_run`;
DROP PROCEDURE IF EXISTS `_sync_column`;

DELIMITER //

-- Выполнить DDL, если его ещё не применяли: `p_exists` — счётчик из
-- `information_schema` (0 = нужного объекта нет).
CREATE PROCEDURE `_sync_run`(IN p_exists INT, IN p_ddl TEXT)
BEGIN
    IF p_exists = 0 THEN
        SET @ddl = p_ddl;
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END//

-- То же для колонки — самый частый случай, поэтому со своим именем и без запроса
-- в каждой строке вызова.
CREATE PROCEDURE `_sync_column`(IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_ddl TEXT)
BEGIN
    CALL `_sync_run`((SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
                       WHERE `TABLE_SCHEMA` = DATABASE()
                         AND `TABLE_NAME` = p_table
                         AND `COLUMN_NAME` = p_column), p_ddl);
END//

DELIMITER ;

-- ── Таблицы ───────────────────────────────────────────────────────────────────
-- Порядок обязателен: на `project_task_type` ссылается `project_task`, на `project`
-- — `project_team`, на `project_task` — `project_task_plan_revision`.

CREATE TABLE IF NOT EXISTS `project_task_type` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(50) NOT NULL COMMENT 'dev, bug, test, research, plan',
    `title` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Отображаемое название',
    `description` TEXT DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_type_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Пять типов задач — это не данные проекта, а справочник, без которого страница
-- задач не откроет ни одной карточки. Номера те же, что локально: на них ссылается
-- `project_task`.`task_type_id`, и разъехавшаяся нумерация сделала бы перенос задач
-- между установками бессмысленным.
INSERT IGNORE INTO `project_task_type` (`id`, `name`, `title`, `description`) VALUES
    (1, 'dev',      'Разработка',   'Разработка новой функциональности'),
    (2, 'bug',      'Bug',          'Исправление существующих багов'),
    (3, 'test',     'Тестирование', 'Написание и выполнение тестов'),
    (4, 'research', 'Исследование', 'Анализ и исследование технологий'),
    (5, 'plan',     'Планирование', 'Планирование задач и спринтов');

CREATE TABLE IF NOT EXISTS `project_team` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT DEFAULT NULL COMMENT 'Проект карточки; NULL — карточка вне проектов',
    `name` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Имя члена команды',
    `role` VARCHAR(50) NOT NULL DEFAULT 'developer' COMMENT 'manager, developer, qa',
    `command` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Команда для запуска (например: claude-shell --gx10 --manager)',
    `work_dir` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Рабочая директория проекта',
    `status` ENUM('active','inactive') NOT NULL DEFAULT 'inactive' COMMENT 'Статус: активен/не активен',
    `last_ping_at` DATETIME DEFAULT NULL COMMENT 'Последний пинг от терминала',
    `pid` INT DEFAULT NULL COMMENT 'PID процесса терминала',
    `session_uuid` CHAR(36) DEFAULT NULL COMMENT 'UUID сессии Claude Code',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_team_project_name` (`project_id`, `name`),
    INDEX `idx_team_status` (`status`),
    INDEX `idx_team_project_role` (`project_id`, `role`),
    CONSTRAINT `fk_team_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `project_task_plan_revision` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `task_id` INT NOT NULL,
    `revision_no` INT NOT NULL DEFAULT '0',
    `plan_text` MEDIUMTEXT NOT NULL,
    `goals` TEXT NOT NULL,
    `subtasks` MEDIUMTEXT NOT NULL,
    `author_kind` ENUM('manager','user') NOT NULL DEFAULT 'manager',
    `author_id` INT DEFAULT NULL,
    `author_name` VARCHAR(64) NOT NULL DEFAULT '',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_ptpr_task_rev` (`task_id`, `revision_no`),
    CONSTRAINT `fk_ptpr_task` FOREIGN KEY (`task_id`) REFERENCES `project_task` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── Колонки `project` ─────────────────────────────────────────────────────────

CALL `_sync_column`('project', 'work_dir',
    'ALTER TABLE `project` ADD COLUMN `work_dir` VARCHAR(500) NULL AFTER `idea`');
CALL `_sync_column`('project', 'task_server_url',
    'ALTER TABLE `project` ADD COLUMN `task_server_url` VARCHAR(255) NOT NULL DEFAULT '''' AFTER `work_dir`');
CALL `_sync_column`('project', 'description',
    'ALTER TABLE `project` ADD COLUMN `description` TEXT NULL AFTER `task_server_url`');

-- ── Колонки `project_task` ────────────────────────────────────────────────────

CALL `_sync_column`('project_task', 'task_type_id',
    'ALTER TABLE `project_task` ADD COLUMN `task_type_id` INT DEFAULT NULL AFTER `parent_id`');
CALL `_sync_column`('project_task', 'pipeline_attempt_count',
    'ALTER TABLE `project_task` ADD COLUMN `pipeline_attempt_count` INT NOT NULL DEFAULT ''0'' AFTER `pipeline_error`');
CALL `_sync_column`('project_task', 'pipeline_from_plan',
    'ALTER TABLE `project_task` ADD COLUMN `pipeline_from_plan` TINYINT(1) NOT NULL DEFAULT ''0'' AFTER `pipeline_attempt_count`');
CALL `_sync_column`('project_task', 'pipeline_started_at',
    'ALTER TABLE `project_task` ADD COLUMN `pipeline_started_at` DATETIME DEFAULT NULL AFTER `pipeline_locked_by`');
CALL `_sync_column`('project_task', 'trace_meta',
    'ALTER TABLE `project_task` ADD COLUMN `trace_meta` JSON NULL COMMENT ''Мета-данные интеграций: [{domain, ...}]'' AFTER `pipeline_started_at`');
CALL `_sync_column`('project_task', 'metadata',
    'ALTER TABLE `project_task` ADD COLUMN `metadata` JSON NULL COMMENT ''Произвольные данные задачи: {ключ: значение}'' AFTER `trace_meta`');

-- Состояния конвейера: на проде остался набор из семи значений от первой версии
-- (`pending_approval`, `split`), в `0001.sql` их четырнадцать. Строк в таблице нет,
-- поэтому перевод — чистая смена типа, без сверки данных.
CALL `_sync_run`((SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
                   WHERE `TABLE_SCHEMA` = DATABASE()
                     AND `TABLE_NAME` = 'project_task'
                     AND `COLUMN_NAME` = 'pipeline_state'
                     AND `COLUMN_TYPE` LIKE '%qa_pending%'),
    'ALTER TABLE `project_task` MODIFY COLUMN `pipeline_state` ENUM(''new'',''planning'',''plan_approval'',''reviewing'',''approved'',''processing'',''testing'',''planned'',''developing'',''qa_pending'',''failed_qa'',''blocked'',''done'',''failed'') DEFAULT NULL');

CALL `_sync_run`((SELECT COUNT(*) FROM `information_schema`.`STATISTICS`
                   WHERE `TABLE_SCHEMA` = DATABASE()
                     AND `TABLE_NAME` = 'project_task'
                     AND `INDEX_NAME` = 'idx_pt_task_type'),
    'ALTER TABLE `project_task` ADD INDEX `idx_pt_task_type` (`task_type_id`)');

CALL `_sync_run`((SELECT COUNT(*) FROM `information_schema`.`TABLE_CONSTRAINTS`
                   WHERE `TABLE_SCHEMA` = DATABASE()
                     AND `TABLE_NAME` = 'project_task'
                     AND `CONSTRAINT_NAME` = 'fk_pt_task_type'),
    'ALTER TABLE `project_task` ADD CONSTRAINT `fk_pt_task_type` FOREIGN KEY (`task_type_id`) REFERENCES `project_task_type` (`id`) ON DELETE SET NULL');

-- ── `project_task_attempt`: перевести с подзадач на задачи ────────────────────
-- Колонку не переименовываем: вместе с ней меняются внешний ключ и индекс, а таблица
-- пуста — пересоздать по `0001.sql` короче и вернее, чем вести цепочку ALTER-ов.
-- Условие «пусто» проверяется явно: круги Developer → QA на проде не шли, но если
-- строки всё же появятся, скрипт молча их не выбросит.

CALL `_sync_run`((SELECT COUNT(*) + (SELECT COUNT(*) FROM `project_task_attempt`)
                    FROM `information_schema`.`COLUMNS`
                   WHERE `TABLE_SCHEMA` = DATABASE()
                     AND `TABLE_NAME` = 'project_task_attempt'
                     AND `COLUMN_NAME` = 'task_id'),
    'DROP TABLE `project_task_attempt`');

CREATE TABLE IF NOT EXISTS `project_task_attempt` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `task_id` INT NOT NULL,
    `attempt_no` INT NOT NULL DEFAULT '0',
    `role` ENUM('manager','developer','qa') NOT NULL,
    `status` ENUM('ok','error') NOT NULL,
    `output` MEDIUMTEXT NOT NULL,
    `error` TEXT NOT NULL,
    `duration_ms` INT NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_pta_task` (`task_id`, `attempt_no`),
    CONSTRAINT `fk_pta_task` FOREIGN KEY (`task_id`) REFERENCES `project_task` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Отдельной таблицы подзадач у конвейера больше нет: единица работы — строка в дереве
-- задач с непустым `parent_id`. `0001.sql` сносит её на чистой установке (строка 25),
-- здесь то же для живой базы. Сносим только пустую: ссылок на неё уже нет (внешний
-- ключ ушёл вместе со старым `project_task_attempt`), но данные важнее схемы.
--
-- Счётчик строк берём через prepared-запрос, а не прямым `SELECT COUNT(*)`: на второй
-- прогон (и на любой базе, где таблицы никогда не было) обращение к ней по имени —
-- ошибка разбора, а не пустой ответ. Нет таблицы — ставим единицу, то есть «делать
-- нечего».
SET @ddl = IF((SELECT COUNT(*) FROM `information_schema`.`TABLES`
                WHERE `TABLE_SCHEMA` = DATABASE()
                  AND `TABLE_NAME` = 'project_task_subtask') = 0,
              'SELECT 1 INTO @subtask_rows',
              'SELECT COUNT(*) INTO @subtask_rows FROM `project_task_subtask`');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CALL `_sync_run`(@subtask_rows, 'DROP TABLE IF EXISTS `project_task_subtask`');

-- ── Колонки реестра сессий Claude ─────────────────────────────────────────────

CALL `_sync_column`('ai_claude_session', 'status',
    'ALTER TABLE `ai_claude_session` ADD COLUMN `status` ENUM(''queued'',''delivered'',''answered'',''failed'') NOT NULL DEFAULT ''queued'' COMMENT ''Фаза обработки строки очереди: queued - лежит в инбоксе, delivered - оболочка ввела текст в Claude Code, answered - пришёл ответ, failed - оболочка сдалась''');
CALL `_sync_column`('ai_claude_session_registry', 'work_dir',
    'ALTER TABLE `ai_claude_session_registry` ADD COLUMN `work_dir` VARCHAR(500) NULL COMMENT ''Абсолютный путь, в котором запущена shell-оболочка''');
CALL `_sync_column`('ai_claude_session_registry', 'agent_status',
    'ALTER TABLE `ai_claude_session_registry` ADD COLUMN `agent_status` ENUM(''unknown'',''ready'',''busy'') NOT NULL DEFAULT ''unknown'' COMMENT ''Готов ли агент принять сообщение прямо сейчас; приходит с heartbeat оболочки''');
CALL `_sync_column`('ai_claude_session_registry', 'agent_status_reason',
    'ALTER TABLE `ai_claude_session_registry` ADD COLUMN `agent_status_reason` VARCHAR(32) NOT NULL DEFAULT '''' COMMENT ''Причина занятости: permission / turn / queue / ... — только для диагностики''');

DROP PROCEDURE IF EXISTS `_sync_column`;
DROP PROCEDURE IF EXISTS `_sync_run`;

-- ─── После: всё на месте ──────────────────────────────────────────────────────
SELECT
    (SELECT COUNT(*) FROM `information_schema`.`TABLES`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND `TABLE_NAME` IN ('project_task_type', 'project_team',
                             'project_task_plan_revision'))            AS `таблиц_из_3`,
    (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND ((`TABLE_NAME` = 'project'
              AND `COLUMN_NAME` IN ('work_dir', 'task_server_url', 'description'))
          OR (`TABLE_NAME` = 'project_task'
              AND `COLUMN_NAME` IN ('task_type_id', 'pipeline_attempt_count',
                                    'pipeline_from_plan', 'pipeline_started_at',
                                    'trace_meta', 'metadata'))
          OR (`TABLE_NAME` = 'ai_claude_session' AND `COLUMN_NAME` = 'status')
          OR (`TABLE_NAME` = 'ai_claude_session_registry'
              AND `COLUMN_NAME` IN ('work_dir', 'agent_status',
                                    'agent_status_reason'))))          AS `колонок_из_13`,
    (SELECT COUNT(*) FROM `project_task_type`)                         AS `типов_задач`,
    (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND `TABLE_NAME` = 'project_task_attempt'
        AND `COLUMN_NAME` = 'task_id')                                 AS `attempt_на_задачи`,
    (SELECT COUNT(*) FROM `information_schema`.`TABLES`
      WHERE `TABLE_SCHEMA` = DATABASE()
        AND `TABLE_NAME` = 'project_task_subtask')                     AS `осталась_subtask`;

SELECT `COLUMN_TYPE` AS `pipeline_state`
FROM `information_schema`.`COLUMNS`
WHERE `TABLE_SCHEMA` = DATABASE()
  AND `TABLE_NAME` = 'project_task'
  AND `COLUMN_NAME` = 'pipeline_state';
