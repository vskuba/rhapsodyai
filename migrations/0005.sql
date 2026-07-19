-- Синхронизация с продом (сгенерировано mysql_migration_prod_create).
-- Структура: CREATE/ALTER для нового, что появилось локально. Данные: построчный
-- diff по первичному ключу - только затронутые строки. Для измененных строк
-- показаны обе версии (прод для сравнения, затем новая локальная - upsert).

-- прод: текущее значение измененных строк (для сравнения)
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(30, 4, 'detective_bot', 'Детектив-бот', 'Мастер детективной игры: создает дела и подозреваемых', 12, NULL, 'Ты ведущий детективной игры. Выполняешь команды буквально и возвращаешь ответ в JSON, если об этом просят.', 'Добро пожаловать в детективное агентство!\n\nДоступные команды:\n\n/new_case - начать новое дело\n/accuse - обвинить подозреваемого', 0, 0)
ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `dynamic` = VALUES(`dynamic`);

-- локально: новое/измененное значение
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(30, 4, 'detective_bot', 'Детектив-бот', 'Мастер детективной игры: создает дела и подозреваемых', 12, NULL, 'Ты ведущий детективной игры. Выполняешь команды буквально и возвращаешь ответ в JSON, если об этом просят.', '[[link:http://92.5.17.195:8011/play/detective/|🕵️ Играть]]\n\nДобро пожаловать в детективное агентство!\n\nДоступные команды:\n\n/new_case - начать новое дело\n/accuse - обвинить подозреваемого', 0, 0)
ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `dynamic` = VALUES(`dynamic`);
