-- Таблица пользователей
INSERT INTO `user` (`id`, `username`, `email`, `created_at`) VALUES
(1, 'user1', 'user1@example.com', '2026-04-26 09:17:35'),
(2, 'user2', 'user2@example.com', '2026-04-26 09:17:35');

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

INSERT INTO `setting` (`id`, `key`, `user_id`, `value`) VALUES
(4, 'llm_active', 1, 'groq:openai/gpt-oss-120b');

INSERT INTO `node` (`id`, `name`, `position`) VALUES
(1, 'Cashier', 0),
(2, 'Dating', 0),
(3, 'Soko', 0),
(4, 'Chat', -1);

INSERT INTO `agent_specialization` (`id`, `name`) VALUES
(1, 'fact_compressor'),
(2, 'fact_extractor');

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `specialization_id`, `fact_collection`, `system_prompt`, `tool`, `mcp_server`, `memory_short_disabled`, `llm_id`, `position`) VALUES
(1, 4, 'my_assistant', 'My assistant', 'Agent which research needed response for customer request.', NULL, NULL, 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', 'agent_desc_list,agent_invoke', NULL, 0, NULL, -1),
(2, 3, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, 'Ти асистент ресторану суші Soko. \r\n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \r\n  та інших страв японської кухні.\r\n  \r\n  База даних доступна через інструмент [qdrant_memory_search_text],', '', NULL, NULL, 1, NULL, 0),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', 1, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.\r\n  \r\n  OUTPUT FORMAT EXAMPLE:\r\n  \r\n  ## [Descriptive Title]\r\n  group_id: [unique_id]\r\n  category: [category_name]\r\n  language: [code]\r\n  tags: [tag1, tag2, tag3]\r\n  ---\r\n  [Cleaned factual content]\r\n  \r\n  ## [Descriptive Title 2]\r\n  group_id: [unique_id]\r\n  category: [category_name]\r\n  language: [code]\r\n  tags: [tag1, tag2, tag3]\r\n  ---\r\n  [Cleaned factual content 2]', NULL, NULL, 1, NULL, 0),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', 2, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.\r\n  \r\n  OUTPUT FORMAT EXAMPLE:\r\n  \r\n  ## [Descriptive Title]\r\n  group_id: [unique_id]\r\n  category: [category_name]\r\n  language: [code]\r\n  tags: [tag1, tag2, tag3]\r\n  ---\r\n  [Cleaned factual content]\r\n  \r\n  ## [Descriptive Title 2]\r\n  group_id: [unique_id]\r\n  category: [category_name]\r\n  language: [code]\r\n  tags: [tag1, tag2, tag3]\r\n  ---\r\n  [Cleaned factual content 2]', NULL, NULL, 1, NULL, 0),
(5, 1, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', NULL, 'jira', 0, NULL, 0),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', 'github_search_repo_by_last_commit,github_search_branch_with_last_commit,github_check_and_merge_url_get', NULL, 0, NULL, 0),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, NULL, 'Your are agent which returns weather information for customer request. \r\n  \r\n  CORE RULES:\r\n  1. NEVER invent or hallucinate data when customer ask you something\r\n  2. Do not use your general training data to answer questions that should be in the database.\r\n  3. Use only Russian in response.\r\n  \r\n  For retrieve weather information use tool \'weather_get\' with parameters \'city\' and \'days_offset\' (number of \r\n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', 'weather_get', NULL, 1, NULL, 0),
(8, NULL, 'thinker', 'Thinker', 'Agent which thinking and find out answers', NULL, NULL, 'You are agent which analyze input text and prepare response.\r\n  \r\n  Use tools \'qdrant_memory_search_text\' for search information in memory.\r\n  \r\n  CORE RULES:\r\n  1. ALWAYS call \'agent_list\' for retrieve information about available agents before start research.\r\n  You can use \'agent_invoke\' to get information in area of request.\r\n  With list of available agents and their description you know exactly which information they can provide.\r\n  Use tools \'agent_list\' and \'agent_invoke\' for getting required information.\r\n  2. ALWAYS call \'search_memories\' before answering any factual question.\r\n  3. Do not use your general training data to answer questions that should be in the database. \r\n  Better return answer that you do not have this information in your memory than invent it.\r\n  4. Use only Russian or English in response.\r\n  5. NEVER invent or hallucinate data when customer ask you something', 'agent_list,agent_invoke', NULL, 0, NULL, 0);

INSERT INTO `agent_session` (`id`, `session_uuid`, `llm_id`, `agent_id`, `user_id`, `role`, `kind_type`, `content`, `token`, `created_at`) VALUES
(1, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'system', 'system-prompt', 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', NULL, '2026-05-01 19:08:33'),
(2, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'user', 'user-prompt', 'Ну давай попробуем.', NULL, '2026-05-01 19:08:33'),
(3, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'assistant', 'thinking', 'The user says \"Ну давай попробуем.\" Likely they want to start some request. We need to ask for clarification? According to core rule 1: before doing actions, notify customer detailed plan of actions. So we need to ask what they want? Probably need to respond asking for request details. Use Russian.', 806, '2026-05-01 19:08:33'),
(4, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'assistant', 'response-final', 'Добрый день! Чтобы я мог помочь вам максимально эффективно, расскажите, пожалуйста, что именно вы хотите попробовать:  \n\n1. **Поиск информации** — нужны данные из нашей внутренней базы, документы, статистика и т.п.  \n2. **Исследование в интернете** — требуется собрать сведения с внешних сайтов.  \n3. **Выполнение расчётов или генерация кода** — нужны технические решения, скрипты, формулы.  \n4. **Что‑то другое** — уточните задачу, и я подскажу, какие шаги будем предпринимать.\n\nКак только получу от вас уточнение, я подготовлю подробный план действий и приступлю к их выполнению.', 806, '2026-05-01 19:08:33');

INSERT INTO `fact_collection` (`id`, `name`, `language`, `user_prompt_header`) VALUES
(1, 'cashier_service', 'ru', 'Микросервисы'),
(2, 'dating_girl_bio', 'ru,en', 'Биография и личная информация '),
(3, 'soko_menu', 'ru,en,ua', 'Меню');
