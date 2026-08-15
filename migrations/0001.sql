CREATE DATABASE IF NOT EXISTS `project` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `project`;

SET FOREIGN_KEY_CHECKS = 0;

-- Удаляем таблицы, если они существуют
-- browser
DROP TABLE IF EXISTS `browser_scenario_run`;
DROP TABLE IF EXISTS `browser_scenario`;
DROP TABLE IF EXISTS `browser_site`;
-- project / planning (new names)
DROP TABLE IF EXISTS `project_design_prototype_page_block`;
DROP TABLE IF EXISTS `project_design_prototype_widget`;
DROP TABLE IF EXISTS `project_design_prototype_page`;
DROP TABLE IF EXISTS `project_state`;
-- project_design_prototype_block removed: merged into project_design_ui_block
DROP TABLE IF EXISTS `project_design_prototype_browser_history`;
DROP TABLE IF EXISTS `project_design_ui_block_size`;
DROP TABLE IF EXISTS `project_design_ui_block`;
DROP TABLE IF EXISTS `project_design_ui_block_type`;
DROP TABLE IF EXISTS `project_design_ui_component`;
DROP TABLE IF EXISTS `project_design_token`;
DROP TABLE IF EXISTS `project_planning_document`;
DROP TABLE IF EXISTS `project_planning_phase`;
DROP TABLE IF EXISTS `project_planning_phase_source`;
DROP TABLE IF EXISTS `project_task_attempt`;
-- Таблицы больше нет: подзадачи конвейера живут в `project_task` через `parent_id`.
-- Строку оставляем, чтобы прогон схемы поверх старой базы дочищал за собой.
DROP TABLE IF EXISTS `project_task_subtask`;
DROP TABLE IF EXISTS `project_task`;
DROP TABLE IF EXISTS `project_team`;
DROP TABLE IF EXISTS `project_task_type`;
DROP TABLE IF EXISTS `project`;
-- developing / detective
DROP TABLE IF EXISTS `developing_task`;
DROP TABLE IF EXISTS `developing_project`;
-- agent workflow trace
DROP TABLE IF EXISTS `agent_workflow_trace_step`;
DROP TABLE IF EXISTS `agent_workflow_trace`;
DROP TABLE IF EXISTS `agent_session`;
DROP TABLE IF EXISTS `plan`;
DROP TABLE IF EXISTS `agent_role`;
DROP TABLE IF EXISTS `agent`;
DROP TABLE IF EXISTS `fact`;
DROP TABLE IF EXISTS `fact_collection`;
DROP TABLE IF EXISTS `companion`;
DROP TABLE IF EXISTS `agent_workflow_variable_public_workflow`;
DROP TABLE IF EXISTS `agent_workflow_variable_public_role`;
DROP TABLE IF EXISTS `agent_workflow_variable_public`;
DROP TABLE IF EXISTS `agent_workflow_variable_workflow`;
DROP TABLE IF EXISTS `agent_workflow_variable`;
DROP TABLE IF EXISTS `agent_workflow_step`;
DROP TABLE IF EXISTS `agent_workflow_step_type`;
DROP TABLE IF EXISTS `agent_workflow`;
DROP TABLE IF EXISTS `tool`;
DROP TABLE IF EXISTS `tool_group`;
DROP TABLE IF EXISTS `session`;
DROP TABLE IF EXISTS `role_node`;
DROP TABLE IF EXISTS `llm_request`;
DROP TABLE IF EXISTS `node_llm`;
DROP TABLE IF EXISTS `user_node`;
DROP TABLE IF EXISTS `setting`;
DROP TABLE IF EXISTS `node`;
DROP TABLE IF EXISTS `user_access_token`;
DROP TABLE IF EXISTS `ai_claude_session_registry`;
DROP TABLE IF EXISTS `ai_claude_session`;
DROP TABLE IF EXISTS `event_log`;
DROP TABLE IF EXISTS `user`;
DROP TABLE IF EXISTS `role`;
DROP TABLE IF EXISTS `llm`;

-- Включаем проверки обратно
SET FOREIGN_KEY_CHECKS = 1;

-- Таблица LLM
CREATE TABLE `llm` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `input_type`  VARCHAR(255) NOT NULL DEFAULT 'text' COMMENT 'Поддерживаемые типы входных данных через запятую: text,image,audio',
    `output_type` VARCHAR(255) NOT NULL DEFAULT 'text' COMMENT 'Поддерживаемые типы выходных данных через запятую: text,image,audio',
    `chunk_size` JSON NULL COMMENT 'Кеш: {"10": 15000, "avg_ms": 32000, "chars_per_ms": 1.5}; ключ = целевые секунды',
    `chunk_size_refresh_at` DATETIME NULL COMMENT 'Когда истекает кеш chunk_size (NOW + 15 мин); NULL = требует пересчёта'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица ролей
CREATE TABLE `role` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(30) NOT NULL,
    UNIQUE INDEX `ux_role_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица пользователей
CREATE TABLE `user` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` CHAR(50) NOT NULL,
    `email` CHAR(50) NOT NULL,
    `password_hash` CHAR(100) NOT NULL,
    `role_id` INT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `dynamic` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Создан рантаймом (guest-сессия PWA), не seed - исключается из экспорта/prod-миграции',
    CONSTRAINT `fk_user_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица токенов доступа пользователей
CREATE TABLE `user_access_token` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `token` CHAR(36) NOT NULL,
    CONSTRAINT `fk_user_access_token_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `node` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `is_catchall` TINYINT(1) NOT NULL DEFAULT 0,
    `llm_parallel_per_agent_max` TINYINT NOT NULL DEFAULT 1 COMMENT 'Максимум параллельных LLM-запросов на один агент этой ноды'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица настроек (scope: user_id — пользовательская, node_id — нодовая, оба NULL — общая)
