INSERT INTO `user` (`id`, `username`, `email`, `created_at`) VALUES
(1, 'user1', 'user1@example.com', '2026-04-26 09:17:35'),
(2, 'user2', 'user2@example.com', '2026-04-26 09:17:35');

--

INSERT INTO `llm` (`id`, `name`) VALUES
(1, 'claude-sonnet-4-5-20250929'),
(2, 'gpt-5-nano'),
(3, 'gpt-4.1'),
(4, 'o4-mini'),
(5, 'gemini-3.1-pro-preview'),
(6, 'gemini-2.5-flash'),
(7, 'grok-4-1-fast-reasoning'),
(8, 'grok-4-1-fast-non-reasoning'),
(9, 'grok-4-fast-reasoning'),
(10, 'grok-4'),
(11, 'grok-3'),
(12, 'groq:openai/gpt-oss-120b'),
(13, 'groq:llama-3.3-70b-versatile'),
(14, 'groq:qwen/qwen3-32b'),
(15, 'groq:llama-3.1-8b-instant'),
(16, 'openai/gpt-oss-120b'),
(17, 'ollama/llama3.1:latest'),
(18, 'ollama/deepseek-r1:8b'),
(19, 'ollama/qwen2.5:7b'),
(20, 'ollama/qwen2.5:14b'),
(21, 'ollama/qwen2.5-coder:7b'),
(22, 'ollama/gpt-oss:20b'),
(23, 'ollama/qwen3:30b'),
(24, 'ollama/qwen3-coder:30b'),
(25, 'ollama/mistral');

--

INSERT INTO `setting` (`id`, `key`, `user_id`, `value`) VALUES
(4, 'llm_active', 1, 'groq:openai/gpt-oss-120b');

--

INSERT INTO `node` (`id`, `name`, `position`) VALUES
(1, 'Cashier', 0),
(2, 'Dating', -3),
(3, 'Soko', 0),
(4, 'Chat', -1),
(5, 'Test', -2);

