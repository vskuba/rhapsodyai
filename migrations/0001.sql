CREATE DATABASE IF NOT EXISTS `project` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `project`;

SET FOREIGN_KEY_CHECKS = 0;

-- Удаляем таблицы, если они существуют
DROP TABLE IF EXISTS `user_access_token`;
DROP TABLE IF EXISTS `user_node`;
DROP TABLE IF EXISTS `user_llm`;
DROP TABLE IF EXISTS `tool`;
DROP TABLE IF EXISTS `tool_group`;
DROP TABLE IF EXISTS `workflow_step`;
DROP TABLE IF EXISTS `workflow_step_type`;
DROP TABLE IF EXISTS `workflow_variable`;
DROP TABLE IF EXISTS `workflow`;
DROP TABLE IF EXISTS `fact`;
DROP TABLE IF EXISTS `fact_collection`;
DROP TABLE IF EXISTS `agent_session`;
DROP TABLE IF EXISTS `agent`;
DROP TABLE IF EXISTS `node`;
DROP TABLE IF EXISTS `llm`;
DROP TABLE IF EXISTS `setting`;
DROP TABLE IF EXISTS `role`;
DROP TABLE IF EXISTS `user`;

-- Включаем проверки обратно
SET FOREIGN_KEY_CHECKS = 1;

-- Таблица LLM
CREATE TABLE `llm` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица пользователей
CREATE TABLE `user` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` CHAR(50) NOT NULL,
    `email` CHAR(50) NOT NULL,
    `password_hash` CHAR(100) NOT NULL,
    `role` CHAR(20) NOT NULL DEFAULT 'user',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица токенов доступа пользователей
CREATE TABLE `user_access_token` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `token` CHAR(36) NOT NULL,
    CONSTRAINT `fk_user_access_token_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица ролей
CREATE TABLE `role` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(20) NOT NULL,
    UNIQUE INDEX `ux_role_name` (`name`)
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

CREATE TABLE `node` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `position` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `user_node` (
    `user_id` INT NOT NULL,
    `node_id` INT NOT NULL,
    PRIMARY KEY (`user_id`, `node_id`),
    CONSTRAINT `fk_user_node_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_user_node_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `user_llm` (
    `user_id` INT NOT NULL,
    `llm_id` INT NOT NULL,
    `rate_limit_at` DATETIME DEFAULT NULL,
    PRIMARY KEY (`user_id`, `llm_id`),
    CONSTRAINT `fk_user_llm_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_user_llm_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `session` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `uuid` CHAR(36) NOT NULL,
    `metadata` LONGTEXT DEFAULT NULL,
    UNIQUE INDEX `ui_session_uuid` (`uuid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица инструментов
CREATE TABLE `tool_group` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    UNIQUE INDEX `ux_tool_group_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `tool` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `group_id` INT NULL,
    `path` CHAR(200) DEFAULT NULL,
    `description` LONGTEXT DEFAULT NULL,
    `args` LONGTEXT DEFAULT NULL,
    CONSTRAINT `fk_tool_group` FOREIGN KEY (`group_id`) REFERENCES `tool_group` (`id`) ON DELETE SET NULL,
    UNIQUE INDEX `ux_tool_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица задач
CREATE TABLE `agent_workflow` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `name` CHAR(50) NOT NULL,
    `title` CHAR(50) NOT NULL,
    `description` CHAR(200) NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    CONSTRAINT `workflow_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL,
    UNIQUE INDEX `ux_workflow_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_step_type` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `icon` CHAR(2) NOT NULL,
    `description` CHAR(200) NOT NULL,
    `description_full` LONGTEXT DEFAULT NULL,
    `metadata` LONGTEXT NOT NULL,
    UNIQUE INDEX `ux_workflow_step_type_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_step` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `workflow_id` INT NULL,
    `type_id` INT NULL,
    `title` CHAR(50) NOT NULL,
    `position` INT NOT NULL DEFAULT 0,
    `metadata` LONGTEXT NOT NULL,
    CONSTRAINT `workflow_step_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE SET NULL,
    CONSTRAINT `workflow_step_workflow_step_type` FOREIGN KEY (`type_id`) REFERENCES `agent_workflow_step_type` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_workflow_variable` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `workflow_id` INT NULL,
    `name` CHAR(50) NOT NULL,
    `default` CHAR(200) DEFAULT NULL,
    CONSTRAINT `workflow_variable_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE SET NULL
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
    `llm_id` INT NULL,
    `role_id` INT NULL,
    `position` INT NOT NULL DEFAULT 0,
    CONSTRAINT `ag_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL,
    CONSTRAINT `ag_workflow` FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`) ON DELETE SET NULL,
    CONSTRAINT `ag_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE SET NULL,
    CONSTRAINT `ag_role` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE SET NULL
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