CREATE TABLE `setting` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `key` CHAR(50) NOT NULL,
    `user_id` INT DEFAULT NULL,
    `node_id` INT DEFAULT NULL,
    `value` LONGTEXT NOT NULL,
    `dynamic` TINYINT NOT NULL DEFAULT 0,
    CONSTRAINT `fk_settings_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_settings_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE setting ADD UNIQUE INDEX idx_key_user (`key`, user_id, node_id);

CREATE TABLE `user_node` (
    `user_id` INT NOT NULL,
    `node_id` INT NOT NULL,
    PRIMARY KEY (`user_id`, `node_id`),
    CONSTRAINT `fk_user_node_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_user_node_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал запросов к LLM: метрики страницы /admin/llm (счетчики за интервалы, графики).
-- Записи старше 7 дней удаляются оппортунистически при вставке (ai_llm_request_log)
CREATE TABLE `llm_request` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `llm_id` INT NOT NULL,
    `user_id` INT NULL,
    `node_id` INT NULL,                                -- нода, под которой реально шел запрос (для /admin/llm статистики по ноде - node_llm может делить одну модель между нодами, этого недостаточно для фильтра)
    `status_code` INT NULL,                            -- 200 = успех; 429/413/402/503/500 = ошибка
    `duration_ms` INT NULL,                            -- время ответа провайдера в мс
    `prompt_length` INT NULL,                           -- суммарный размер промпта (system+user) для расчёта chars/ms
    `tokens_input`  INT NULL,                          -- входящие токены LLM-вызова
    `tokens_output` INT NULL,                          -- исходящие токены LLM-вызова
    `error` VARCHAR(255) NULL,                         -- краткий текст ошибки
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_llm_request_llm` (`llm_id`, `created_at`),
    INDEX `idx_llm_request_created` (`created_at`),
    INDEX `idx_llm_request_node` (`node_id`, `created_at`),
    CONSTRAINT `fk_llm_request_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_llm_request_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_llm_request_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Список LLM настраивается на ноду (не на пользователя) - при росте числа
