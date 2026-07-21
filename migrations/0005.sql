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

-- Редактор планов: принимает текущий Markdown плана (plan_current_content) и
-- инструкцию пользователя (prompt_user), возвращает ПОЛНЫЙ обновленный текст
-- плана - шаги/чекбоксы остаются частью Markdown (см. src/uvicorn/routers/telegram_app/telegram_app_plan.py).

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(16, 7, 'plan_editor', 'Редактор планов', 'Применяет инструкцию пользователя к тексту плана (Markdown) и возвращает полный обновленный документ', 1, 0);

--

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(158, 16, 1, 'Применить правку', 0, '{"transitions_before": [], "transitions_after": [], "prompt_user": "Ты - помощник по редактированию текстовых планов в формате Markdown. Тебе дан текущий текст плана и инструкция пользователя по его изменению.\\n\\n=== Текущий текст плана (Markdown) ===\\n%plan_current_content%\\n\\n=== Инструкция пользователя ===\\n%prompt_user%\\n\\n=== Правила ===\\n1. Примени инструкцию к тексту плана максимально точно, не меняя остального без необходимости.\\n2. Шаги плана оформляются как чекбоксы Markdown: \\"- [ ] текст шага\\" (не выполнен) или \\"- [x] текст шага\\" (выполнен). Сохраняй существующую разметку чекбоксов и статус выполнения шагов, если инструкция явно не просит их поменять.\\n3. Если инструкция просит добавить шаг - добавь новый пункт \\"- [ ] ...\\" в подходящее место списка.\\n4. Если инструкция просит переформулировать/удалить/отметить шаг - найди соответствующий пункт по смыслу и измени именно его.\\n5. Верни ТОЛЬКО итоговый полный текст плана целиком в Markdown, без пояснений, без обрамления в кавычки или блоки кода, без вступлений вроде \\"Вот обновленный план:\\".\\n6. Сохраняй общую структуру документа (заголовки, порядок разделов), меняя только то, что просит инструкция."}');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(32, 7, 'plan_editor', 'Редактор планов', 'Служебный агент: применяет инструкцию пользователя к Markdown-тексту плана', 16, NULL, 'Ты внимательный редактор текстовых документов. Точно следуешь инструкциям правки, сохраняя не относящуюся к ним часть текста без изменений.', '', 1, 0);

--

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
(185, 'plan_current_content', 'input', '', 'Текущий Markdown-текст плана (workflow plan_editor)');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(185, 16);
