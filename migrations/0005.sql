-- Синхронизация с продом (сгенерировано mysql_migration_prod_create).
-- Структура: CREATE/ALTER для нового, что появилось локально. Данные: построчный
-- diff по первичному ключу - только затронутые строки. Для измененных строк
-- показаны обе версии (прод для сравнения, затем новая локальная - upsert).

-- прод: текущее значение измененных строк (для сравнения)
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(24, 6, 'mysql_export', 'Mysql export', 'Служебный агент для dev-операций', 8, '{}', 'Ты служебный dev-агент. Выполняешь технические операции по командам.', 'Привет! Я Dev bot.\n\nДоступные команды:\n\n[[Экспорт ноды Dashboard]]\n\n[[Экспорт ноды Dating]]\n\n[[Экспорт ноды Detective]]\n\n[[Создать миграцию на прод]] - сравнивает структуру и данные прода с локальными (как migration diff в ORM) и создает готовую миграцию: структура - только то, чего не хватает на проде; данные - прод как основа, локальные правки поверх (upsert), только по таблицам, где данные реально отличаются.', 0, 0)
ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `dynamic` = VALUES(`dynamic`);

-- локально: новое/измененное значение
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(24, 6, 'mysql_export', 'Mysql export', 'Служебный агент для dev-операций', 8, '{}', 'Ты служебный dev-агент. Выполняешь технические операции по командам.', 'Привет! Я Dev bot.\n\nДоступные команды:\n\n[[Экспорт ноды Dashboard]]\n\n[[Экспорт ноды Dating]]\n\n[[Экспорт ноды Detective]]\n\n[[Создать миграцию на прод]] - сравнивает структуру и данные прода с локальными (как migration diff в ORM) и создает готовую миграцию: структура - только то, чего не хватает на проде; данные - построчный diff по первичному ключу, только новые/измененные локально строки (upsert) и строки, существующие только на проде.', 0, 0)
ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `dynamic` = VALUES(`dynamic`);

-- прод: текущее значение измененных строк (для сравнения)
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(61, 8, 4, 'Подсказка', 7, '{"prompt_user": "Привет! Я Dev bot.\\n\\nДоступные команды:\\n\\n[[Экспорт ноды Dashboard]]\\n\\n[[Экспорт ноды Dating]]\\n\\n[[Экспорт ноды Detective]]\\n\\n[[Создать миграцию на прод]] - сравнивает структуру и данные прода с локальными (как migration diff в ORM) и создает готовую миграцию: структура - только то, чего не хватает на проде; данные - прод как основа, локальные правки поверх (upsert), только по таблицам, где данные реально отличаются.", "continue_workflow": false, "transitions_after": [], "transitions_before": []}')
ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

-- локально: новое/измененное значение
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(61, 8, 4, 'Подсказка', 7, '{"prompt_user": "Привет! Я Dev bot.\\n\\nДоступные команды:\\n\\n[[Экспорт ноды Dashboard]]\\n\\n[[Экспорт ноды Dating]]\\n\\n[[Экспорт ноды Detective]]\\n\\n[[Создать миграцию на прод]] - сравнивает структуру и данные прода с локальными (как migration diff в ORM) и создает готовую миграцию: структура - только то, чего не хватает на проде; данные - построчный diff по первичному ключу, только новые/измененные локально строки (upsert) и строки, существующие только на проде.", "continue_workflow": false, "transitions_after": [], "transitions_before": []}')
ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