-- пользователей настраивать каждому вручную нереально, а нод намного меньше
CREATE TABLE `node_llm` (
    `node_id` INT NOT NULL,
    `llm_id` INT NOT NULL,
    `rate_limit_at` DATETIME DEFAULT NULL,             -- время последней ошибки провайдера (модель уходит в конец очереди)
    `code_error` INT DEFAULT NULL,                     -- HTTP-код ошибки провайдера (429/413/402/503)
    `position` INT DEFAULT NULL,
    PRIMARY KEY (`node_id`, `llm_id`),
    CONSTRAINT `fk_node_llm_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_node_llm_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `role_node` (
    `role_id` INT NOT NULL,
    `node_id` INT NOT NULL,
    PRIMARY KEY (`role_id`, `node_id`),
    CONSTRAINT `fk_role_node_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_role_node_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `session` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `uuid` CHAR(36) NOT NULL,
    `metadata` LONGTEXT DEFAULT NULL,
    UNIQUE INDEX `u_session_uuid` (`uuid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица инструментов
CREATE TABLE `tool_group` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    UNIQUE INDEX `u_tool_group_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tool` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `group_id` INT NULL,
    `path` CHAR(200) DEFAULT NULL,
    `description` LONGTEXT DEFAULT NULL,
    `args` LONGTEXT DEFAULT NULL,
    CONSTRAINT `fk_tool_group` FOREIGN KEY (`group_id`) REFERENCES `tool_group` (`id`) ON DELETE SET NULL,
    UNIQUE INDEX `u_tool_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица задач
CREATE TABLE `agent_workflow` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `name` CHAR(50) NOT NULL,
    `title` CHAR(50) NOT NULL,
    `description` CHAR(200) NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `group_name` CHAR(50) NULL DEFAULT NULL,
    `subflow` INT NOT NULL DEFAULT 0,
    CONSTRAINT `workflow_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL,
    UNIQUE INDEX `u_w_workflow_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_step_type` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `icon` CHAR(2) NOT NULL,
    `description` CHAR(200) NOT NULL,
    `description_full` LONGTEXT DEFAULT NULL,
    `metadata` LONGTEXT NOT NULL,
    UNIQUE INDEX `u_st_workflow_step_type_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_step` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `workflow_id` INT NULL,
    `type_id` INT NULL,
    `title` CHAR(50) NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `metadata` LONGTEXT NOT NULL,
    CONSTRAINT `fk_ws_workflow_step_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_ws_workflow_step_workflow_step_type` FOREIGN KEY (`type_id`) REFERENCES `agent_workflow_step_type` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_variable` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `type` ENUM('global', 'input', 'workflow') NOT NULL DEFAULT 'workflow',
    `default` LONGTEXT NULL,
    `description` CHAR(200) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_variable_workflow` (
    `variable_id` INT NOT NULL,
    `workflow_id` INT NOT NULL,
    PRIMARY KEY (`variable_id`, `workflow_id`),
    CONSTRAINT `fk_vw_workflow_variable` FOREIGN KEY (`variable_id`) REFERENCES `agent_workflow_variable` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_vw_workflow_variable_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Публичные переменные (бывшие "переменные ноды"): привязаны к ноде, редактируются менеджерами.
-- type='proxy' — переменная-подсказка: показывается как доступный %плейсхолдер% при
-- редактировании публичных переменных той же ноды (замена старого механизма use_as_hint)
CREATE TABLE `agent_workflow_variable_public` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `name` CHAR(50) NOT NULL,
    `title` CHAR(100) NOT NULL DEFAULT '',             -- отображаемое название (в списках и меню)
    `type` ENUM('public', 'proxy') NOT NULL DEFAULT 'public',
    `default` LONGTEXT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `description` CHAR(200) DEFAULT NULL,
    CONSTRAINT `fk_vp_workflow_variable_public_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_variable_public_role` (
    `public_variable_id` INT NOT NULL,
    `role_id` INT NOT NULL,
    PRIMARY KEY (`public_variable_id`, `role_id`),
    CONSTRAINT `fk_vpr_workflow_variable_public` FOREIGN KEY (`public_variable_id`) REFERENCES `agent_workflow_variable_public` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_vpr_workflow_variable_public_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Привязка публичной переменной к workflow: переменная видна не во всех workflow ноды,
-- а только в тех, где реально используется
CREATE TABLE `agent_workflow_variable_public_workflow` (
    `public_variable_id` INT NOT NULL,
    `workflow_id` INT NOT NULL,
    PRIMARY KEY (`public_variable_id`, `workflow_id`),
    CONSTRAINT `fk_vpw_workflow_variable_public` FOREIGN KEY (`public_variable_id`) REFERENCES `agent_workflow_variable_public` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_vpw_workflow_variable_public_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `companion` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(25) NOT NULL,
    `title` CHAR(25) NOT NULL,
    UNIQUE INDEX `un_companion_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица фактов (коллекция фактов)
CREATE TABLE `fact_collection` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `name` CHAR(40) NOT NULL,
    `title` CHAR(100) NOT NULL DEFAULT '',            -- отображаемое название (в списках и меню)
    `field` CHAR(250) NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `language` CHAR(40) NOT NULL,
    `description` CHAR(200) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица агентов
CREATE TABLE `agent` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `name` CHAR(50) NOT NULL,
    `title` CHAR(150) NOT NULL,
    `description` CHAR(250) NOT NULL,
    `workflow_id` INT NULL,
    `workflow_variable` LONGTEXT DEFAULT NULL,
    `prompt_system` LONGTEXT NOT NULL,
    `greeting` LONGTEXT NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `group_name` CHAR(50) NULL DEFAULT NULL,
    `dynamic` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 - создан во время игры (agent_create_or_update), не входит в seed-экспорт',
    UNIQUE INDEX `u_agent_name` (`name`),              -- name — системный идентификатор (document_id в Qdrant); отображаемое имя — title
    CONSTRAINT `ag_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL,
    CONSTRAINT `ag_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_role` (
    `agent_id` INT NOT NULL,
    `role_id` INT NOT NULL,
    PRIMARY KEY (`agent_id`, `role_id`),
    CONSTRAINT `fk_agent_agent` FOREIGN KEY (`agent_id`) REFERENCES `agent` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_agent_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица планов (Markdown-документы, редактируемые голосом/текстом в Telegram Mini App)
CREATE TABLE `plan` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `user_id` INT NULL,
    `title` CHAR(150) NOT NULL,
    `content` LONGTEXT NOT NULL COMMENT 'Markdown-текст плана; шаги/прогресс — чекбоксы "- [ ]"/"- [x]" внутри этого текста',
    `status` ENUM('active', 'archived') NOT NULL DEFAULT 'active',
    `position` INT NOT NULL DEFAULT 0,
    `dynamic` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 - создан во время работы (mini-app), не входит в seed-экспорт',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_plan_node` (`node_id`),
    INDEX `idx_plan_user_status` (`user_id`, `status`),
    CONSTRAINT `fk_plan_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_plan_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица фактов
CREATE TABLE `fact` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `collection_id` INT NOT NULL,
    `user_id` INT NULL COMMENT 'tag:filter|type:int|desc:User that ran the workflow which created the fact (owner; system field, filled by code, used for Qdrant filtering)',
    `document_id` CHAR(100) NULL COMMENT 'tag:extract|type:string|desc:Document ID string (example: dasha)',
    `document_title` CHAR(200) NULL,                   -- заголовок документа: title сущности агента (заполняется кодом, не LLM)
    `file_id` CHAR(100) NULL COMMENT 'tag:extract|type:string|desc:File ID as key for single storage (example: filename.pdf)',
    `category` CHAR(50) DEFAULT NULL COMMENT 'tag:extract|type:string|desc:High-level classification (example: delivery)',
    `language` CHAR(2) NOT NULL COMMENT 'tag:extract|type:string|desc:The language two char format, ISO 639-1 code (example: en)',
    `document` LONGTEXT NOT NULL COMMENT 'tag:extract|type:string|desc:The clean, factual text extracted from the source',
    `tags` CHAR(250) NOT NULL COMMENT 'tag:extract|type:array_string|desc:A comma-separated list of tags extracted from the source (example: tag1,tag2,tag3)',
    `qdrant_synced` INT NOT NULL DEFAULT 0,
    `verify_status` CHAR(20) DEFAULT NULL,             -- фактчек кроном: ok | corrected | unverifiable (NULL - не проверялся)
    `verified_at` DATETIME DEFAULT NULL,               -- когда факт проверялся в последний раз
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_qdrant_synced` (`qdrant_synced`),
    INDEX `idx_fact_verified` (`verified_at`),
    INDEX `idx_collection_lang` (`collection_id`, `language`),
    INDEX `idx_fact_user` (`user_id`),
    CONSTRAINT `fk_fact_fact_collection` FOREIGN KEY (`collection_id`) REFERENCES `fact_collection` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_fact_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица памяти (история диалогов/действий)
CREATE TABLE `agent_session` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL,
    `request_uuid` CHAR(36) NOT NULL,
    `llm_id` INT NULL,
    `agent_id` INT NULL,
    `user_id` INT NULL,
    `companion_id` INT NULL,
    `role` CHAR(30) NOT NULL,
    `kind_type` CHAR(20) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `token` INT DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_session` (`session_uuid`),
    INDEX `idx_agent_user` (`agent_id`, `user_id`, `created_at`),
    CONSTRAINT `fk_memory_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_memory_agent` FOREIGN KEY (`agent_id`) REFERENCES `agent` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_memory_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_memory_companion` FOREIGN KEY (`companion_id`) REFERENCES `companion` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Очередь сообщений Telegram Claude chat (Mini App) для внешней обработки
-- Claude Code: воркфлоу telegram_claude_cli кладет сюда сообщение и мгновенно
-- отвечает "..." без LLM, настоящий ответ пишет отдельный процесс Claude Code
-- (handled/response/responded_at) - см. migrations/0005.sql и src/tool/claude_/claude_.py
CREATE TABLE `ai_claude_session` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `handled` TINYINT(1) NOT NULL DEFAULT 0,
    `response` LONGTEXT NULL,
    `responded_at` DATETIME NULL,
    `dynamic` TINYINT(1) NOT NULL DEFAULT 0,
    `status` ENUM('queued','delivered','answered','failed') NOT NULL DEFAULT 'queued' COMMENT 'Фаза обработки строки очереди: queued - лежит в инбоксе, delivered - оболочка ввела текст в Claude Code, answered - пришёл ответ, failed - оболочка сдалась',
    INDEX `idx_claude_session_handled` (`handled`, `created_at`),
    INDEX `idx_claude_session_uuid` (`session_uuid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Реестр терминальных сессий Claude Code (не путать с очередью выше) - какие
-- session_uuid сейчас зарегистрированы/активны, под какой ролью и проектом;
-- нужен, чтобы Mini App могла показывать список открытых сессий в виде иконок
-- и резюмировать конкретную при повторном запуске терминала - см.
-- .claude/docs/claude_session_registry.md
CREATE TABLE `ai_claude_session_registry` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL UNIQUE,
    `role` VARCHAR(50) NOT NULL DEFAULT 'developer',
    `project_label` VARCHAR(255) NOT NULL,
    `status` ENUM('active','closing','inactive') NOT NULL DEFAULT 'active',
    `server_llm` ENUM('anthropic','gx10') NOT NULL DEFAULT 'anthropic',
    `summary` VARCHAR(500) NULL,
    `work_dir` VARCHAR(500) NULL COMMENT 'Абсолютный путь, в котором запущена shell-оболочка',
    `agent_status` ENUM('unknown','ready','busy') NOT NULL DEFAULT 'unknown' COMMENT 'Готов ли агент принять сообщение прямо сейчас; приходит с heartbeat оболочки',
    `agent_status_reason` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'Причина занятости: permission / turn / queue / ... — только для диагностики',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `last_seen_at` DATETIME NULL,
    `closed_at` DATETIME NULL,
    INDEX `idx_claude_registry_status` (`status`),
    INDEX `idx_claude_registry_project` (`project_label`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Дело игры-детектива: жертва, преступление и разгадка одной партии. Разгадку держим
-- на сервере (`guilty_suspect_name`, `solution_reveal`): агенты-подозреваемые её не
-- знают, иначе первый же вопрос игрока вскрыл бы финал. Партия привязана к сессии, а
-- не к пользователю: в `/play/detective` играют без входа, `user_id` заполняется только
-- у вошедших - см. .claude/docs/detective.md
CREATE TABLE `detective_case` (
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

-- Журнал выполнения workflow: один запуск (включая вложенные sub-workflow через parent_run_id)
CREATE TABLE `agent_workflow_trace` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `run_uuid` CHAR(36) NOT NULL,
    `parent_run_id` INT NULL,                    -- запуск sub-workflow ссылается на родителя
    `parent_step_id` INT NULL,                   -- id шага workflow_invoke, породившего запуск
    `depth` INT NOT NULL DEFAULT 0,
    `workflow_id` INT NULL,
    `agent_id` INT NULL,
    `user_id` INT NULL,
    `session_uuid` CHAR(36) DEFAULT NULL,
    `request_uuid` CHAR(36) DEFAULT NULL,
    `prompt_user` LONGTEXT NULL,
    `variables_start` LONGTEXT NULL,             -- полный снапшот переменных на старте (JSON)
    `result` LONGTEXT NULL,                      -- финальный ответ workflow
    `status` ENUM('running', 'success', 'error', 'stopped') NOT NULL DEFAULT 'running',
    `error` LONGTEXT NULL,
    `started_at` DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    `finished_at` DATETIME(3) NULL,
    `duration_ms` INT NULL,
    UNIQUE INDEX `u_workflow_run_uuid` (`run_uuid`),
    INDEX `idx_workflow_run_workflow` (`workflow_id`, `started_at`),
    INDEX `idx_workflow_run_session` (`session_uuid`),
    INDEX `idx_workflow_run_parent` (`parent_run_id`),
    CONSTRAINT `fk_wr_run_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_wr_run_parent` FOREIGN KEY (`parent_run_id`) REFERENCES `agent_workflow_trace` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал выполнения workflow: выполненный шаг (вход/выход/переход/длительность)
CREATE TABLE `agent_workflow_trace_step` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `run_id` INT NOT NULL,
    `exec_index` INT NOT NULL,                   -- порядковый номер выполнения (не position шага)
    `step_id` INT NULL,
    `step_title` CHAR(100) DEFAULT NULL,
    `step_type` CHAR(50) DEFAULT NULL,
    `llm_id` INT NULL,                           -- LLM использованная в LLM-шаге (NULL для tool/text/variable шагов)
    `metadata_rendered` LONGTEXT NULL,           -- вход: metadata после рендера %переменных%
    `variables_changed` LONGTEXT NULL,           -- выход: JSON измененных шагом переменных
    `output` LONGTEXT NULL,                      -- ответ LLM / результат инструмента / результат sub-workflow
    `transition` LONGTEXT NULL,                  -- сработавший переход: {phase, condition, to_step_id}
    `status` ENUM('success', 'error', 'retry') NOT NULL DEFAULT 'success',
    `error` LONGTEXT NULL,
    `created_at` DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    `duration_ms` INT NULL,
    `tokens_input` INT NULL,                       -- входящие токены LLM-шага
    `tokens_output` INT NULL,                      -- исходящие токены LLM-шага
    INDEX `idx_workflow_run_step_run` (`run_id`, `exec_index`),
    CONSTRAINT `fk_wrs_run` FOREIGN KEY (`run_id`) REFERENCES `agent_workflow_trace` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_wrs_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал событий event-системы (py_modules/event_/event_.py): аудит + лента
-- для Telegram Mini App. Без FK - события системные и не привязаны к ноде.
CREATE TABLE `event_log` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `type` ENUM('system', 'github', 'claude_session', 'agent', 'llm') NOT NULL,
    `payload` JSON NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_event_log_type` (`type`),
    INDEX `idx_event_log_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── Project Task ──────────────────────────────────────────────────────────────

CREATE TABLE `project_task` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT DEFAULT NULL,
    -- Дерево задач: NULL = корневая, иначе подзадача своего родителя. Глубина не
    -- ограничена схемой. Дерево одно на всех: и человеческая декомпозиция
    -- «эпик → подзадачи», и подзадачи конвейера, которые Manager раскладывает из
    -- утверждённого плана, — это строки этой же таблицы со своим `parent_id`.
    `parent_id` INT DEFAULT NULL,
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `description` TEXT NOT NULL,
    `goals` TEXT NOT NULL,
    `status` ENUM('pending','queued','active','done','blocked','cancelled') NOT NULL DEFAULT 'pending',
    `task_type_id` INT DEFAULT NULL COMMENT 'Тип задачи (dev, bug, test, research, plan)',
    `report` TEXT NOT NULL,
    `position` INT NOT NULL DEFAULT '0',
    -- Конвейер агентов. NULL = обычная ручная задача, конвейера не касается (opt-in).
    -- Ортогонально `status`, который остаётся человеческим kanban-статусом.
    -- `reviewing` — человек нажал «Обновить план»: план есть, но его надо пересмотреть.
    -- Отдельное значение обязательно: отбор в конвейер идёт по «в плане нет подзадач»
    -- (`task_claim_task_unplanned`), и задачу с готовым планом иначе никто не подберёт.
    --
    -- Один ENUM на две ветки конвейера, потому что таблица одна:
    --   родитель: new -> planning -> plan_approval -> approved -> processing -> done|failed
    --             reviewing --^ (человек нажал «Обновить план»)      '-> testing --^
    --   ребёнок:  planned -> developing -> qa_pending -> testing -> done
    --                            ^                          '-> failed_qa -> повтор до MAX_ATTEMPTS
    --                            '---------------------------'      '-> blocked (лимит исчерпан)
    -- `testing` у родителя — та же работа, что и `processing`, но после пометки
    -- «в тестирование»: разработка по всем подзадачам закончена, идёт проверка.
    -- Закрывается оттуда же, откуда и `processing` (`task_state_task_finalize`).
    -- `testing` у ребёнка — QA взял подзадачу в работу (`qa_pending` — только очередь
    -- к нему). Значение общее для обеих веток намеренно: смысл один и тот же —
    -- «идёт проверка», и человеку на странице оно читается одинаково.
    -- Остальные значения не пересекаются: ветку задаёт `parent_id`, а не колонка.
    `pipeline_state` ENUM('new','planning','plan_approval','reviewing','approved','processing',
                          'testing','planned','developing','qa_pending','failed_qa','blocked',
                          'done','failed') DEFAULT NULL,
    `pipeline_plan` MEDIUMTEXT NOT NULL,
    `pipeline_error` TEXT NOT NULL,
    -- Сколько кругов Developer -> QA уже прошла подзадача. У родителя всегда 0:
    -- круг идёт по детям, лимит — `task_pipeline.MAX_ATTEMPTS`.
    `pipeline_attempt_count` INT NOT NULL DEFAULT '0',
    -- 1 = строку создал конвейер, разложив утверждённый план родителя; 0 = задачу
    -- завёл человек. Дерево общее, отдельной таблицы подзадач нет, и по состоянию
    -- происхождение не восстановить: сброс и пересмотр плана сносят свои строки
    -- целиком, а человеческую декомпозицию трогать нельзя ни при каких условиях.
    `pipeline_from_plan` TINYINT(1) NOT NULL DEFAULT '0',
    `pipeline_locked_at` DATETIME DEFAULT NULL,
    `pipeline_locked_by` VARCHAR(64) NOT NULL DEFAULT '',
    -- Когда началась текущая работа над строкой. Отдельно от `pipeline_locked_at`
    -- потому, что тот подновляется на ходу (`task_claim_lock_touch`): живой job
    -- держит блокировку свежей, и по ней уже не сказать, давно ли идёт прогон.
    -- Отсюда карточки команды считают остаток до таймаута агента.
    -- При снятии блокировки не чистится: читается только вместе с ней.
    `pipeline_started_at` DATETIME DEFAULT NULL,
    `trace_meta` JSON NULL COMMENT 'Мета-данные интеграций: [{domain, ...}]',
    -- Свободный мешок данных задачи: ключ -> значение, читается и пишется целиком
    -- через `task_metadata`. Сюда кладут то, под что заводить колонку рано: пометки
    -- агентов, ссылки на внешние сущности, счётчики. Схема ничего не знает о
    -- составе — контракт держит код, который пишет конкретный ключ.
    -- Отличие от `trace_meta`: тот — след интеграции, привязка задачи к источнику
    -- ошибки, по нему идёт дедуп (`task_bug_dedup`), и трогать его нельзя.
    `metadata` JSON NULL COMMENT 'Произвольные данные задачи: {ключ: значение}',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_pt_project` (`project_id`),
    INDEX `idx_pt_status` (`status`),
    INDEX `idx_pt_position` (`project_id`, `position`),
    INDEX `idx_pt_pipeline` (`pipeline_state`),
    INDEX `idx_pt_parent` (`parent_id`, `position`),
    INDEX `idx_pt_task_type` (`task_type_id`),
    -- Удаление родителя уносит всю ветку: подзадача без родителя смысла не имеет.
    CONSTRAINT `fk_pt_parent` FOREIGN KEY (`parent_id`) REFERENCES `project_task` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_pt_task_type` FOREIGN KEY (`task_type_id`) REFERENCES `project_task_type` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- История попыток: нужна, чтобы вернуть ошибку QA обратно разработчику
-- и чтобы Developer с QA не пинг-понговали бесконечно (см. MAX_ATTEMPTS).
--
-- `task_id` — та самая подзадача, по которой шёл круг, то есть строка `project_task`
-- с непустым `parent_id`. Отдельной таблицы подзадач у конвейера нет: единица работы
-- живёт в дереве задач наравне с остальными.
CREATE TABLE `project_task_attempt` (
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

-- История версий плана. План перезаписывается на месте, и без снапшота предыдущая
-- версия исчезала вместе с ответом на вопрос «кто и на что её поменял» — а именно он
-- и нужен, когда разбираешь, почему конвейер сделал не то.
--
-- Append-only: каждая запись плана добавляет строку, самая свежая ревизия — это то,
-- что прямо сейчас лежит в `project_task.pipeline_plan`. Снимок именно новой версии,
-- а не вытесняемой: тогда автор и время у строки честные («эту версию написал
-- такой-то тогда-то»), а не «момент, когда её заменили».
CREATE TABLE `project_task_plan_revision` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `task_id` INT NOT NULL,
    -- Нумерация внутри задачи, считается на вставке. AUTO_INCREMENT не годится —
    -- он общий на все задачи, и «Ревизия 417» в интерфейсе ничего не значит.
    `revision_no` INT NOT NULL DEFAULT '0',
    `plan_text` MEDIUMTEXT NOT NULL,
    -- Цели и подзадачи снимаются вместе с планом: чипс ревизии подменяет и то, и то,
    -- а восстановление без подзадач дало бы план, который нечем раскладывать.
    `goals` TEXT NOT NULL,
    `subtasks` MEDIUMTEXT NOT NULL,
    `author_kind` ENUM('manager','user') NOT NULL DEFAULT 'manager',
    `author_id` INT DEFAULT NULL,
    `author_name` VARCHAR(64) NOT NULL DEFAULT '',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    -- Настоящая защита от гонки человека и воркера: номер считается запросом, и без
    -- уникальности две одновременные записи получили бы один и тот же `revision_no`.
    UNIQUE KEY `uk_ptpr_task_rev` (`task_id`, `revision_no`),
    CONSTRAINT `fk_ptpr_task` FOREIGN KEY (`task_id`) REFERENCES `project_task` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── Developing ────────────────────────────────────────────────────────────────

CREATE TABLE `developing_project` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `node_id` INT NOT NULL DEFAULT '10',
    `planning_project_id` INT DEFAULT NULL,
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `status` ENUM('pending','active','done','blocked','cancelled') NOT NULL DEFAULT 'pending',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_planning_project` (`planning_project_id`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `developing_task` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT NOT NULL,
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `description` TEXT NOT NULL,
    `role` ENUM('manager','backend','frontend','devops','qa') NOT NULL DEFAULT 'backend',
    `assignee` VARCHAR(100) NOT NULL DEFAULT '',
    `priority` ENUM('high','medium','low') NOT NULL DEFAULT 'medium',
    `status` ENUM('pending','active','review','done','blocked','cancelled') NOT NULL DEFAULT 'pending',
    `hours_planned` SMALLINT NOT NULL DEFAULT '0',
    `hours_spent` SMALLINT NOT NULL DEFAULT '0',
    `position` INT NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_project` (`project_id`),
    INDEX `idx_status` (`status`),
    INDEX `idx_role` (`role`),
    INDEX `idx_position` (`project_id`, `position`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── Project (planning_project → project) ──────────────────────────────────────

CREATE TABLE `project` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `node_id` INT NOT NULL DEFAULT '6',
    `user_id` INT NOT NULL DEFAULT '0',
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `idea` LONGTEXT NOT NULL,
    `work_dir` VARCHAR(500) NULL,
    -- Адрес сервера, поднятого над рабочим каталогом подзадачи этого проекта:
    -- QA проверяет ветку на нём, а не на общем сервере установки. У каждого
    -- проекта свой порт и своя команда запуска, поэтому значение на проекте, а
    -- не в `.env`; пусто — берётся PROJECT_TASK_QA_SERVER_URL (`project_task.md`).
    `task_server_url` VARCHAR(255) NOT NULL DEFAULT '',
    `description` TEXT NULL,
    `status` ENUM('pending','processing','complete','error') NOT NULL DEFAULT 'pending',
    `phase_current` VARCHAR(100) NOT NULL DEFAULT '',
    `position` INT NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `score_market` TINYINT DEFAULT NULL,
    `score_feasibility` TINYINT DEFAULT NULL,
    `score_financial` TINYINT DEFAULT NULL,
    `score_total` TINYINT DEFAULT NULL,
    `score_verdict` VARCHAR(10) DEFAULT NULL,
    `score_investment` VARCHAR(100) DEFAULT NULL,
    `score_time_to_market` VARCHAR(100) DEFAULT NULL,
    `score_summary` TEXT DEFAULT NULL,
    `cloud_tags` TEXT DEFAULT NULL,
    `entities` TEXT DEFAULT NULL,
    `roles` TEXT DEFAULT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── Project Planning ──────────────────────────────────────────────────────────

CREATE TABLE `project_planning_phase_source` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `phase_key` VARCHAR(100) NOT NULL DEFAULT '',
    `title` VARCHAR(200) NOT NULL DEFAULT '',
    `doc_file` VARCHAR(200) NOT NULL DEFAULT '',
    `header_mode` VARCHAR(30) NOT NULL DEFAULT '## ',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_phase_key` (`phase_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_planning_phase` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT NOT NULL,
    `phase` VARCHAR(100) NOT NULL DEFAULT '',
    `parent_phase` VARCHAR(100) DEFAULT NULL,
    `title` VARCHAR(200) NOT NULL DEFAULT '',
    `status` ENUM('pending','running','waiting','complete','failed') NOT NULL DEFAULT 'pending',
    `result` LONGTEXT NOT NULL,
    `error` TEXT NOT NULL,
    `summary` VARCHAR(150) NOT NULL DEFAULT '',
    `tokens_used` INT NOT NULL DEFAULT '0',
    `tokens_input` INT DEFAULT NULL,
    `tokens_output` INT DEFAULT NULL,
    `started_at` DATETIME DEFAULT NULL,
    `completed_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `project_phase` (`project_id`, `phase`),
    INDEX `idx_project` (`project_id`),
    INDEX `idx_status` (`status`),
    INDEX `idx_parent_phase` (`project_id`, `parent_phase`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_planning_document` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT NOT NULL,
    `doc_type` VARCHAR(100) NOT NULL DEFAULT '',
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `content` LONGTEXT NOT NULL,
    `version` INT NOT NULL DEFAULT '1',
    `status` ENUM('draft','final') NOT NULL DEFAULT 'draft',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_project` (`project_id`),
    INDEX `idx_doc_type` (`doc_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── Project Design ────────────────────────────────────────────────────────────

-- project_design_prototype_block removed: merged into project_design_ui_block (project_id column added there)

CREATE TABLE `project_design_prototype_browser_history` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT NOT NULL,
    `url` VARCHAR(2048) NOT NULL DEFAULT '',
    `used_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_project_url` (`project_id`, `url`(512)),
    INDEX `idx_project_used` (`project_id`, `used_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_state` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(50) NOT NULL,
    `description` VARCHAR(255) DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_prototype_page` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `project_id` INT NOT NULL,
    `parent_id` INT DEFAULT NULL,
    `name` VARCHAR(255) NOT NULL DEFAULT '',
    `description` TEXT DEFAULT NULL,
    `page_type` VARCHAR(50) NOT NULL DEFAULT 'feature',
    `tags` VARCHAR(500) NOT NULL DEFAULT '',
    `roles` VARCHAR(500) NOT NULL DEFAULT '',
    `state_id` INT NOT NULL DEFAULT 1,
    `wireframe` LONGTEXT DEFAULT NULL,
    `grid_layout` JSON DEFAULT NULL,
    `ux_spec` LONGTEXT DEFAULT NULL,
    `order_index` INT NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_project` (`project_id`),
    INDEX `idx_parent` (`parent_id`),
    INDEX `idx_state` (`state_id`),
    CONSTRAINT `fk_proto_page_state` FOREIGN KEY (`state_id`) REFERENCES `project_state` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_prototype_widget` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `block_id` INT NOT NULL,
    `name` VARCHAR(255) NOT NULL,
    `description` TEXT DEFAULT NULL,
    `css` MEDIUMTEXT DEFAULT NULL,
    `html` MEDIUMTEXT DEFAULT NULL,
    `created_by` VARCHAR(50) NOT NULL DEFAULT 'ai',
    `order_index` INT NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_block_id` (`block_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_prototype_page_block` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `page_id` INT NOT NULL,
    `block_id` INT NOT NULL,
    `widget_id` INT DEFAULT NULL,
    `widget_name` VARCHAR(255) NOT NULL DEFAULT '',
    `order_index` INT NOT NULL DEFAULT '0',
    `section` TINYINT(4) NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_page_block` (`page_id`, `block_id`, `section`),
    INDEX `idx_page` (`page_id`),
    INDEX `idx_block` (`block_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_ui_component` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    `description` TEXT NOT NULL,
    `variants` VARCHAR(500) NOT NULL DEFAULT '',
    `sizes` VARCHAR(200) NOT NULL DEFAULT '',
    `states` VARCHAR(300) NOT NULL DEFAULT '',
    `tailwind_example` TEXT NOT NULL,
    `tags` VARCHAR(500) NOT NULL DEFAULT '',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_name` (`name`),
    INDEX `idx_tags` (`tags`(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_ui_block_type` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `description` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_type_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_ui_block` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `type_id` INT DEFAULT NULL,
    `name` VARCHAR(255) NOT NULL DEFAULT '',
    `title` VARCHAR(255) DEFAULT NULL,
    `description` TEXT DEFAULT NULL,
    `stateless` TINYINT(1) NOT NULL DEFAULT 0,
    `html` TEXT DEFAULT NULL,
    `css` TEXT DEFAULT NULL,
    `created_by` VARCHAR(20) NOT NULL DEFAULT 'ai',
    `order_index` INT NOT NULL DEFAULT 0,
    `section` VARCHAR(500) DEFAULT NULL,
    `tags` VARCHAR(500) DEFAULT NULL,
    `vars` TEXT DEFAULT NULL,
    `slot` VARCHAR(100) DEFAULT NULL,
    `slots` TEXT DEFAULT NULL,
    `width_min` INT DEFAULT NULL COMMENT 'minimum preview width px',
    `height_min` INT DEFAULT NULL COMMENT 'minimum preview height px',
    `expand_direction` ENUM('none','vertical','horizontal','both') NOT NULL DEFAULT 'none',
    `expand_factor_height` FLOAT DEFAULT NULL COMMENT 'px per item vertically',
    `expand_factor_width` FLOAT DEFAULT NULL COMMENT 'px per item horizontally',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_block_name` (`name`(191)),
    KEY `idx_type_id` (`type_id`),
    CONSTRAINT `fk_ui_block_type` FOREIGN KEY (`type_id`) REFERENCES `project_design_ui_block_type` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_ui_block_size` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `block_id` INT NOT NULL,
    `viewport_width` INT NOT NULL,
    `width_px` INT NOT NULL,
    `height_px` INT NOT NULL,
    `measured_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_block_viewport` (`block_id`, `viewport_width`),
    KEY `idx_block_id` (`block_id`),
    CONSTRAINT `fk_block_size_block` FOREIGN KEY (`block_id`) REFERENCES `project_design_ui_block` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_design_token` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `description` TEXT DEFAULT NULL,
    `tokens` JSON NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── Project Team ──────────────────────────────────────────────────────────────

CREATE TABLE `project_task_type` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(50) NOT NULL COMMENT 'dev, bug, test, research, plan',
    `title` VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Отображаемое название',
    `description` TEXT DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_type_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `project_team` (
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

-- ─── Browser ───────────────────────────────────────────────────────────────────

-- Сайт — закладка контейнера-браузера: имя и адрес, с которого начинают работу.
-- Живёт в базе, а не в реестре сессий: сессия умирает вместе с контейнером, а
-- список сайтов, с которыми работают, обязан пережить и рестарт, и падение.
--
-- Вход в сайт (cookie, `storage_state`) здесь не хранится: это состояние сессии,
-- у него свой срок жизни и свои секреты, а закладка — только «куда идти».
CREATE TABLE `browser_site` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    `url` VARCHAR(500) NOT NULL COMMENT 'Полный адрес со схемой: сессии заводят по нему',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    -- Имя уникально: карточки различают по нему, два «личного кабинета» с разными
    -- адресами человек не разберёт.
    UNIQUE KEY `uk_browser_site_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Сценарий — последовательность действий над страницей. Хранится здесь, а не в
-- контейнере-браузере: контейнер держит только живые страницы и переживает падение
-- базы, а сценарий должен пережить падение контейнера.
--
-- Паролей в `steps` нет и быть не должно. Шаги ссылаются на `{{переменные}}`,
-- значения приходят на прогон: обычные — в журнал, секретные — мимо него.
CREATE TABLE `browser_scenario` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    -- Цель словами: «войти в админку и оказаться на списке задач». По ней агент
    -- перепишет шаги, когда вёрстка сайта изменится, — сами шаги для этого
    -- бесполезны, они описывают старую вёрстку.
    `goal` VARCHAR(255) NOT NULL DEFAULT '',
    `start_url` VARCHAR(500) NOT NULL DEFAULT '' COMMENT 'Справочно: с какого адреса сценарий начинается',
    `steps` JSON NOT NULL COMMENT 'Массив шагов по схеме src/browser/browser_scenario.py',
    `variables` JSON NOT NULL COMMENT 'Значения по умолчанию; секретов здесь нет',
    -- `broken` ставит не человек, а неудачный прогон: по нему заводится задача
    -- на переписывание, и сценарий не дёргают, пока агент его не починит.
    `status` ENUM('draft','active','broken') NOT NULL DEFAULT 'draft',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_browser_scenario_name` (`name`),
    INDEX `idx_browser_scenario_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Журнал прогонов. Пишется и на успехе тоже: «сценарий сломался» видно только в
-- сравнении с тем, как он работал раньше — сколько шагов проходил и за сколько.
CREATE TABLE `browser_scenario_run` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `scenario_id` INT NOT NULL,
    `session_id` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'Сессия контейнера; живёт в памяти, FK на неё невозможен',
    `status` ENUM('ok','error') NOT NULL,
    `step_no` INT NOT NULL DEFAULT '0' COMMENT 'Номер упавшего шага; 0 — дошли до конца',
    `error` TEXT NOT NULL,
    `trace` JSON NOT NULL COMMENT 'Шаг за шагом: действие, цель, время, ошибка',
    `extract` JSON NOT NULL COMMENT 'Что сценарий забрал со страницы',
    `duration_ms` INT NOT NULL DEFAULT '0',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_bsr_scenario` (`scenario_id`, `id`),
    CONSTRAINT `fk_bsr_scenario` FOREIGN KEY (`scenario_id`) REFERENCES `browser_scenario` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
