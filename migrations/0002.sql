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
(2, 'Dating', 0),
(3, 'Soko', 0),
(4, 'Chat', -1);

--

INSERT INTO `agent_specialization` (`id`, `name`) VALUES
(1, 'fact_compressor'),
(2, 'fact_extractor');

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `specialization_id`, `fact_collection`, `system_prompt`, `tool`, `mcp_server`, `memory_short_disabled`, `llm_id`, `position`) VALUES
(1, 4, 'my_assistant', 'My assistant', 'Agent which research needed response for customer request.', NULL, NULL, 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', 'agent_desc_list,agent_invoke', NULL, 0, NULL, -1),
(2, 3, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, 'Ти асистент ресторану суші Soko. \r\n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \r\n  та інших страв японської кухні.\r\n  \r\n  База даних доступна через інструмент [qdrant_memory_search_text],', '', NULL, NULL, 1, NULL, 0),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', 1, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.', NULL, NULL, 1, NULL, 0),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', 2, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.', NULL, NULL, 1, NULL, 0),
(5, 1, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', NULL, 'jira', 0, NULL, 0),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', 'github_search_repo_by_last_commit,github_search_branch_with_last_commit,github_check_and_merge_url_get', NULL, 0, NULL, 0),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, NULL, 'Your are agent which returns weather information for customer request. \r\n  \r\n  CORE RULES:\r\n  1. NEVER invent or hallucinate data when customer ask you something\r\n  2. Do not use your general training data to answer questions that should be in the database.\r\n  3. Use only Russian in response.\r\n  \r\n  For retrieve weather information use tool \'weather_get\' with parameters \'city\' and \'days_offset\' (number of \r\n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', 'weather_get', NULL, 1, NULL, 0),
(8, NULL, 'thinker', 'Thinker', 'Agent which thinking and find out answers', NULL, NULL, 'You are agent which analyze input text and prepare response.\r\n  \r\n  Use tools \'qdrant_memory_search_text\' for search information in memory.\r\n  \r\n  CORE RULES:\r\n  1. ALWAYS call \'agent_list\' for retrieve information about available agents before start research.\r\n  You can use \'agent_invoke\' to get information in area of request.\r\n  With list of available agents and their description you know exactly which information they can provide.\r\n  Use tools \'agent_list\' and \'agent_invoke\' for getting required information.\r\n  2. ALWAYS call \'search_memories\' before answering any factual question.\r\n  3. Do not use your general training data to answer questions that should be in the database. \r\n  Better return answer that you do not have this information in your memory than invent it.\r\n  4. Use only Russian or English in response.\r\n  5. NEVER invent or hallucinate data when customer ask you something', 'agent_list,agent_invoke', NULL, 0, NULL, 0);

