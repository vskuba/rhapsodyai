-- Telegram: нода для Telegram Mini App (/telegram-app). Один минимальный
-- агент-ассистент с одношаговым workflow "вопрос-ответ" (просто прогоняет
-- prompt_user через LLM и возвращает ответ) - обслуживает чат внутри Mini App.

INSERT INTO `node` (`id`, `name`, `position`, `migration_file`, `is_catchall`) VALUES
(7, 'Telegram', 3, 'migrations/0005.sql', 0);

--

INSERT INTO `node_llm` (`node_id`, `llm_id`, `rate_limit_at`, `code_error`, `position`) VALUES
(7, 5, NULL, NULL, 2),
(7, 6, NULL, NULL, 5),
(7, 10, NULL, NULL, 6),
(7, 11, NULL, NULL, 1),
(7, 12, NULL, NULL, 4),
(7, 15, NULL, NULL, 3),
(7, 16, NULL, NULL, 7);

--

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(15, 7, 'telegram_chat', 'Telegram чат', 'Простой вопрос-ответ для чата в Telegram Mini App', 0, 0);

--

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(157, 15, 1, 'Ответ', 0, '{"prompt_user":"%prompt_user%","transitions_after":[]}');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(31, 7, 'telegram_assistant', 'Telegram', 'Ассистент для чата в Telegram Mini App', 15, NULL, 'Ты дружелюбный ассистент RhapsodyAi. Отвечай кратко, по делу и на языке пользователя.', 'Привет! Чем могу помочь?', 0, 0);
