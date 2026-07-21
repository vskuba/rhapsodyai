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
(158, 16, 1, 'Применить правку', 0, '{"transitions_before": [], "transitions_after": [], "prompt_user": "Ты - помощник по ведению текстовых планов в формате Markdown. Пользователь постоянно диктует или печатает разную информацию по ходу работы над планом - твоя задача понять смысл нового сообщения и правильно встроить его в уже существующий план.\\n\\n=== Текущий текст плана (Markdown) ===\\n%plan_current_content%\\n\\n=== Новое сообщение пользователя ===\\n%prompt_user%\\n\\n=== Как обрабатывать сообщение ===\\n1. Если сообщение - явная команда об уже существующем пункте (отметить выполненным/невыполненным, переформулировать, удалить) - найди этот пункт по смыслу и примени команду именно к нему.\\n2. Если сообщение - просьба добавить конкретный шаг - добавь новый пункт \\"- [ ] ...\\" в наиболее подходящий по смыслу раздел плана, не обязательно в конец.\\n3. Если сообщение - просто новая информация или заметка без явной команды (факт, идея, деталь), определи, к какому существующему разделу (заголовку) плана она относится по смыслу, и добавь её туда. Если подходящего раздела нет - создай новый раздел (\\"## Название раздела\\") в логичном месте документа.\\n4. Шаги плана - чекбоксы Markdown: \\"- [ ] текст\\" (не выполнен) / \\"- [x] текст\\" (выполнен). Сохраняй существующую разметку и статус чекбоксов, если явно не просят их изменить.\\n5. Группируй связанные пункты под общими заголовками разделов, а не одним плоским списком - если несколько пунктов относятся к одной теме, объединяй их под одним разделом.\\n6. Не удаляй и не меняй ничего, кроме того, что явно требуется из нового сообщения.\\n7. Верни ТОЛЬКО итоговый полный текст плана целиком в Markdown, без пояснений, без обрамления в кавычки или блоки кода, без вступлений вроде \\"Вот обновленный план:\\"."}');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(32, 7, 'plan_editor', 'Редактор планов', 'Служебный агент: применяет инструкцию пользователя к Markdown-тексту плана', 16, NULL, 'Ты внимательный редактор текстовых документов. Точно следуешь инструкциям правки, сохраняя не относящуюся к ним часть текста без изменений.', '', 1, 0);

--

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
(185, 'plan_current_content', 'input', '', 'Текущий Markdown-текст плана (workflow plan_editor)');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(185, 16);

-- Создатель планов: с экрана списка планов (до открытия конкретного плана)
-- пользователь надиктовывает/печатает описание нового плана - агент создает
-- документ Markdown с нуля (первая строка - заголовок "# ..."), см.
-- src/uvicorn/routers/telegram_app/telegram_app_plan.py (POST /telegram-app/plans).
-- Отдельный агент от plan_editor: там разметка "текст+правка", здесь - "создать с нуля".

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(17, 7, 'plan_creator', 'Создатель планов', 'Создает новый план (Markdown) с нуля по инструкции пользователя', 2, 0);

--

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(159, 17, 1, 'Создать план', 0, '{"transitions_before": [], "transitions_after": [], "prompt_user": "Ты - помощник по созданию текстовых планов в формате Markdown. Пользователь (обычно голосом) описал, какой план ему нужен.\\n\\n=== Инструкция пользователя ===\\n%prompt_user%\\n\\n=== Правила ===\\n1. Первая строка результата - короткий заголовок плана в виде \\"# Название плана\\".\\n2. Дальше, если из инструкции понятны шаги, оформляй их как чекбоксы Markdown: \\"- [ ] шаг\\" (пока не выполнен).\\n3. Верни ТОЛЬКО итоговый текст плана целиком в Markdown, без пояснений, без обрамления в кавычки или блоки кода, без вступлений."}');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(33, 7, 'plan_creator', 'Создатель планов', 'Служебный агент: создает новый план (Markdown) по инструкции пользователя', 17, NULL, 'Ты внимательный помощник по составлению структурированных текстовых планов.', '', 2, 0);
