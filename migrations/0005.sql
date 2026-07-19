-- Синхронизация с продом (сгенерировано mysql_migration_prod_create).
-- Блок за блоком по каждой таблице: данные прода (старая структура) ->
-- ALTER/CREATE этой таблицы -> локальные правки (upsert, новая структура).

-- ===== agent =====

-- прод: текущее значение измененных строк (для сравнения)
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(30, 4, 'detective_bot', 'Детектив-бот', 'Мастер детективной игры: создает дела и подозреваемых', 12, NULL, 'Ты ведущий детективной игры. Выполняешь команды буквально и возвращаешь ответ в JSON, если об этом просят.', 'Добро пожаловать в детективное агентство!\n\nДоступные команды:\n\n/new_case - начать новое дело\n/accuse - обвинить подозреваемого', 0, 0)
ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `dynamic` = VALUES(`dynamic`);

-- локально: новое/измененное значение
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(30, 4, 'detective_bot', 'Детектив-бот', 'Мастер детективной игры: создает дела и подозреваемых', 12, NULL, 'Ты ведущий детективной игры. Выполняешь команды буквально и возвращаешь ответ в JSON, если об этом просят.', '[[link:http://92.5.17.195:8011/play/detective/|🕵️ Играть]]\n\nДобро пожаловать в детективное агентство!\n\nДоступные команды:\n\n/new_case - начать новое дело\n/accuse - обвинить подозреваемого', 0, 0)
ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `dynamic` = VALUES(`dynamic`);

-- ===== agent_workflow_step =====

-- прод: текущее значение измененных строк (для сравнения)
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(121, 12, 4, 'Вернуть список команд', 0, '{"prompt_user": "%agent_greeting%", "continue_workflow": false, "transitions_after": [], "transitions_before": [{"value": "/new_case", "step_id": "143", "operator": "==", "variable": "prompt_user"}, {"value": "/accuse", "step_id": "131", "operator": "==", "variable": "prompt_user"}]}')
ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

-- локально: новое/измененное значение
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(121, 12, 4, 'Вернуть список команд', 0, '{"prompt_user": "%agent_greeting%", "continue_workflow": false, "transitions_after": [], "transitions_before": [{"value": "/new_case", "step_id": "156", "operator": "==", "variable": "prompt_user"}, {"value": "/accuse", "step_id": "131", "operator": "==", "variable": "prompt_user"}]}'),
(156, 12, 3, 'Очистить старых агентов дела', 16, '{"transitions_before": [], "tool_invoke": {"tool_name": "detective_dynamic_agents_cleanup", "inputs_map": {"session_uuid": "session_uuid"}, "outputs_map": {}}, "transitions_after": [{"variable": "session_uuid", "operator": "exists", "value": "", "step_id": "143"}]}')
ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

-- ===== companion =====

-- локально: новое/измененное значение
INSERT INTO `companion` (`id`, `name`, `title`) VALUES
(4, 'detective_player', 'Игрок')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `title` = VALUES(`title`);

-- ===== user =====

-- user: данные прода (структура отличается - таблица целиком)
INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role_id`, `created_at`) VALUES
(1, 'admin', 'admin@example.com', '$2b$12$HgW3UjBwpAX6vYk5M6JykOM73WQuAVDw/.zHu8DxEZ3p8H0/FySx.', 1, '2026-04-26 09:17:35'),
(2, 'lilia', 'lilia@example.com', '$2b$12$XG.UEUHZz3kkq73DpN52Z.7rqVMgrlCnsbyK2bR2tuXTLkBPhACDK', 2, '2026-04-26 09:17:35'),
(3, 'olga', 'olga@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 3, '2026-04-26 09:17:35'),
(4, 'alena', 'alena@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 4, '2026-04-26 09:17:35')
ON DUPLICATE KEY UPDATE `username` = VALUES(`username`), `email` = VALUES(`email`), `password_hash` = VALUES(`password_hash`), `role_id` = VALUES(`role_id`), `created_at` = VALUES(`created_at`);

ALTER TABLE `user` ADD COLUMN `dynamic` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'Создан рантаймом (guest-сессия PWA), не seed - исключается из экспорта/prod-миграции';

-- user: локальные данные (структура отличается - таблица целиком)
INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role_id`, `created_at`, `dynamic`) VALUES
(1, 'admin', 'admin@example.com', '$2b$12$HgW3UjBwpAX6vYk5M6JykOM73WQuAVDw/.zHu8DxEZ3p8H0/FySx.', 1, '2026-04-26 09:17:35', 0),
(2, 'lilia', 'lilia@example.com', '$2b$12$XG.UEUHZz3kkq73DpN52Z.7rqVMgrlCnsbyK2bR2tuXTLkBPhACDK', 2, '2026-04-26 09:17:35', 0),
(3, 'olga', 'olga@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 3, '2026-04-26 09:17:35', 0),
(4, 'alena', 'alena@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 4, '2026-04-26 09:17:35', 0)
ON DUPLICATE KEY UPDATE `username` = VALUES(`username`), `email` = VALUES(`email`), `password_hash` = VALUES(`password_hash`), `role_id` = VALUES(`role_id`), `created_at` = VALUES(`created_at`), `dynamic` = VALUES(`dynamic`);
