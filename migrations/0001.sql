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
    `value` LONGTEXT,
    CONSTRAINT `fk_settings_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE setting ADD UNIQUE INDEX idx_key_user (`key`, user_id);

-- Таблица фактов (коллекция фактов)
CREATE TABLE `fact_collection` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(40) NOT NULL,
    `language` CHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица фактов
CREATE TABLE `fact` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `collection_id` INT NOT NULL,
    `document` CHAR(250) NOT NULL,
    `group_id` CHAR(250) DEFAULT NULL,
    `category` CHAR(20) DEFAULT NULL,
    `language` CHAR(2) NOT NULL,
    `source_file` CHAR(50) DEFAULT NULL,
    `content` LONGTEXT,
    `qdrant_synced` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_qdrant_synced` (`qdrant_synced`), -- Для фоновой синхронизации
    INDEX `idx_collection_lang` (`collection_id`, `language`), -- Для поиска по контексту
    CONSTRAINT `fk_fact_fact_collection` FOREIGN KEY (`collection_id`) REFERENCES `fact_collection` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица тегов (связь с фактами)
CREATE TABLE `fact_tags` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `fact_id` INT NOT NULL,
    `name` CHAR(100) NOT NULL,
    CONSTRAINT `fk_tags_fact` FOREIGN KEY (`fact_id`) REFERENCES `fact` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица памяти (история диалогов/действий)
CREATE TABLE `agent_memory_short` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL,
    `agent` CHAR(30) NOT NULL,
    `role` CHAR(30) NOT NULL,
    `user_id` INT DEFAULT NULL,
    `kind_type` CHAR(20) NOT NULL,
    `content` LONGTEXT,
    `token` INT DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_session` (`session_uuid`), -- Для быстрой выборки истории
    INDEX `idx_agent_user` (`agent`, `user_id`, `created_at`),
    CONSTRAINT `fk_memory_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;