CREATE DATABASE IF NOT EXISTS `project` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `project`;

SET FOREIGN_KEY_CHECKS = 0;

-- Удаляем таблицы, если они существуют
DROP TABLE IF EXISTS `agent_workflow_run_step`;
DROP TABLE IF EXISTS `agent_workflow_run`;
DROP TABLE IF EXISTS `agent_session`;
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
DROP TABLE IF EXISTS `user_llm`;
DROP TABLE IF EXISTS `user_node`;
DROP TABLE IF EXISTS `setting`;
DROP TABLE IF EXISTS `node`;
DROP TABLE IF EXISTS `user_access_token`;
DROP TABLE IF EXISTS `user`;
DROP TABLE IF EXISTS `role`;
DROP TABLE IF EXISTS `llm`;

-- Включаем проверки обратно
SET FOREIGN_KEY_CHECKS = 1;

-- Таблица LLM
CREATE TABLE `llm` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL
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
    `position` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица настроек (связь с user)
CREATE TABLE `setting` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `key` CHAR(50) NOT NULL,
    `user_id` INT DEFAULT NULL,
    `value` LONGTEXT NOT NULL,
    CONSTRAINT `fk_settings_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE setting ADD UNIQUE INDEX idx_key_user (`key`, user_id);

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
    `status_code` INT NULL,                            -- 200 = успех; 429/413/402/503/500 = ошибка
    `duration_ms` INT NULL,                            -- время ответа провайдера в мс
    `error` VARCHAR(255) NULL,                         -- краткий текст ошибки
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_llm_request_llm` (`llm_id`, `created_at`),
    INDEX `idx_llm_request_created` (`created_at`),
    CONSTRAINT `fk_llm_request_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_llm_request_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `user_llm` (
    `user_id` INT NOT NULL,
    `llm_id` INT NOT NULL,
    `rate_limit_at` DATETIME DEFAULT NULL,             -- время последней ошибки провайдера (модель уходит в конец очереди)
    `code_error` INT DEFAULT NULL,                     -- HTTP-код ошибки провайдера (429/413/402/503)
    `position` INT DEFAULT NULL,
    PRIMARY KEY (`user_id`, `llm_id`),
    CONSTRAINT `fk_user_llm_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_user_llm_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE CASCADE
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

-- Таблица фактов
CREATE TABLE `fact` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `collection_id` INT NOT NULL,
    `document_id` CHAR(100) NULL COMMENT 'tag:extract|type:string|desc:Document ID string (example: dasha)',
    `document_title` CHAR(200) NULL,                   -- заголовок документа: title сущности агента (заполняется кодом, не LLM)
    `file_id` CHAR(100) NULL COMMENT 'tag:extract|type:string|desc:File ID as key for single storage (example: filename.pdf)',
    `category` CHAR(50) DEFAULT NULL COMMENT 'tag:extract|type:string|desc:High-level classification (example: delivery)',
    `language` CHAR(2) NOT NULL COMMENT 'tag:extract|type:string|desc:The language two char format, ISO 639-1 code (example: en)',
    `document` LONGTEXT NOT NULL COMMENT 'tag:extract|type:string|desc:The clean, factual text extracted from the source',
    `tags` CHAR(250) NOT NULL COMMENT 'tag:extract|type:array_string|desc:A comma-separated list of tags extracted from the source (example: tag1,tag2,tag3)',
    `qdrant_synced` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_qdrant_synced` (`qdrant_synced`),
    INDEX `idx_collection_lang` (`collection_id`, `language`),
    CONSTRAINT `fk_fact_fact_collection` FOREIGN KEY (`collection_id`) REFERENCES `fact_collection` (`id`) ON DELETE CASCADE
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

-- Журнал выполнения workflow: один запуск (включая вложенные sub-workflow через parent_run_id)
CREATE TABLE `agent_workflow_run` (
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
    CONSTRAINT `fk_wr_run_parent` FOREIGN KEY (`parent_run_id`) REFERENCES `agent_workflow_run` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Журнал выполнения workflow: выполненный шаг (вход/выход/переход/длительность)
CREATE TABLE `agent_workflow_run_step` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `run_id` INT NOT NULL,
    `exec_index` INT NOT NULL,                   -- порядковый номер выполнения (не position шага)
    `step_id` INT NULL,
    `step_title` CHAR(100) DEFAULT NULL,
    `step_type` CHAR(50) DEFAULT NULL,
    `metadata_rendered` LONGTEXT NULL,           -- вход: metadata после рендера %переменных%
    `variables_changed` LONGTEXT NULL,           -- выход: JSON измененных шагом переменных
    `output` LONGTEXT NULL,                      -- ответ LLM / результат инструмента / результат sub-workflow
    `transition` LONGTEXT NULL,                  -- сработавший переход: {phase, condition, to_step_id}
    `status` ENUM('success', 'error', 'retry') NOT NULL DEFAULT 'success',
    `error` LONGTEXT NULL,
    `created_at` DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    `duration_ms` INT NULL,
    INDEX `idx_workflow_run_step_run` (`run_id`, `exec_index`),
    CONSTRAINT `fk_wrs_run` FOREIGN KEY (`run_id`) REFERENCES `agent_workflow_run` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
