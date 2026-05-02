CREATE DATABASE IF NOT EXISTS `project` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `project`;

SET FOREIGN_KEY_CHECKS = 0;

-- Удаляем таблицы, если они существуют
DROP TABLE IF EXISTS `fact_collection_cashier_service`;
DROP TABLE IF EXISTS `fact_collection_dating_girl_bio`;
DROP TABLE IF EXISTS `fact_collection_soko_menu`;
DROP TABLE IF EXISTS `fact`;
DROP TABLE IF EXISTS `fact_collection`;
DROP TABLE IF EXISTS `agent_session`;
DROP TABLE IF EXISTS `agent`;
DROP TABLE IF EXISTS `agent_node`;
DROP TABLE IF EXISTS `agent_specialization`;
DROP TABLE IF EXISTS `llm`;
DROP TABLE IF EXISTS `setting`;
DROP TABLE IF EXISTS `user`;

-- Включаем проверки обратно
SET FOREIGN_KEY_CHECKS = 1;

-- Таблица пользователей
CREATE TABLE `user` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` CHAR(50) NOT NULL,
    `email` CHAR(50) NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
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

-- Таблица агентов
CREATE TABLE `llm` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_specialization` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(25) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `node` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `position` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица агентов
CREATE TABLE `agent` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `node_id` INT NULL,
    `name` CHAR(50) NOT NULL,
    `title` CHAR(150) NOT NULL,
    `description` CHAR(250) NOT NULL,
    `specialization_id` INT NULL,
    `fact_collection` CHAR(250) DEFAULT NULL,
    `system_prompt` LONGTEXT NOT NULL,
    `tool` CHAR(250) DEFAULT NULL,
    `mcp_server` CHAR(250) DEFAULT NULL,
    `memory_short_disabled` INT NOT NULL DEFAULT 0,
    `llm_id` INT NULL,
    `position` INT NOT NULL DEFAULT 0,
    CONSTRAINT `ag_node` FOREIGN KEY (`node_id`) REFERENCES `node` (`id`) ON DELETE SET NULL,
    CONSTRAINT `ag_specialization` FOREIGN KEY (`specialization_id`) REFERENCES `agent_specialization` (`id`) ON DELETE SET NULL,
    CONSTRAINT `ag_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица памяти (история диалогов/действий)
CREATE TABLE `agent_session` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL,
    `llm_id` INT NULL,
    `agent_id` INT NULL,
    `user_id` INT NULL,
    `role` CHAR(30) NOT NULL,
    `kind_type` CHAR(20) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `token` INT DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_session` (`session_uuid`),
    INDEX `idx_agent_user` (`agent_id`, `user_id`, `created_at`),
    CONSTRAINT `fk_memory_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_memory_agent` FOREIGN KEY (`agent_id`) REFERENCES `agent` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_memory_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- Таблица фактов (коллекция фактов)
CREATE TABLE `fact_collection` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(40) NOT NULL,
    `language` CHAR(40) NOT NULL,
    `user_prompt_header` CHAR(60) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица фактов
CREATE TABLE `fact` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `collection_id` INT NOT NULL,
    `category` CHAR(20) DEFAULT NULL,
    `language` CHAR(2) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `tags` CHAR(250) NOT NULL,
    `qdrant_synced` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_qdrant_synced` (`qdrant_synced`),
    INDEX `idx_collection_lang` (`collection_id`, `language`),
    CONSTRAINT `fk_fact_fact_collection` FOREIGN KEY (`collection_id`) REFERENCES `fact_collection` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблицы коллекции фактов
CREATE TABLE `fact_collection_soko_menu` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `fact_id` INT NOT NULL,
    CONSTRAINT `fk_soko_menu` FOREIGN KEY (`fact_id`) REFERENCES `fact` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `fact_collection_dating_girl_bio` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `fact_id` INT NOT NULL,
    CONSTRAINT `fk_dating_girl_bio` FOREIGN KEY (`fact_id`) REFERENCES `fact` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `fact_collection_cashier_service` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `fact_id` INT NOT NULL,
    CONSTRAINT `fk_cashier_service` FOREIGN KEY (`fact_id`) REFERENCES `fact` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;