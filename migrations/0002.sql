-- Системные данные: не относятся ни к одному подпроекту (ноде) - LLM, пользователи,
-- роли, ноды, настройки, инструменты, служебные workflow (Cashier/Soko/Test/Dev,
-- переводчик, фактчек). Данные Dating - в 0003.sql, Detective - в 0004.sql.

INSERT INTO `llm` (`id`, `name`) VALUES
(1, 'openrouter/google/gemma-4-31b:free'),
(2, 'openrouter/openai/gpt-oss-120b:free'),
(3, 'openrouter/qwen/qwen3-next-80b-a3b-instruct:free'),
(4, 'ollama/qwen2.5:14b'),
(5, 'groq/llama-3.3-70b-versatile'),
(6, 'groq/openai/gpt-oss-120b'),
(7, 'gemini/gemini-3-flash-preview'),
(8, 'gemini/gemini-3.1-flash-lite'),
(9, 'gemini/gemini-2.5-pro'),
(10, 'mistral/mistral-large-2512'),
(11, 'mistral/mistral-medium-latest'),
(12, 'mistral/mistral-medium-2508'),
(13, 'mistral/mistral-medium-2505'),
(14, 'huggingface/meta-llama/Llama-3.3-70B-Instruct'),
(15, 'cerebras/gpt-oss-120b'),
(16, 'cerebras/gemma-4-31b'),
(17, 'openai/gpt-5.2'),
(18, 'openai/gpt-5.3-codex'),
(19, 'ollama/qwen2.5:7b');

--

INSERT INTO `role` (`id`, `name`) VALUES
(1, 'admin'),
(2, 'manager_dating'),
(3, 'manager_cashier'),
(4, 'manager_dating_junior');

-- Password: 14Orca_45
-- Password: user123

INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role_id`, `created_at`, `dynamic`) VALUES
(1, 'admin', 'admin@example.com', '$2b$12$h4r.DMSVURAOMZGzLk1QXegad/PwgaNI/aMu0AKvdGXIyW1KARoke', 1, '2026-04-26 09:17:35', 0),
(2, 'lilia', 'lilia@example.com', '$2b$12$XG.UEUHZz3kkq73DpN52Z.7rqVMgrlCnsbyK2bR2tuXTLkBPhACDK', 2, '2026-04-26 09:17:35', 0),
(3, 'olga', 'olga@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 3, '2026-04-26 09:17:35', 0),
(4, 'alena', 'alena@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 4, '2026-04-26 09:17:35', 0);

--

INSERT INTO `user_access_token` (`id`, `user_id`, `token`) VALUES
(1, 2, '8fd15581-36ae-48ed-812f-3b3d11d427f0'),
(2, 1, 'a0000000-1111-4444-bbbb-000000000001');

--

INSERT INTO `node` (`id`, `name`, `position`, `migration_file`, `is_catchall`) VALUES
(2, 'Dating', 1, 'migrations/0003.sql', 0),
(4, 'Detective', 2, 'migrations/0004.sql', 0),
(6, 'Dashboard', 0, 'migrations/0002.sql', 1);

--

INSERT INTO `setting` (`id`, `key`, `user_id`, `node_id`, `value`) VALUES
(1, 'llm_error_reset_hours', NULL, NULL, '1'),
(2, 'timezone', NULL, NULL, '+3'),
(3, 'languages', NULL, NULL, 'ru'),
(4, 'languages', NULL, 2, 'ru,en'),
(5, 'whisper_model_name', NULL, NULL, 'base');

--

-- Список LLM ноды Dashboard (catchall) - также фоллбэк для агентов без своей
-- ноды (node_id IS NULL: soko, translator, fact_verifier, jira, github, weather).
-- Наборы для Dating/Detective/Telegram - в их файлах миграции (0003/0004/0005.sql)
INSERT INTO `node_llm` (`node_id`, `llm_id`, `rate_limit_at`, `code_error`, `position`) VALUES
(6, 5, NULL, NULL, 1),
(6, 6, NULL, NULL, 4),
(6, 10, NULL, NULL, 5),
(6, 11, NULL, NULL, 0),
(6, 12, NULL, NULL, 3),
(6, 15, NULL, NULL, 2),
(6, 16, NULL, NULL, 6);

--

INSERT INTO `llm_request` (`id`, `llm_id`, `user_id`, `status_code`, `duration_ms`, `error`, `created_at`) VALUES
(1, 11, 1, 200, 25171, NULL, '2026-07-19 14:01:38'),
(2, 11, 1, 200, 18968, NULL, '2026-07-19 14:03:30'),
(3, 11, 1, 200, 17767, NULL, '2026-07-19 14:04:23'),
(4, 11, 1, 200, 20392, NULL, '2026-07-19 14:05:31'),
(5, 11, 1, 200, 17122, NULL, '2026-07-19 14:13:25'),
(6, 11, 1, 200, 2256, NULL, '2026-07-19 14:15:27'),
(7, 11, 1, 200, 37283, NULL, '2026-07-19 14:17:22'),
(8, 11, 1, 200, 23206, NULL, '2026-07-19 14:18:01'),
(9, 11, 1, 200, 19782, NULL, '2026-07-19 14:19:01'),
(10, 11, 1, 200, 29984, NULL, '2026-07-19 14:24:54'),
(11, 11, 1, 200, 42807, NULL, '2026-07-19 14:28:43');

--

INSERT INTO `agent_workflow_step_type` (`id`, `name`, `icon`, `description`, `description_full`, `metadata`) VALUES
(1, 'return_response_llm', '↩L', 'Вернуть LLM ответ', 'Собираем полный запрос на LLM с учетом короткой и длинной памяти, всей связанной информации в БД и отдаем LLM для формирования наиболее качественного ответа.', ''),
(2, 'llm_to_json', '🧠', 'LLM -> JSON', 'Ожидает ответ от LLM в виде JSON. Далее каждый ключ JSON доступен в последующих шагах', ''),
(3, 'tool_invoke', '⚙️', 'Вызов инструмента', 'Вызываем инструмент. Передаем в аргументы текущие переменные и сохраняем ответ в переменные.', ''),
(4, 'return_response_text', '↩T', 'Вернуть текстовый ответ', 'Возращаем текстовый ответ на основе шаблона из переменных', ''),
(5, 'variable_conversion', '❴❵', 'Переменные', 'Переопределяем значения переменных', ''),
(6, 'workflow_invoke', '🇼', 'Вызов workflow', 'Вызываем вложенный workflow (sub-workflow): передаем входящие переменные, получаем результат в переменную и продолжаем выполнение.', '');

--

INSERT INTO `companion` (`id`, `name`, `title`) VALUES
(1, 'Vadim', 'Vadim'),
(2, 'Olenka', 'Olenka'),
(3, 'user_admin', 'admin'),
(4, 'detective_player', 'Игрок');

--

INSERT INTO `fact_collection` (`id`, `node_id`, `name`, `title`, `field`, `position`, `language`, `description`) VALUES
(1, NULL, 'cashier_service', 'cashier_service', 'document_id,category,language,document,tags', 0, 'ru', 'Микросервисы'),
(3, NULL, 'soko_menu', 'soko_menu', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Меню');

--

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(1, NULL, 'response_cashier', 'Чат кашира', 'Ответить пользователю', 0, 0),
(3, NULL, 'response_soko', 'Чат суши-бара', 'Ответить пользователю', 0, 0),
(4, NULL, 'test', 'Test', 'Simple test workflow', -1, 0),
(8, 6, 'mysql_export_tables', 'Экспорт таблиц', 'Экспортирует таблицы БД по точным именам в миграцию 0002.sql: команда «Экспорт <таблица1>,<таблица2> таблиц»', 0, 0),
(9, 6, 'workflow_shell_test', 'Workflow оболочка', 'Оболочка-тестер: LLM играет собеседника, в цикле вызывает целевой workflow (test_workflow_id), ведет диалог в отдельной сессии и возвращает стенограмму', 0, 0),
(10, NULL, 'translator', 'Переводчик', 'Служебный workflow автоперевода: переводит текст с language_from на language_to; вне ноды — доступен всем (кнопка перевода в переключателе языков)', 0, 0),
(11, NULL, 'fact_verify', 'Фактчек', 'Служебный workflow: проверяет привязки факта к реальному миру веб-поиском и исправляет противоречия', 0, 0);

--

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(1, 1, 1, 'мой ответ', 2, '{"prompt_user":"%prompt_user%","transitions_after":[]}'),
(2, 1, 3, 'мой инструмент', 1, '{"prompt_user":"ok","transitions_after":[],"tool_invoke":{"tool_name":"github_user_info","inputs_map":{"random":"facts"},"outputs_map":{"login":"tags","name":"prompt_user","email":"facts"}}}'),
(4, 3, 1, 'мой ответ', 0, ''),
(5, 3, 3, 'мой поиск', 0, ''),
(7, 1, 2, 'запрос LLM', 0, '{"llm_to_json_variable":[{"variable":"tags","text":"распарсить текст на таги"}],"prompt_user":"%prompt_user%\n\n=== Important information about final response ===\nPlease return your response in JSON format. The JSON response must contain follow keys: \n- \\"tags\\": распарсить текст на таги\n\nExample of JSON response:\n{\n  \\"tags\\": \\"распарсить текст на таги\\"\n}","transitions_after":[{"variable":"facts","operator":"==","value":"ok","step_id":"1"}]}'),
(8, 4, 1, 'Вернуть ответ', 3, '{"prompt_user":"%session_messages_rendered%\n\n[Пользователь пишет]:\n\n%prompt_user%","transitions_after":[]}'),
(9, 4, 2, 'LLM ответ JSON', 0, '{"llm_to_json_variable":[{"variable":"tags","text":"распарсить текст на таги"}],"transitions_before":[{"variable":"prompt_user","operator":"==","value":"be","step_id":"12"}],"transitions_after":[{"variable":"prompt_user","operator":"==","value":"go","step_id":"12"}],"prompt_user":"%prompt_user%\n\n=== Important information about final response ===\nPlease return your response in JSON format. The JSON response must contain follow keys: \n- \\"tags\\": распарсить текст на таги\n\nExample of JSON response:\n{\n  \\"tags\\": \\"распарсить текст на таги\\"\n}"}'),
(10, 4, 3, 'session_messages', 1, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit"},"outputs_map":{"list":"session_messages"}},"transitions_after":[]}'),
(11, 4, 3, 'session_messages_render', 2, '{"tool_invoke":{"tool_name":"session_messages_render","inputs_map":{"messages":"session_messages"},"outputs_map":{"str":"session_messages_rendered"}},"transitions_after":[]}'),
(12, 4, 4, 'return_response_text', 4, '{"prompt_user":"Команда [[/go]] найдена","transitions_after":[]}'),
(61, 8, 4, 'Подсказка', 7, '{"prompt_user": "Привет! Я Dev bot.\\n\\nДоступные команды:\\n\\n[[Экспорт ноды Dashboard]]\\n\\n[[Экспорт ноды Dating]]\\n\\n[[Экспорт ноды Detective]]\\n\\n[[Создать миграцию на прод]] - сравнивает структуру и данные прода с локальными (как migration diff в ORM) и создает готовую миграцию: структура - только то, чего не хватает на проде; данные - построчный diff по первичному ключу, только новые/измененные локально строки (upsert) и строки, существующие только на проде.", "continue_workflow": false, "transitions_after": [], "transitions_before": []}'),
(66, 9, 3, 'session_uuid_create', 24, '{"tool_invoke":{"tool_name":"session_uuid_create","inputs_map":{},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(67, 9, 2, 'Сообщение тестера', 25, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"test_message","text":"следующее сообщение собеседника-тестера: короткое, естественное, по сценарию"}],"prompt_user":"Ты тестировщик чат-агента: играешь роль собеседника по имени %companion_title%, который переписывается с агентом %target_agent_title%.\\n\\n=== Сценарий тестирования ===\\n%prompt_user%\\n%if test_dialog%\\n\\n=== Диалог до этого момента ===\\n%test_dialog%\\n%endif%\\n\\nПридумай СЛЕДУЮЩЕЕ сообщение собеседника: короткое (до 30 слов), естественное, продолжает диалог и следует сценарию. Не повторяй уже отправленные сообщения.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"test_message\\": следующее сообщение собеседника\\n\\nExample of JSON response:\\n{\\n  \\"test_message\\": \\"Привет! Чем увлекаешься?\\"\\n}"}'),
(68, 9, 6, 'Вызов тестируемого workflow', 26, '{"workflow_invoke":{"workflow_id":"%test_workflow_id%","inputs_map":{"prompt_user":"test_message","prompt_system":"target_prompt_system","session_uuid":"session_uuid_create_66_result_str","agent_id":"target_agent_id","agent_name":"target_agent_name","agent_title":"target_agent_title","girl_id":"girl_id","companion_id":"companion_id","companion_title":"companion_title","companion_name":"companion_name","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(69, 9, 3, 'session_message_add', 27, '{"tool_invoke": {"tool_name": "session_message_add", "inputs_map": {"user_id": "user_id", "agent_id": "target_agent_id", "companion_id": "companion_id", "session_uuid": "session_uuid_create_66_result_str", "user_message": "test_message", "agent_response": "workflow_invoke_68_result_str"}, "outputs_map": {}}, "transitions_after": [], "transitions_before": []}'),
(70, 9, 3, 'counter_increment', 28, '{"tool_invoke":{"tool_name":"counter_increment","inputs_map":{"value":"test_iteration"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(71, 9, 5, 'Обновить контекст', 29, '{"transitions_before":[],"transitions_after":[{"variable":"test_iteration","operator":"<","value":"%test_iterations_limit%","step_id":"67"}],"variable_conversion":[{"variable":"test_dialog","text":"%test_dialog%\\n[%companion_title%]: %test_message%\\n[%target_agent_title%]: %workflow_invoke_68_result_str%"},{"variable":"test_iteration","text":"%counter_increment_70_result_int%"}]}'),
(72, 9, 4, 'Отчет теста', 30, '{"transitions_before":[],"transitions_after":[],"prompt_user":"✅ Тест завершен: %test_iteration% итераций workflow #%test_workflow_id%.\\n\\n=== Диалог ===\\n%test_dialog%\\n\\nСессия диалога: %session_uuid_create_66_result_str%","continue_workflow":false}'),
(73, 9, 5, 'Параметры: список нод', 0, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"find_table","text":"node"},{"variable":"find_criteria","text":"{}"}]}'),
(74, 9, 3, 'Найти ноды', 1, '{"tool_invoke":{"tool_name":"mysql_find_by","inputs_map":{"table_name":"find_table","criteria":"find_criteria"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(75, 9, 3, 'Названия нод', 2, '{"tool_invoke":{"tool_name":"dict_column","inputs_map":{"data":"mysql_find_by_74_result_list","column_name":"chips_column"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(76, 9, 3, 'Чипсы нод', 3, '{"tool_invoke":{"tool_name":"list_render","inputs_map":{"items":"dict_column_75_result_list","template":"chips_template","separator":"chips_separator"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(77, 9, 4, 'Спросить ноду', 4, '{"transitions_before":[],"transitions_after":[],"prompt_user":"🧪 Тестовый прогон workflow.\\n\\nВ какой ноде тестируем? Выберите:\\n\\n%list_render_76_result_str%","continue_workflow":true}'),
(78, 9, 5, 'Параметры: нода по имени', 5, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"find_table","text":"node"},{"variable":"find_criteria","text":"{\\"name\\":\\"%prompt_user%\\"}"}]}'),
(79, 9, 3, 'Найти ноду', 6, '{"tool_invoke":{"tool_name":"mysql_find_one_by","inputs_map":{"table_name":"find_table","criteria":"find_criteria"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(80, 9, 5, 'Параметры: workflow ноды', 7, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"find_table","text":"agent_workflow"},{"variable":"find_criteria","text":"{\\"node_id\\": %mysql_find_one_by_79_result_id%, \\"subflow\\": 0}"}]}'),
(81, 9, 3, 'Найти workflow ноды', 8, '{"tool_invoke":{"tool_name":"mysql_find_by","inputs_map":{"table_name":"find_table","criteria":"find_criteria"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(82, 9, 3, 'Названия workflow', 9, '{"tool_invoke":{"tool_name":"dict_column","inputs_map":{"data":"mysql_find_by_81_result_list","column_name":"chips_column"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(83, 9, 3, 'Чипсы workflow', 10, '{"tool_invoke":{"tool_name":"list_render","inputs_map":{"items":"dict_column_82_result_list","template":"chips_template","separator":"chips_separator"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(84, 9, 4, 'Спросить workflow', 11, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Нода «%prompt_user%». Какой workflow тестируем?\\n\\n%list_render_83_result_str%","continue_workflow":true}'),
(85, 9, 5, 'Параметры: workflow по имени', 12, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"find_table","text":"agent_workflow"},{"variable":"find_criteria","text":"{\\"name\\":\\"%prompt_user%\\"}"}]}'),
(86, 9, 3, 'Найти workflow', 13, '{"tool_invoke":{"tool_name":"mysql_find_one_by","inputs_map":{"table_name":"find_table","criteria":"find_criteria"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(87, 9, 5, 'Параметры: агенты workflow', 14, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"test_workflow_id","text":"%mysql_find_one_by_86_result_id%"},{"variable":"find_table","text":"agent"},{"variable":"find_criteria","text":"{\\"workflow_id\\": %mysql_find_one_by_86_result_id%}"}]}'),
(88, 9, 3, 'Найти агентов', 15, '{"tool_invoke":{"tool_name":"mysql_find_by","inputs_map":{"table_name":"find_table","criteria":"find_criteria"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(89, 9, 3, 'Имена агентов', 16, '{"tool_invoke":{"tool_name":"dict_column","inputs_map":{"data":"mysql_find_by_88_result_list","column_name":"chips_column"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(90, 9, 3, 'Чипсы агентов', 17, '{"tool_invoke":{"tool_name":"list_render","inputs_map":{"items":"dict_column_89_result_list","template":"chips_template","separator":"chips_separator"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(91, 9, 4, 'Спросить агента', 18, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Workflow «%prompt_user%». От имени какого агента отвечать?\\n\\n%list_render_90_result_str%","continue_workflow":true}'),
(92, 9, 5, 'Параметры: агент по имени', 19, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"find_table","text":"agent"},{"variable":"find_criteria","text":"{\\"name\\":\\"%prompt_user%\\",\\"workflow_id\\": %test_workflow_id%}"}]}'),
(93, 9, 3, 'Найти агента', 20, '{"tool_invoke":{"tool_name":"mysql_find_one_by","inputs_map":{"table_name":"find_table","criteria":"find_criteria"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(94, 9, 3, 'girl_id агента', 21, '{"tool_invoke":{"tool_name":"dict_column","inputs_map":{"data":"mysql_find_one_by_93_result_workflow_variable","column_name":"doc_key"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(95, 9, 5, 'Применить конфиг', 22, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"target_agent_id","text":"%mysql_find_one_by_93_result_id%"},{"variable":"target_agent_name","text":"%mysql_find_one_by_93_result_name%"},{"variable":"target_agent_title","text":"%mysql_find_one_by_93_result_title%"},{"variable":"target_prompt_system","text":"%mysql_find_one_by_93_result_prompt_system%"},{"variable":"girl_id","text":"%dict_column_94_result_str%"}]}'),
(96, 9, 4, 'Спросить сценарий', 23, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Цель: %target_agent_title% (workflow #%test_workflow_id%, документ «%girl_id%»).\\n\\nНапишите сценарий тестирования: кто собеседник, о чем говорит, чего добивается. Итераций диалога: %test_iterations_limit%.\\n\\nЗаготовки (клик вставит текст в поле, отредактируйте под себя):\\n\\n[[+Ты мужчина 35 лет, познакомился с %target_agent_title% в приложении знакомств. Пиши коротко и неформально, как в мессенджере. Расспрашивай о ее увлечениях, работе и прошлом, делись фактами о себе (работа, машина, хобби) и мягко добивайся личной встречи.]]\\n\\n[[+Ты скептичный собеседник: подозреваешь, что %target_agent_title% — бот. Задавай личные вопросы о ее прошлом, ищи противоречия в ответах, возвращайся к ранее сказанному и проверяй, помнит ли она детали переписки.]]\\n\\n[[+Ты немногословный мужчина: пишешь по 2-5 слов, иногда с опечатками, отвечаешь односложно и редко задаешь вопросы. Проверка, как %target_agent_title% поддерживает вялый диалог.]]","continue_workflow":true}'),
(110, 10, 1, 'Перевод', 0, '{"transitions_before": [], "transitions_after": [], "prompt_user": "Переведи текст с языка [%language_from%] на язык [%language_to%].\\n\\n=== Текст ===\\n%prompt_user%\\n\\n=== Правила ===\\n1. Верни ТОЛЬКО перевод, без пояснений, вступлений и кавычек вокруг результата.\\n2. Сохраняй стиль, тон, регистр и форматирование исходного текста (переносы строк, списки, эмодзи).\\n3. Имена собственные не переводи.\\n4. Если текст уже на целевом языке - верни его без изменений."}'),
(116, 11, 2, 'Анализ факта', 0, '{"transitions_before":[],"transitions_after":[{"variable":"verify_query","operator":"==","value":"0","step_id":"119"}],"llm_to_json_variable":[{"variable":"verify_query","text":"поисковый запрос для проверки привязки факта к реальности или 0, если проверять нечего"}],"prompt_user":"=== Факт из базы ===\\n%prompt_user%\\n\\n=== Что нужно ===\\nПерсонаж выдуманный, но привязки к реальному миру должны быть правдоподобны. Найди в факте привязки, которые можно проверить веб-поиском: школы и вузы с номерами, адреса, названия заведений, утверждения что находится где (район, город). Если такие есть - сформулируй ОДИН короткий поисковый запрос для проверки самой конкретной привязки (например: школа 157 Киев какой район). Если проверяемых привязок нет (вкусы, характер, обобщенные места вроде кафе в центре) - верни 0.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"verify_query\\": поисковый запрос или 0, если проверять нечего\\n\\nExample of JSON response:\\n{\\n  \\"verify_query\\": \\"школа 157 Киев какой район\\"\\n}\\n\\nExample of JSON response one more:\\n{\\n  \\"verify_query\\": 0\\n}"}'),
(117, 11, 3, 'web_search', 1, '{"tool_invoke":{"tool_name":"web_search","inputs_map":{"query":"verify_query","limit":"verify_search_limit"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(118, 11, 2, 'Вердикт', 2, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"verify_status","text":"вердикт проверки: ok | corrected | unverifiable"},{"variable":"document_corrected","text":"исправленный текст факта при corrected, иначе пустая строка"}],"prompt_user":"=== Проверяемый факт ===\\n%prompt_user%\\n\\n=== Поисковый запрос ===\\n%verify_query%\\n\\n=== Результаты веб-поиска ===\\n%web_search_117_result_results%\\n\\n=== Что нужно ===\\nСверь привязки факта с результатами поиска и вынеси вердикт:\\n- ok: привязки не противоречат реальности\\n- corrected: есть противоречие (заведение в другом районе, не существует) - исправь факт минимальной правкой, сохранив суть: замени привязку на реальную из результатов поиска или обобщи (школа рядом с домом)\\n- unverifiable: результаты поиска не позволяют судить\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"verify_status\\": ok | corrected | unverifiable\\n- \\"document_corrected\\": исправленный полный текст факта, только при corrected; иначе пустая строка\\n\\nExample of JSON response:\\n{\\n  \\"verify_status\\": \\"corrected\\",\\n  \\"document_corrected\\": \\"Училась в лицее на Оболони, недалеко от дома\\"\\n}"}'),
(119, 11, 3, 'Сохранить вердикт', 3, '{"tool_invoke":{"tool_name":"fact_verify_result_save","inputs_map":{"fact_id":"fact_id","verify_status":"verify_status","document_corrected":"document_corrected"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(120, 11, 4, 'Отчет', 4, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%verify_status%","continue_workflow":false}'),
(145, 8, 3, 'Извлечь имя ноды', 0, '{"tool_invoke": {"tool_name": "text_regex_extract", "inputs_map": {"text": "prompt_user", "pattern": "export_node_regex"}, "outputs_map": {}}, "transitions_after": [{"value": "", "step_id": "61", "operator": "empty", "variable": "text_regex_extract_145_result_str"}], "transitions_before": [{"value": "Создать миграцию на прод", "step_id": "152", "operator": "==", "variable": "prompt_user"}]}'),
(146, 8, 5, 'Критерии поиска ноды', 2, '{"transitions_before": [], "transitions_after": [], "variable_conversion": [{"variable": "export_node_find_table", "text": "node"}, {"variable": "export_node_find_criteria", "text": "{\\"name\\": \\"%text_regex_extract_145_result_str%\\"}"}]}'),
(147, 8, 3, 'Найти ноду', 4, '{"transitions_before": [], "transitions_after": [], "tool_invoke": {"tool_name": "mysql_find_one_by", "inputs_map": {"table_name": "export_node_find_table", "criteria": "export_node_find_criteria"}, "outputs_map": {}}}'),
(148, 8, 3, 'mysql_export_node_to_migration', 5, '{"tool_invoke": {"tool_name": "mysql_export_node_to_migration", "inputs_map": {"node_id": "mysql_find_one_by_147_result_id", "migration_file": "export_node_migration_file_empty"}, "outputs_map": {}}, "transitions_after": [], "transitions_before": []}'),
(149, 8, 4, 'Отчет экспорта ноды', 6, '{"prompt_user": "%if mysql_export_node_to_migration_148_result_blocked%%mysql_export_node_to_migration_148_result_report_str%%else%✅ Экспорт ноды «%mysql_find_one_by_147_result_name%» завершен.\\n\\nФайл: %mysql_export_node_to_migration_148_result_migration_file%\\nТаблиц: %mysql_export_node_to_migration_148_result_tables_qty%, строк: %mysql_export_node_to_migration_148_result_rows_qty%.\\nОбновлены: %mysql_export_node_to_migration_148_result_report_str%%endif%", "continue_workflow": false, "transitions_after": [], "transitions_before": []}'),
(152, 8, 3, 'mysql_migration_prod_create', 8, '{"transitions_before":[],"transitions_after":[],"tool_invoke":{"tool_name":"mysql_migration_prod_create","inputs_map":{},"outputs_map":{}}}'),
(153, 8, 4, 'Отчет по миграции на прод', 9, '{"transitions_before": [], "transitions_after": [], "prompt_user": "✅ Миграция для прода создана: %mysql_migration_prod_create_152_result_migration_file%\\n\\nТаблиц с данными: %mysql_migration_prod_create_152_result_tables_qty%, строк: %mysql_migration_prod_create_152_result_rows_qty%.\\n\\nИзменения структуры: %mysql_migration_prod_create_152_result_schema_changes%\\n\\n%if mysql_migration_prod_create_152_result_review_needed%⚠️ Требует ручного review:\\n%mysql_migration_prod_create_152_result_review_needed%%endif%", "continue_workflow": false}'),
(154, 9, 3, 'Проверка окружения (прод-заглушка)', -2, '{"tool_invoke": {"tool_name": "env_is_prod", "inputs_map": {}, "outputs_map": {}}, "transitions_after": [{"value": "1", "step_id": "155", "operator": "==", "variable": "env_is_prod_154_result_is_prod"}, {"value": "0", "step_id": "73", "operator": "==", "variable": "env_is_prod_154_result_is_prod"}], "transitions_before": []}'),
(155, 9, 4, 'Заглушка: только локально', -1, '{"transitions_before": [], "transitions_after": [], "prompt_user": "🚫 Тестовые прогоны workflow доступны только локально, на проде отключены.", "continue_workflow": false}');

--

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
(1, 'agent_greeting', 'global', NULL, NULL),
(2, 'agent_id', 'global', NULL, NULL),
(3, 'agent_title', 'global', NULL, NULL),
(4, 'agent_name', 'global', NULL, NULL),
(5, 'node_id', 'global', NULL, NULL),
(6, 'prompt_user', 'global', NULL, NULL),
(7, 'session_uuid', 'global', NULL, NULL),
(8, 'user_id', 'global', NULL, NULL),
(9, 'user_username', 'global', NULL, NULL),
(10, 'user_email', 'global', NULL, NULL),
(11, 'workflow_id', 'global', NULL, NULL),
(71, 'companion_id', 'global', NULL, NULL),
(72, 'companion_title', 'global', NULL, NULL),
(73, 'companion_name', 'global', NULL, NULL),
(120, 'user_language', 'global', NULL, 'Активный язык диалога: workflow_variable агента → выбор пользователя в кабинете → первый язык ноды (настройка languages)'),
(121, 'node_languages', 'global', NULL, 'Языки ноды агента через запятую (настройка languages, нодовая перекрывает общую)'),
(15, 'tags', 'workflow', NULL, NULL),
(16, 'facts', 'workflow', NULL, NULL),
(17, 'tags', 'workflow', NULL, NULL),
(18, 'session_messages_limit', 'workflow', '10', NULL),
(19, 'session_messages', 'workflow', NULL, NULL),
(21, 'session_messages_rendered', 'workflow', NULL, NULL),
(92, 'test_workflow_id', 'workflow', '5', 'ID целевого workflow для тестового прогона'),
(93, 'test_iterations_limit', 'workflow', '20', 'Сколько циклов диалога прогнать'),
(94, 'test_iteration', 'workflow', '0', 'Счетчик выполненных циклов'),
(95, 'test_dialog', 'workflow', '', 'Накопленная стенограмма диалога тестового прогона'),
(96, 'test_message', 'workflow', NULL, 'Очередное сообщение LLM-собеседника'),
(97, 'target_agent_name', 'workflow', 'anna', 'Системное имя целевого агента (передается в тестируемый workflow)'),
(98, 'target_agent_title', 'workflow', 'Анна', 'Отображаемое имя целевого агента'),
(99, 'target_agent_id', 'workflow', '20', 'ID целевого агента: им подписываются ответы в сессии диалога'),
(100, 'girl_id', 'workflow', 'anna', 'girl_id целевого агента (для workflow с фактами)'),
(101, 'chat_timeout', 'workflow', '1800', 'Таймаут ожидания ответа в чате, сек (долгий тестовый прогон)'),
(102, 'find_table', 'workflow', '', 'Таблица для mysql_find_by/mysql_find_one_by (задается шагами)'),
(103, 'find_criteria', 'workflow', '{}', 'JSON-критерии для mysql_find_by/mysql_find_one_by (задается шагами)'),
(104, 'chips_template', 'workflow', '[[%s]]', 'Шаблон элемента list_render: чипс чата'),
(105, 'chips_separator', 'workflow', ' ', 'Разделитель элементов list_render'),
(106, 'chips_column', 'workflow', 'name', 'Колонка для dict_column при построении чипсов'),
(107, 'doc_key', 'workflow', 'girl_id', 'Ключ для извлечения girl_id из workflow_variable агента'),
(108, 'target_prompt_system', 'workflow', '', 'Системный промпт целевого агента: персона для ответов тестируемого workflow'),
(118, 'language_from', 'input', 'ru', 'Исходный язык перевода (workflow translator)'),
(119, 'language_to', 'input', 'en', 'Целевой язык перевода (workflow translator)'),
(122, 'fact_id', 'input', NULL, 'ID проверяемого факта (workflow fact_verify)'),
(123, 'verify_query', 'workflow', '0', 'Поисковый запрос фактчека; 0 - проверять нечего'),
(124, 'verify_status', 'workflow', 'ok', 'Вердикт фактчека: ok | corrected | unverifiable'),
(125, 'document_corrected', 'workflow', '', 'Исправленный текст факта (только при verify_status=corrected)'),
(126, 'verify_search_limit', 'workflow', '5', 'Количество результатов веб-поиска для фактчека'),
(183, 'export_node_regex', 'workflow', 'Экспорт ноды\\s+(\\S+)', 'Регулярка команды экспорта ноды: группа 1 - имя ноды'),
(184, 'export_node_migration_file_empty', 'workflow', '', 'Пустое значение - mysql_export_node_to_migration сам возьмет migration_file из node');

--

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(15, 1),
(16, 1),
(17, 4),
(18, 4),
(19, 4),
(21, 4),
(92, 9),
(93, 9),
(94, 9),
(95, 9),
(96, 9),
(97, 9),
(98, 9),
(99, 9),
(100, 9),
(101, 9),
(102, 9),
(103, 9),
(104, 9),
(105, 9),
(106, 9),
(107, 9),
(108, 9),
(118, 10),
(119, 10),
(122, 11),
(123, 11),
(124, 11),
(125, 11),
(126, 11),
(183, 8),
(184, 8);

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(2, NULL, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, NULL, 'Ти асистент ресторану суші Soko. \n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \n  та інших страв японської кухні.\n  \n  База даних доступна через інструмент [qdrant_memory_search_text],', '', 0, 0),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', NULL, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \n  independent "Facts". \n\n  For each fact, follow this strict schema:\n  \n  1. Title: A short descriptive title starting with \'## \'\n  2. Metadata block:\n     - group_id: Unique slug (snake_case) representing the topic.\n     - category: High-level classification (e.g., contacts, pricing, delivery).\n     - language: ISO 639-1 code (ru/en/ua).\n     - tags: A comma-separated list inside brackets [tag1, tag2].\n  3. Separator: Exactly three dashes \'---\'.\n  4. Content: The clean, factual text extracted from the source.', '', 0, 0),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', NULL, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \n  independent "Facts". \n\n  For each fact, follow this strict schema:\n  \n  1. Title: A short descriptive title starting with \'## \'\n  2. Metadata block:\n     - group_id: Unique slug (snake_case) representing the topic.\n     - category: High-level classification (e.g., contacts, pricing, delivery).\n     - language: ISO 639-1 code (ru/en/ua).\n     - tags: A comma-separated list inside brackets [tag1, tag2].\n  3. Separator: Exactly three dashes \'---\'.\n  4. Content: The clean, factual text extracted from the source.', '', 0, 0),
(5, NULL, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', '', 0, 0),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', '', 0, 0),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, NULL, 'Your are agent which returns weather information for customer request. \n  \n  CORE RULES:\n  1. NEVER invent or hallucinate data when customer ask you something\n  2. Do not use your general training data to answer questions that should be in the database.\n  3. Use only Russian in response.\n  \n  For retrieve weather information use tool \'weather_get\' with parameters \'city\' and \'days_offset\' (number of \n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', '', 0, 0),
(8, NULL, 'Test agent', 'Test agent', 'Agent which thinking and find out answers', 4, NULL, 'You are agent which analyze input text and prepare response', 'Привет, я тестовый бот.', 0, 0),
(24, 6, 'mysql_export', 'Mysql export', 'Служебный агент для dev-операций', 8, '{}', 'Ты служебный dev-агент. Выполняешь технические операции по командам.', 'Привет! Я Dev bot.\n\nДоступные команды:\n\n[[Экспорт ноды Dashboard]]\n\n[[Экспорт ноды Dating]]\n\n[[Экспорт ноды Detective]]\n\n[[Создать миграцию на прод]] - сравнивает структуру и данные прода с локальными (как migration diff в ORM) и создает готовую миграцию: структура - только то, чего не хватает на проде; данные - построчный diff по первичному ключу, только новые/измененные локально строки (upsert) и строки, существующие только на проде.', 0, 0),
(25, 6, 'workflow_tester', 'Workflow tester', 'Тестовый прогон workflow: LLM-собеседник ведет диалог с целевым workflow в цикле', 9, '{}', 'Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON.', 'Привет! Я Workflow tester, использую workflow оболочку для тестирования любого workflow.\n\nНапишите любое сообщение, чтобы начать: я спрошу ноду, workflow и агента (выбор чипсами), затем сценарий тестирования (кто собеседник, о чем говорит, чего добивается) — и прогоню диалог с целевым workflow, вернув стенограмму.\n\nКоличество итераций — переменная test_iterations_limit.\n\n[[/start]]', 0, 0),
(27, NULL, 'translator', 'Переводчик', 'Служебный агент автоперевода', 10, NULL, 'Ты профессиональный переводчик. Переводишь текст точно, сохраняя смысл, стиль и тон. Возвращаешь только перевод без пояснений.', '', 0, 0),
(29, NULL, 'fact_verifier', 'Фактчекер', 'Служебный агент проверки фактов веб-поиском (крон fact_verify)', 11, NULL, 'Ты дотошный фактчекер. Проверяешь утверждения по результатам веб-поиска и исправляешь противоречия минимальной правкой.', '', 0, 0);