INSERT INTO `agent_session` (`id`, `session_uuid`, `llm_id`, `agent_id`, `user_id`, `role`, `kind_type`, `content`, `token`, `created_at`) VALUES
(1, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'system', 'system-prompt', 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', NULL, '2026-05-01 19:08:33'),
(2, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'user', 'user-prompt', 'Ну давай попробуем.', NULL, '2026-05-01 19:08:33'),
(3, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'assistant', 'thinking', 'The user says \"Ну давай попробуем.\" Likely they want to start some request. We need to ask for clarification? According to core rule 1: before doing actions, notify customer detailed plan of actions. So we need to ask what they want? Probably need to respond asking for request details. Use Russian.', 806, '2026-05-01 19:08:33'),
(4, '097824c7-c3d3-4925-a63f-bd685292a408', 14, 1, 1, 'assistant', 'response-final', 'Добрый день! Чтобы я мог помочь вам максимально эффективно, расскажите, пожалуйста, что именно вы хотите попробовать:  \n\n1. **Поиск информации** — нужны данные из нашей внутренней базы, документы, статистика и т.п.  \n2. **Исследование в интернете** — требуется собрать сведения с внешних сайтов.  \n3. **Выполнение расчётов или генерация кода** — нужны технические решения, скрипты, формулы.  \n4. **Что‑то другое** — уточните задачу, и я подскажу, какие шаги будем предпринимать.\n\nКак только получу от вас уточнение, я подготовлю подробный план действий и приступлю к их выполнению.', 806, '2026-05-01 19:08:33');

--

INSERT INTO `workflow` (`id`, `node_id`, `tid`, `title`, `description`) VALUES
(1, 1, 'response_cashier', 'Чат кашира', 'Ответить пользователю'),
(2, 2, 'response_dating', 'Чат сайта знакомств', 'Ответить пользователю'),
(3, 3, 'response_soko', 'Чат суши-бара', 'Ответить пользователю');

INSERT INTO `workflow_step_type` (`id`, `name`, `icon`, `description`, `description_full`, `metadata`) VALUES
(1, 'response_return', '↩', 'Вернуть ответ', 'Собираем полный запрос на LLM с учетом короткой и длинной памяти, всей связанной информации в БД и отдаем LLM для формирования наиболее качественного ответа.', ''),
(2, 'llm_to_json', '🧠', 'LLM ответ JSON', 'Ожидает ответ от LLM в виде JSON. Далее каждый ключ JSON доступен в последующих шагах', ''),
(3, 'llm_to_string', '🧠', 'LLM ответ string', 'Ожидает ответ от LLM в виде текстовой строки', ''),
(4, 'tool_invoke', '🛠', 'Вызов инструмента', 'Вызываем инструмент. Передаем в аргументы текущие переменные и сохраняем ответ в переменные.', '');

INSERT INTO `workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(1, 1, 1, 'мой ответ', 2, '{"response_return":"%user-prompt%","transitions":[]}'),
(2, 1, 4, 'мой инструмент', 1,'{"textarea":"ok","transitions":[],"tool_invoke":{"tool_name":"github_user_info","inputs_map":{"random":"facts"},"outputs_map":{"login":"tags","name":"user-prompt","email":"facts"}}}'),
(3, 2, 1, 'мой ответ', 0, ''),
(4, 3, 1, 'мой ответ', 0, ''),
(5, 3, 4, 'мой поиск', 0, ''),
(7, 1, 2, 'запрос LLM', 0, '{"llm_to_json_variable":[{"variable":"tags","text":"распарсить текст на таги"}],"llm_to_json_prompt":"%user-prompt%\n\n=== Important information about final response ===\nPlease return your response in JSON format. The JSON response must contain follow keys: \n- \\"tags\\": распарсить текст на таги\n\nExample of JSON response:\n{\n  \\"tags\\": \\"распарсить текст на таги\\"\n}","transitions":[{"variable":"facts","operator":"==","value":"ok","step_id":"1"}]}');

INSERT INTO `workflow_variable` (`id`, `workflow_id`, `name`) VALUES
(1, 1, 'tags'),
(2, 1, 'facts');

--

INSERT INTO `fact_collection` (`id`, `name`, `position`, `language`, `user_prompt_header`) VALUES
(1, 'cashier_service', 0, 'ru', 'Микросервисы'),
(2, 'dating_girl_bio', 0, 'ru,en', 'Биография и личная информация '),
(3, 'soko_menu', 0, 'ru,en,ua', 'Меню');

INSERT INTO `fact` (`id`, `collection_id`, `category`, `language`, `content`, `tags`, `qdrant_synced`, `created_at`) VALUES
(8, 3, 'data format', 'ru', 'База данных возвращает данные в формате списка словарей (Dict), а не кортежей.', 'database, list, dict, tuples, mysql', 1, '2026-05-02 16:53:43'),
(9, 3, 'configuration', 'ru', 'Это происходит потому, что mysql_get_db_async настроен на использование DictCursor.', 'mysql_get_db_async, DictCursor, configuration', 1, '2026-05-02 16:53:43'),
(10, 3, 'code', 'ru', 'В коде происходит обращение к данным по индексам: field_name = col[0] и raw_comment = col[8].', 'code, indexing, col, field_name, raw_comment', 1, '2026-05-02 16:53:43'),
(11, 3, 'error', 'ru', 'Поскольку col — это словарь, Python либо выдает ошибку, либо (в некоторых версиях драйверов) возвращает None/ошибку ключа.', 'Python, error, dict, key error, None', 1, '2026-05-02 16:53:43'),
(12, 2, 'personal_info', 'ru', 'Анна, 25 лет', 'Анна, возраст, 25', 1, '2026-05-02 18:10:13'),
(13, 2, 'location', 'ru', 'Город: Харьков', 'Харьков, город', 1, '2026-05-02 18:10:13'),
(14, 2, 'early_years', 'ru', 'Анна родилась и выросла в Харькове — городе студентов и творческой интеллигенции', 'рождение, детство, Харьков', 1, '2026-05-02 18:10:13'),
(15, 2, 'early_years', 'ru', 'С детства её окружала атмосфера «бетонных джунглей» Госпрома и уютных парков', 'детство, атмосфера, Госпром, парки', 1, '2026-05-02 18:10:13'),
(16, 2, 'education', 'ru', 'Окончила одну из местных гимназий', 'гимназия, образование', 1, '2026-05-02 18:10:13'),
(17, 2, 'education', 'ru', 'Поступила в ХНУ им. В. Н. Каразина', 'ХНУ, В. Н. Каразин, университет', 1, '2026-05-02 18:10:13'),
(18, 2, 'education', 'ru', 'За время учебы получила диплом', 'диплом, образование', 1, '2026-05-02 18:10:13'),
(19, 2, 'education', 'ru', 'Стала активным участником молодежных харьковских форумов и волонтерских инициатив', 'форумы, волонтёрство, молодежь', 1, '2026-05-02 18:10:13'),
(20, 2, 'career', 'ru', 'Начала карьеру в одном из харьковских IT‑кластеров на позиции контент‑менеджера', 'IT‑кластер, контент‑менеджер, карьера', 1, '2026-05-02 18:10:13'),
(21, 2, 'career', 'ru', 'Быстро переросла в специалиста по маркетингу', 'маркетинг, продвижение, карьерный рост', 1, '2026-05-02 18:10:13'),
(22, 2, 'career', 'ru', 'Сейчас работает удаленно, сотрудничая с украинскими брендами', 'удалённая работа, украинские бренды, сотрудничество', 1, '2026-05-02 18:10:13'),
(23, 2, 'personality', 'ru', 'Типичная харьковчанка: прямолинейная, энергичная и с прекрасным чувством юмора', 'характер, прямолинейность, энергия, юмор', 1, '2026-05-02 18:10:13'),
(24, 2, 'personality', 'ru', 'Обожает свой город, даже в самые сложные времена', 'любовь к городу, Харьков, патриотизм', 1, '2026-05-02 18:10:13'),
(25, 2, 'habits', 'ru', 'Часто встречается с ноутбуком в кофейнях на Сумской или Пушкинской', 'кофейни, Сумская, Пушкинская, работа', 1, '2026-05-02 18:10:13'),
(26, 2, 'hobbies', 'ru', 'Хобби: фотография (особенно любит снимать харьковский конструктивизм)', 'фотография, конструктивизм, Харьков', 1, '2026-05-02 18:10:13'),
(27, 2, 'hobbies', 'ru', 'Хобби: изучение языков', 'языки, обучение', 1, '2026-05-02 18:10:13'),
(28, 2, 'hobbies', 'ru', 'Хобби: большой теннис', 'теннис, спорт', 1, '2026-05-02 18:10:13'),
(29, 2, 'dream', 'ru', 'Мечта: создать собственный образовательный проект для талантливой молодежи родного города', 'мечта, образование, проект, молодежь', 1, '2026-05-02 18:10:13'),
(30, 2, 'credo', 'ru', 'Жизненное кредо: «Движение — это жизнь, а Харьков — это место силы»', 'кредо, цитата, движение, Харьков', 1, '2026-05-02 18:10:13'),
(31, 2, 'personal_info', 'ru', 'Анна, 25 лет.', 'имя, возраст', 1, '2026-05-02 18:11:54'),
(32, 2, 'location', 'ru', 'Город проживания — Харьков.', 'город, местоположение', 1, '2026-05-02 18:11:54'),
(33, 2, 'early_years', 'ru', 'Анна родилась и выросла в Харькове, городе студентов и творческой интеллигенции, окружённом атмосферой «бетонных джунглей» Госпрома и уютными парками.', 'детство, родина, атмосфера', 1, '2026-05-02 18:11:54'),
(34, 2, 'education', 'ru', 'Окончила одну из местных гимназий.', 'школа, гимназия', 1, '2026-05-02 18:11:54'),
(35, 2, 'higher_education', 'ru', 'Поступила в ХНУ им. В. Н. Каразина и получила диплом.', 'университет, высшее_образование, диплом', 1, '2026-05-02 18:11:54'),
(36, 2, 'extracurricular', 'ru', 'Во время учёбы стала активным участником харьковских молодежных форумов и волонтёрских инициатив.', 'форумы, волонтёрство, молодежь', 1, '2026-05-02 18:11:54'),
(37, 2, 'career_start', 'ru', 'Начала карьеру в одном из харьковских IT‑кластеров на позиции контент‑менеджера.', 'карьера, IT, контент‑менеджер', 1, '2026-05-02 18:11:54'),
(38, 2, 'career_progression', 'ru', 'Быстро переросла в специалиста по маркетингу.', 'маркетинг, продвижение, рост', 1, '2026-05-02 18:11:54'),
(39, 2, 'current_work', 'ru', 'Сейчас работает удалённо, сотрудничая с украинскими брендами и помогая им находить уникальный голос в цифровом пространстве.', 'удалённая_работа, бренды, цифровой_маркетинг', 1, '2026-05-02 18:11:54'),
(40, 2, 'personality', 'ru', 'Типичная харьковчанка: прямолинейная, энергичная и с прекрасным чувством юмора.', 'характер, черты_личности', 1, '2026-05-02 18:11:54'),
(41, 2, 'city_affection', 'ru', 'Обожает свой город даже в самые сложные времена.', 'любовь_к_городу, патриотизм', 1, '2026-05-02 18:11:54'),
(42, 2, 'work_habits', 'ru', 'Часто работает с ноутбуком в кофейнях на Сумской или Пушкинской улицах.', 'кофейни, рабочее_место, привычки', 1, '2026-05-02 18:11:54'),
(43, 2, 'hobbies', 'ru', 'Хобби: фотография (особенно съемка харьковского конструктивизма), изучение языков и большой теннис.', 'фотография, конструктивизм, языки, теннис', 1, '2026-05-02 18:11:54'),
(44, 2, 'dream', 'ru', 'Мечтает создать собственный образовательный проект для талантливой молодежи родного города.', 'мечта, образование, проект', 1, '2026-05-02 18:11:54'),
(45, 2, 'credo', 'ru', 'Жизненное кредо: «Движение — это жизнь, а Харьков — это место силы».', 'кредо, философия, мотивация', 1, '2026-05-02 18:11:54');

INSERT INTO `fact_collection_dating_girl_bio` (`id`, `fact_id`) VALUES
(1, 12),
(2, 13),
(3, 14),
(4, 15),
(5, 16),
(6, 17),
(7, 18),
(8, 19),
(9, 20),
(10, 21),
(11, 22),
(12, 23),
(13, 24),
(14, 25),
(15, 26),
(16, 27),
(17, 28),
(18, 29),
(19, 30),
(20, 31),
(21, 32),
(22, 33),
(23, 34),
(24, 35),
(25, 36),
(26, 37),
(27, 38),
(28, 39),
(29, 40),
(30, 41),
(31, 42),
(32, 43),
(33, 44),
(34, 45);