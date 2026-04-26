-- Таблица пользователей
CREATE TABLE `user` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` CHAR(50) NOT NULL,
    `email` CHAR(50) NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица настроек (связь с user)
CREATE TABLE `settings` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` CHAR(50) NOT NULL,
    `user_id` INT DEFAULT NULL,
    `value` LONGTEXT,
    CONSTRAINT `fk_settings_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица фактов
CREATE TABLE `fact` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `document` CHAR(250) NOT NULL,
    `group_id` CHAR(250) DEFAULT NULL,
    `category` CHAR(20) DEFAULT NULL,
    `language` CHAR(2) NOT NULL, -- В вашем списке было дважды, оставил один
    `source_file` CHAR(50) DEFAULT NULL,
    `content` LONGTEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица тегов (связь с фактами)
CREATE TABLE `tags` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `fact_id` INT NOT NULL,
    `name` CHAR(100) NOT NULL,
    CONSTRAINT `fk_tags_fact` FOREIGN KEY (`fact_id`) REFERENCES `fact` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица памяти (история диалогов/действий)
CREATE TABLE `memory` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `agent` CHAR(30) NOT NULL,
    `role` CHAR(30) NOT NULL,
    `user_id` INT DEFAULT NULL,
    `content` LONGTEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `fk_memory_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;