--

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`) VALUES
(1, 1, 'response_cashier', 'Чат кашира', 'Ответить пользователю', 0),
(2, 2, 'dating_girl_generator', 'Генератор девушки', 'Генерируем коллекции девушки', 0),
(3, 3, 'response_soko', 'Чат суши-бара', 'Ответить пользователю', 0),
(4, 5, 'test', 'Test', 'Simple test workflow', -1);

INSERT INTO `agent_workflow_step_type` (`id`, `name`, `icon`, `description`, `description_full`, `metadata`) VALUES
(1, 'return_response_llm', '↩', 'Вернуть LLM ответ', 'Собираем полный запрос на LLM с учетом короткой и длинной памяти, всей связанной информации в БД и отдаем LLM для формирования наиболее качественного ответа.', ''),
(2, 'llm_to_json', '🧠', 'LLM -> JSON', 'Ожидает ответ от LLM в виде JSON. Далее каждый ключ JSON доступен в последующих шагах', ''),
(3, 'tool_invoke', '⚙️', 'Вызов инструмента', 'Вызываем инструмент. Передаем в аргументы текущие переменные и сохраняем ответ в переменные.', ''),
(4, 'return_response_text', '↩T', 'Вернуть текстовый ответ', 'Возращаем текстовый ответ на основе шаблона из переменных', '');

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(1, 1, 1, 'мой ответ', 2, '{"prompt_user":"%prompt_user%","transitions_after":[]}'),
(2, 1, 3, 'мой инструмент', 1,'{"prompt_user":"ok","transitions_after":[],"tool_invoke":{"tool_name":"github_user_info","inputs_map":{"random":"facts"},"outputs_map":{"login":"tags","name":"prompt_user","email":"facts"}}}'),
(4, 3, 1, 'мой ответ', 0, ''),
(5, 3, 3, 'мой поиск', 0, ''),
(7, 1, 2, 'запрос LLM', 0, '{"llm_to_json_variable":[{"variable":"tags","text":"распарсить текст на таги"}],"prompt_user":"%prompt_user%\n\n=== Important information about final response ===\nPlease return your response in JSON format. The JSON response must contain follow keys: \n- \\"tags\\": распарсить текст на таги\n\nExample of JSON response:\n{\n  \\"tags\\": \\"распарсить текст на таги\\"\n}","transitions_after":[{"variable":"facts","operator":"==","value":"ok","step_id":"1"}]}'),
(8, 4, 1, 'Вернуть ответ', 3, '{"prompt_user":"%session_messages_rendered%\n\n[Пользователь пишет]:\n\n%prompt_user%","transitions_after":[]}'),
(9, 4, 2, 'LLM ответ JSON', 0, '{"llm_to_json_variable":[{"variable":"tags","text":"распарсить текст на таги"}],"transitions_before":[{"variable":"prompt_user","operator":"==","value":"be","step_id":"12"}],"transitions_after":[{"variable":"prompt_user","operator":"==","value":"go","step_id":"12"}],"prompt_user":"%prompt_user%\n\n=== Important information about final response ===\nPlease return your response in JSON format. The JSON response must contain follow keys: \n- \\"tags\\": распарсить текст на таги\n\nExample of JSON response:\n{\n  \\"tags\\": \\"распарсить текст на таги\\"\n}"}'),
(10, 4, 3, 'session_messages', 1, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit"},"outputs_map":{"list":"session_messages"}},"transitions_after":[]}'),
(11, 4, 3, 'session_messages_render', 2, '{"tool_invoke":{"tool_name":"session_messages_render","inputs_map":{"messages":"session_messages"},"outputs_map":{"str":"session_messages_rendered"}},"transitions_after":[]}'),
(12, 4, 4, 'return_response_text', 4, '{"prompt_user":"Команда /go найдена","transitions_after":[]}'),
(13, 2, 3, 'dating_girl_create', 2, '{"tool_invoke":{"tool_name":"dating_girl_create","inputs_map":{"name":"prompt_user"},"outputs_map":{"str":"dating_girl_create_response"}},"transitions_before":[],"transitions_after":[]}'),
(14, 2, 4, 'Вернуть список команд', 0, '{"transitions_before":[{"variable":"prompt_user","operator":"==","value":"/girl_create","step_id":"16"}],"transitions_after":[],"prompt_user":"%agent_greeting%"}'),
(15, 2, 4, 'dating_girl_create_response', 7, '{"prompt_user":"%dating_girl_create_response%\n\nБыло создано %facts_qty% фактов.","transitions_before":[],"transitions_after":[]}'),
(16, 2, 4, 'Спросить имя девушки', 1, '{"prompt_user":"Напишите желаемое имя девушки:","transitions_before":[],"transitions_after":[]}'),
(17, 2, 3, 'dating_girl_id', 3, '{"tool_invoke":{"tool_name":"dating_girl_id","inputs_map":{"name":"prompt_user"},"outputs_map":{"int":"girl_id"}},"transitions_before":[],"transitions_after":[]}'),
(18, 2, 3, 'fact_collection_output_format', 4, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_bio_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(19, 2, 2, 'LLM -> JSON', 5, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"facts","text":"список фактов"}],"prompt_user":"Нужно придумать биографию девушки. Известны такие факты о ней:\n1. ID: %girl_id%\n2. имя: %prompt_user%\n\nНужно придумать биографию. Основные исходные данные: \n1. она родом из города в Украине\n2. возраст от 20 до 35\n3. имеет образование\n4. не имеет детей\n\nОстальные детали придумай. Все факты и детали не должны противоречить друг другу. Нужно придумать, как минимум, 5 фактов в биографии по каждому пункту:\n- детство\n- подростковый возраст\n- учеба\n- отношения с родителями\n- любимые занятия и увлечения\n- любовные отношения\n\n=== Important information about final response ===\nPlease return your response in JSON format. The JSON response must contain follow keys: \n- \\"facts\\": список фактов\n\nВсе факты должны быть в таком формате:\n%fact_collection_output_format_response%\n\nExample of JSON response:\n{\n  \\"facts\\": \\"список фактов\\"\n}"}'),
(20, 2, 3, 'fact_collection_add', 6, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_bio_name","data":"facts"},"outputs_map":{"int":"facts_qty"}},"transitions_before":[],"transitions_after":[]}');

INSERT INTO `agent_workflow_variable` (`id`, `workflow_id`, `name`, `default`) VALUES
(1, 1, 'tags', NULL),
(2, 1, 'facts', NULL),
(3, 4, 'tags', NULL),
(4, 4, 'session_messages_limit', 10),
(5, 4, 'session_messages', NULL),
(6, 4, 'session_messages_rendered', NULL),
(7, 2, 'girl_id', NULL),
(8, 2, 'dating_girl_create_response', NULL),
(9, 2, 'fact_collection_girl_bio_name', 'dating_girl_bio'),
(10, 2, 'fact_collection_output_format_response', NULL),
(11, 2, 'facts', NULL),
(12, 2, 'facts_qty', NULL);

--

INSERT INTO `fact_collection` (`id`, `name`, `position`, `language`, `description`) VALUES
(1, 'cashier_service', 0, 'ru', 'Микросервисы'),
(2, 'dating_girl_bio', 0, 'ru,en', 'Биография девушки и личная информация '),
(3, 'soko_menu', 0, 'ru,en,ua', 'Меню');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `fact_collection`, `prompt_system`, `greeting`, `tool`, `mcp_server`, `llm_id`, `position`) VALUES
(1, 4, 'my_assistant', 'My assistant', 'Agent which research needed response for customer request.', NULL, NULL, 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', '', 'agent_desc_list,agent_invoke', NULL, NULL, -1),
(2, 3, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, 'Ти асистент ресторану суші Soko. \r\n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \r\n  та інших страв японської кухні.\r\n  \r\n  База даних доступна через інструмент [qdrant_memory_search_text],', '', '', NULL, NULL, NULL, 0),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', NULL, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.', '', NULL, NULL, NULL, 0),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', NULL, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.', '', NULL, NULL, NULL, 0),
(5, 1, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', '', NULL, 'jira', NULL, 0),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', '', 'github_search_repo_by_last_commit,github_search_branch_with_last_commit,github_check_and_merge_url_get', NULL, NULL, 0),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, NULL, 'Your are agent which returns weather information for customer request. \r\n  \r\n  CORE RULES:\r\n  1. NEVER invent or hallucinate data when customer ask you something\r\n  2. Do not use your general training data to answer questions that should be in the database.\r\n  3. Use only Russian in response.\r\n  \r\n  For retrieve weather information use tool \'weather_get\' with parameters \'city\' and \'days_offset\' (number of \r\n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', '', 'weather_get', NULL, NULL, 0),
(8, 5, 'Test agent', 'Test agent', 'Agent which thinking and find out answers', 4, NULL, 'You are agent which analyze input text and prepare response', 'Привет, я тестовый бот.', 'agent_list,agent_invoke', NULL, NULL, 0),
(9, 2, 'Bot', 'Dating bot', '', 2, NULL, 'You are agent which analyze input text and prepare response', 'Привет, я dating bot, доступны команды :\n\n/girl_create - создает девушку', NULL, NULL, NULL, 0);

INSERT INTO `agent_session` (`id`, `session_uuid`, `llm_id`, `agent_id`, `user_id`, `role`, `kind_type`, `content`, `token`, `created_at`) VALUES
(1, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'system', 'system-prompt', 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', NULL, '2026-05-01 19:08:33'),
(2, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'user', 'user-prompt', 'Ну давай попробуем.', NULL, '2026-05-01 19:08:33'),
(3, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'assistant', 'thinking', 'The user says \"Ну давай попробуем.\" Likely they want to start some request. We need to ask for clarification? According to core rule 1: before doing actions, notify customer detailed plan of actions. So we need to ask what they want? Probably need to respond asking for request details. Use Russian.', 806, '2026-05-01 19:08:33'),
(4, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'assistant', 'response-final', 'Добрый день! Чтобы я мог помочь вам максимально эффективно, расскажите, пожалуйста, что именно вы хотите попробовать:  \n\n1. **Поиск информации** — нужны данные из нашей внутренней базы, документы, статистика и т.п.  \n2. **Исследование в интернете** — требуется собрать сведения с внешних сайтов.  \n3. **Выполнение расчётов или генерация кода** — нужны технические решения, скрипты, формулы.  \n4. **Что‑то другое** — уточните задачу, и я подскажу, какие шаги будем предпринимать.\n\nКак только получу от вас уточнение, я подготовлю подробный план действий и приступлю к их выполнению.', 806, '2026-05-01 19:08:33');