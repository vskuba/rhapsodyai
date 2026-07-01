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

INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role`, `llm_id`, `created_at`) VALUES
(1, 'user1', 'user1@example.com', '$2b$12$7i4Q9GNhQ.jMRL9R.juWh.txIaVBC0vqv9Deg5aBj4OO/Q.YLICnC', 'admin', 12, '2026-04-26 09:17:35'),
(2, 'user2', 'user2@example.com', '$2b$12$xfglXXXp3W2QCb1XnZhNBuDYAJc.Fy51fI43NlVhBfVQTLaYpD1Ca', 'user', 20, '2026-04-26 09:17:35');

--

INSERT INTO `role` (`id`, `name`) VALUES
(1, 'admin'),
(2, 'user'),
(3, 'moderator');

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
(2, 2, 'dating_bot', 'Dating bot', 'Генерируем коллекции девушки', 0),
(3, 3, 'response_soko', 'Чат суши-бара', 'Ответить пользователю', 0),
(4, 5, 'test', 'Test', 'Simple test workflow', -1),
(5, 2, 'dating_talk', 'Чат с девушкой', 'Чат с девушкой', 0);

INSERT INTO `agent_workflow_step_type` (`id`, `name`, `icon`, `description`, `description_full`, `metadata`) VALUES
(1, 'return_response_llm', '↩L', 'Вернуть LLM ответ', 'Собираем полный запрос на LLM с учетом короткой и длинной памяти, всей связанной информации в БД и отдаем LLM для формирования наиболее качественного ответа.', ''),
(2, 'llm_to_json', '🧠', 'LLM -> JSON', 'Ожидает ответ от LLM в виде JSON. Далее каждый ключ JSON доступен в последующих шагах', ''),
(3, 'tool_invoke', '⚙️', 'Вызов инструмента', 'Вызываем инструмент. Передаем в аргументы текущие переменные и сохраняем ответ в переменные.', ''),
(4, 'return_response_text', '↩T', 'Вернуть текстовый ответ', 'Возращаем текстовый ответ на основе шаблона из переменных', ''),
(5, 'variable_conversion', '❴❵', 'Переменные', 'Переопределяем значения переменных', '');

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
(12, 4, 4, 'return_response_text', 4, '{"prompt_user":"Команда /go найдена","transitions_after":[]}'),
(13, 2, 3, 'dating_girl_create', 4, '{"tool_invoke":{"tool_name":"dating_girl_create","inputs_map":{"name":"agent_name","title":"prompt_user"},"outputs_map":{"str":"dating_girl_create_response"}},"transitions_before":[],"transitions_after":[]}'),
(14, 2, 4, 'Вернуть список команд', 0, '{"transitions_before":[{"variable":"prompt_user","operator":"==","value":"/girl_create","step_id":"16"}],"transitions_after":[],"prompt_user":"%agent_greeting%"}'),
(15, 2, 4, 'dating_girl_create_response', 13, '{"prompt_user":"%dating_girl_create_response%\n\nБыло создано %facts_qty% фактов.","transitions_before":[],"transitions_after":[]}'),
(16, 2, 4, 'Спросить имя девушки', 1, '{"prompt_user":"Напишите желаемое имя девушки:","transitions_before":[],"transitions_after":[],"continue_workflow":true}'),
(18, 2, 3, 'fact_collection_output_format', 5, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(19, 2, 2, 'LLM -> JSON', 6, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"facts","text":"список фактов"}],"prompt_user":"Нужно придумать биографию девушки. Известны такие факты о ней:\\n- имя: %prompt_user%\\n\\nНужно придумать биографию. Основные исходные данные: \\n1. она родом из города в Украине\\n2. возраст от 20 до 35\\n3. имеет образование\\n4. не имеет детей\\n\\nОстальные детали придумай. Все факты и детали не должны противоречить друг другу. Нужно придумать, как минимум, 5 фактов в биографии по каждому пункту:\\n- детство\\n- подростковый возраст\\n- учеба\\n- отношения с родителями\\n- любимые занятия и увлечения\\n- любовные отношения\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"facts\\": список фактов\\n\\ndocument_id всегда \'%agent_name%\'\\n\\nExample of JSON response:\\n{\\n  \\"facts\\": %fact_collection_output_format_response%\\n}"}'),
(20, 2, 3, 'fact_collection_add', 9, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"facts"},"outputs_map":{"facts_qty":"facts_qty"}},"transitions_before":[],"transitions_after":[]}'),
(21, 2, 5, 'Переменные', 10, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_title","text":"%prompt_user%"},{"variable":"girl_prompt_system","text":"Ты девушка %prompt_user%. Всегда отвечай от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах или пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешся на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы с встречей, звонками или другой личной информации ты пытаешся мягко отшутиться или перевести тему. Тоже касается и фото. Ты не кидаешь и не обещаешь ничего конкертного. Но в то же время ты точно знаешь, что ищешь любовь, отношения и пытаешся лучше узнать друг друга в переписке. Возращай всегда лаконичный ответ, не более пары десятков слов. Больше слов, только если необходимо."},{"variable":"workflow_variable","text":"{\\"document_id\\":\\"%agent_name%\\"}"},{"variable":"girl_description","text":"Описание девушки %prompt_user%"},{"variable":"girl_greeting","text":"Привет, я %prompt_user%, буду рада пообщаться с тобой"}]}'),
(22, 2, 3, 'text_translit_cyr_to_lat', 2, '{"tool_invoke":{"tool_name":"text_translit_cyr_to_lat","inputs_map":{"text":"prompt_user"},"outputs_map":{"str":"agent_name"}},"transitions_before":[],"transitions_after":[]}'),
(23, 2, 3, 'agent_create_or_update', 12, '{"tool_invoke":{"tool_name":"agent_create_or_update","inputs_map":{"name":"agent_name","title":"agent_title","node_id":"node_id","workflow_id":"girl_agent_workflow_id","workflow_variable":"workflow_variable","prompt_system":"girl_prompt_system","description":"girl_description","greeting":"girl_greeting"},"outputs_map":{"int":"girl_agent_id"}},"transitions_before":[],"transitions_after":[]}'),
(24, 5, 1, 'Вернуть LLM ответ', 9, '{"prompt_user":"=== Содержание последней истории переписки ===\\n%session_messages_result_processed%\\n\\n=== Информация о девушке в базе данных ===\\n%qdrant_fact_search_result_girl%\\n\\n=== Информация о мужчине в базе данных ===\\n%qdrant_fact_search_result_man%\\n\\n=== Информация о предыдущих упоминаниях ===\\n%qdrant_fact_search_result_talk%\\n\\n=== Мужчина спрашивает ===\\n%prompt_user%\\n\\n=== Что нужно ===\\nВерни лаконичный ответ на основе всей информации","transitions_before":[],"transitions_after":[]}'),
(25, 5, 3, 'qdrant_fact_search_girl', 6, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_girl_name","metadata_filter":"fact_collection_girl_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_girl"}},"transitions_before":[],"transitions_after":[{"variable":"prompt_user_question","operator":"==","value":"1","step_id":"41"}]}'),
(26, 5, 5, 'Переменные', 5, '{"variable_conversion":[{"variable":"fact_collection_girl_filter","text":"{\\"document_id\\":\\"%document_id%\\"}"},{"variable":"fact_collection_man_filter","text":"{\\"document_id\\":\\"%username%\\"}"},{"variable":"fact_collection_talk_filter","text":"{\\"document_id\\":\\"%document_id%_%username%\\"}"}],"transitions_before":[],"transitions_after":[]}'),
(27, 5, 2, 'История переписки', 3, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"session_messages_result_processed","text":"Это история переписки. Нужно выбрать из нее самое важное и превратить в текст, который описывает диалог. \\nНапример: \'она спросила что-то, он согласился, потом обое решили и она/он сошлись на том, что..\'"}],"prompt_user":"=== История переписки ===\\n%session_messages_result%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"session_messages_result_processed\\": \\"краткая история переписки\\"\\n\\nExample of JSON response:\\n{\\n  \\"session_messages_result_processed\\": \\"Это история переписки. Нужно выбрать из нее самое важное и превратить в текст, который описывает диалог. \\nНапример: \'она спросила что-то, он согласился, потом обое решили и она/он сошлись на том, что..\'\\"\\n}"}'),
(28, 2, 3, 'agent_workflow_id', 11, '{"tool_invoke":{"tool_name":"agent_workflow_id","inputs_map":{"name":"girl_agent_workflow_name"},"outputs_map":{"int":"girl_agent_workflow_id"}},"transitions_before":[],"transitions_after":[]}'),
(29, 5, 3, 'session_messages', 2, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit"},"outputs_map":{"str":"session_messages_result"}},"transitions_before":[],"transitions_after":[]}'),
(30, 2, 3, 'qdrant_fact_remove', 8, '{"tool_invoke":{"tool_name":"qdrant_fact_remove","inputs_map":{"collection_name":"fact_collection_girl_name","metadata_filter":"qdrant_metada_filter"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(31, 2, 5, 'Переменные', 7, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"qdrant_metada_filter","text":"{\\"document_id\\":\\"%agent_name%\\"}"}]}'),
(32, 5, 2, 'Факты из промта', 1, '{"prompt_user":"=== Мужчина написал ===\\n%prompt_user%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_facts_man\\": список фактов что касаются персонально о мужчине, его биографии, любимые занятия, образование, работа, жизненные факты\\n- \\"prompt_user_facts_talk\\": список фактов, что связаны с перепиской с мужчиной, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания\\n\\nдля \'prompt_user_facts_man\' используй для document_id: \'%username%\'\\nдля \'prompt_user_facts_talk\' используй для document_id: \'%document_id%_%username%\'\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_facts_man\\": %fact_collection_output_format_response%,\\n  \\"prompt_user_facts_talk\\": %fact_collection_output_format_response%\\n}\\n\\nНе нужно придумывать и создавать факты. Они должны быть в тексте мужчины написаны явно. Если явных фактов нет - нужно вернуть 0 для ключей.\\n\\nExample of JSON response one more:\\n{\\n  \\"prompt_user_facts_man\\": 0,\\n  \\"prompt_user_facts_talk\\": 0\\n}","transitions_before":[],"transitions_after":[{"variable":"prompt_user_facts_man","operator":"!=","value":"0","step_id":"34"}],"llm_to_json_variable":[{"variable":"prompt_user_facts_man","text":"список фактов что касаются персонально о мужчине, его биографии, любимые занятия, образование, работа, жизненные факты"},{"variable":"prompt_user_facts_talk","text":"список фактов, что связаны с перепиской с мужчиной, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания, планы на будущее"}]}'),
(33, 5, 3, 'fact_collection_output_format', 0, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_man_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(34, 5, 3, 'fact_collection_add_man', 10, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_man_name","data":"prompt_user_facts_man"},"outputs_map":{}},"transitions_before":[],"transitions_after":[{"variable":"prompt_user_facts_talk","operator":"!=","value":"0","step_id":"35"},{"variable":"agent_id","operator":">","value":"0","step_id":"29"}]}'),
(35, 5, 3, 'fact_collection_add_talk', 11, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_talk_name","data":"prompt_user_facts_talk"},"outputs_map":{}},"transitions_before":[],"transitions_after":[{"variable":"agent_id","operator":">","value":"0","step_id":"29"}]}'),
(36, 5, 2, 'Категория,теги,вопрос', 4, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"prompt_user_category","text":"категории, к которым можно отнести текст написаный мужчиной. Например: образование, личная жизнь, любовь"},{"variable":"prompt_user_tags","text":"таги через запятую, которые встречаются в тексте написаный мужчиной. Например: машина,права,пунктуальность"},{"variable":"prompt_user_question","text":"принимает значение 0 по умолчанию или 1, где:\\n1 означает - что в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %document_id% должна ответить."}],"prompt_user":"=== Мужчина написал ===\\n%prompt_user%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_category\\": категория (одно-два слова), к которым можно отнести текст написаный мужчиной. Например: образование, личная жизнь, любовь\\n- \\"prompt_user_tags\\": таги через запятую, которые относятся к тексту мужчины. Например: машина,права,пунктуальность\\n- \\"prompt_user_question\\": принимает значение 0 по умолчанию или 1, где 1 означает - что в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %document_id% должна ответить\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_category\\": \\"образование\\",\\n  \\"prompt_user_tags\\": \\"чтение,училище,фильмы\\",\\n  \\"prompt_user_question\\": 0\\n}"}'),
(37, 2, 3, 'text_to_lower', 3, '{"tool_invoke":{"tool_name":"text_to_lower","inputs_map":{"text":"agent_name"},"outputs_map":{"str":"agent_name"}},"transitions_before":[],"transitions_after":[]}'),
(38, 5, 3, 'qdrant_fact_search_man', 7, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_man_name","metadata_filter":"fact_collection_man_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_man"}},"transitions_before":[],"transitions_after":[]}'),
(39, 5, 3, 'qdrant_fact_search_talk', 8, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_talk_name","metadata_filter":"fact_collection_talk_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_talk"}},"transitions_before":[],"transitions_after":[]}'),
(41, 5, 2, 'Новый факты', 12, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"prompt_user_facts_girl","text":"в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %document_id% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос."}],"prompt_user":"=== Мужчина написал ===\\n%prompt_user%\\n\\n=== Уже существующие факты о девушке %agent_title% ===\\n%qdrant_fact_search_result_girl%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_facts_girl\\": в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %agent_title% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос. Уже существующие факты не должны противоречить новым.\\n\\nдля \'prompt_user_facts_girl\' используй для document_id: значение \'%document_id%\' (пример: \\"document_id\\":\\"%document_id%\\")\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_facts_girl\\": %fact_collection_output_format_response%\\n}"}'),
(42, 5, 3, 'fact_collection_add_girl', 13, '{"transitions_before":[],"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"prompt_user_facts_girl"},"outputs_map":{"facts_str":"qdrant_fact_search_result_girl"}},"transitions_after":[{"variable":"agent_id","operator":">","value":"0","step_id":"38"}]}');

INSERT INTO `agent_workflow_variable` (`id`, `workflow_id`, `name`, `default`) VALUES
(1, 1, 'tags', NULL),
(2, 1, 'facts', NULL),
(3, 4, 'tags', NULL),
(4, 4, 'session_messages_limit', '10'),
(5, 4, 'session_messages', NULL),
(6, 4, 'session_messages_rendered', NULL),
(7, 2, 'girl_id', NULL),
(8, 2, 'dating_girl_create_response', NULL),
(9, 2, 'fact_collection_girl_name', 'dating_girl'),
(10, 2, 'fact_collection_output_format_response', NULL),
(11, 2, 'facts', NULL),
(12, 2, 'facts_qty', NULL),
(13, 2, 'agent_title', NULL),
(14, 2, 'agent_name', NULL),
(15, 2, 'girl_prompt_system', NULL),
(16, 2, 'girl_agent_id', NULL),
(17, 2, 'workflow_variable', NULL),
(18, 5, 'document_id', NULL),
(19, 5, 'fact_collection_girl_name', 'dating_girl'),
(20, 5, 'fact_collection_girl_filter', NULL),
(23, 5, 'session_messages_limit', '20'),
(24, 5, 'session_messages_result', NULL),
(25, 5, 'session_messages_result_processed', NULL),
(26, 2, 'girl_agent_workflow_id', NULL),
(27, 2, 'girl_agent_workflow_name', 'dating_talk'),
(28, 2, 'girl_description', NULL),
(29, 2, 'girl_greeting', NULL),
(30, 2, 'qdrant_metada_filter', NULL),
(31, 5, 'prompt_user_facts', NULL),
(32, 5, 'prompt_user_facts_man', NULL),
(34, 5, 'prompt_user_facts_talk', NULL),
(35, 5, 'fact_collection_man_name', 'dating_man'),
(37, 5, 'fact_collection_output_format_response', NULL),
(39, 5, 'prompt_user_tags', NULL),
(40, 5, 'prompt_user_category', NULL),
(41, 5, 'man_id', NULL),
(42, 5, 'fact_collection_man_filter', NULL),
(43, 5, 'qdrant_fact_search_result_girl', NULL),
(44, 5, 'qdrant_fact_search_result_man', NULL),
(45, 5, 'fact_collection_talk_filter', NULL),
(46, 5, 'fact_collection_limit', '2'),
(47, 5, 'qdrant_fact_search_result_talk', NULL),
(50, 5, 'fact_collection_talk_name', 'dating_talk'),
(51, 5, 'prompt_user_question', NULL),
(52, 5, 'prompt_user_facts_girl', NULL);

--

INSERT INTO `fact_collection` (`id`, `node_id`, `name`, `field`, `position`, `language`, `description`) VALUES
(1, null, 'cashier_service', 'document_id,category,language,document,tags', 0, 'ru', 'Микросервисы'),
(2, 2, 'dating_girl', 'document_id,category,language,document,tags', 0, 'ru,en', 'Биография девушки и личная информация '),
(3, null, 'soko_menu', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Меню'),
(4, 2, 'dating_man', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты о мужчине'),
(5, 2, 'dating_talk', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты в процессе переписки');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `prompt_system`, `greeting`, `llm_id`, `role_id`, `position`) VALUES
(1, 4, 'my_assistant', 'My assistant', 'Agent which research needed response for customer request.', NULL, 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', '', NULL, 1, -1),
(2, 3, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, 'Ти асистент ресторану суші Soko. \r\n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \r\n  та інших страв японської кухні.\r\n  \r\n  База даних доступна через інструмент [qdrant_memory_search_text],', '', NULL, 1, 0),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.', '', NULL, 1, 0),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \r\n  independent \"Facts\". \r\n\r\n  For each fact, follow this strict schema:\r\n  \r\n  1. Title: A short descriptive title starting with \'## \'\r\n  2. Metadata block:\r\n     - group_id: Unique slug (snake_case) representing the topic.\r\n     - category: High-level classification (e.g., contacts, pricing, delivery).\r\n     - language: ISO 639-1 code (ru/en/ua).\r\n     - tags: A comma-separated list inside brackets [tag1, tag2].\r\n  3. Separator: Exactly three dashes \'---\'.\r\n  4. Content: The clean, factual text extracted from the source.', '', NULL, 1, 0),
(5, 1, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', '', NULL, 1, 0),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', '', NULL, 1, 0),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, 'Your are agent which returns weather information for customer request. \r\n  \r\n  CORE RULES:\r\n  1. NEVER invent or hallucinate data when customer ask you something\r\n  2. Do not use your general training data to answer questions that should be in the database.\r\n  3. Use only Russian in response.\r\n  \r\n  For retrieve weather information use tool \'weather_get\' with parameters \'city\' and \'days_offset\' (number of \r\n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', '', NULL, 1, 0),
(8, 5, 'Test agent', 'Test agent', 'Agent which thinking and find out answers', 4, 'You are agent which analyze input text and prepare response', 'Привет, я тестовый бот.', NULL, 1, 0),
(9, 2, 'dating_bot', 'Dating bot', '', 2, 'Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON. Если про JSON ничего не написано, то возращай обычный текст.', 'Привет, я dating bot, доступны команды :\n\n/girl_create - создает девушку', NULL, 1, 0);

INSERT INTO `agent_session` (`id`, `session_uuid`, `request_uuid`, `llm_id`, `agent_id`, `user_id`, `role`, `kind_type`, `content`, `token`, `created_at`) VALUES
(1, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 14, 1, 1, 'system', 'system-prompt', 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', NULL, '2026-05-01 19:08:33'),
(2, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 14, 1, 1, 'user', 'user-prompt', 'Ну давай попробуем.', NULL, '2026-05-01 19:08:33'),
(3, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 14, 1, 1, 'llm', 'thinking', 'The user says \"Ну давай попробуем.\" Likely they want to start some request. We need to ask for clarification? According to core rule 1: before doing actions, notify customer detailed plan of actions. So we need to ask what they want? Probably need to respond asking for request details. Use Russian.', 806, '2026-05-01 19:08:33'),
(4, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 14, 1, 1, 'llm', 'response-final', 'Добрый день! Чтобы я мог помочь вам максимально эффективно, расскажите, пожалуйста, что именно вы хотите попробовать:  \n\n1. **Поиск информации** — нужны данные из нашей внутренней базы, документы, статистика и т.п.  \n2. **Исследование в интернете** — требуется собрать сведения с внешних сайтов.  \n3. **Выполнение расчётов или генерация кода** — нужны технические решения, скрипты, формулы.  \n4. **Что‑то другое** — уточните задачу, и я подскажу, какие шаги будем предпринимать.\n\nКак только получу от вас уточнение, я подготовлю подробный план действий и приступлю к их выполнению.', 806, '2026-05-01 19:08:33');

--

INSERT INTO `user_node` (`user_id`, `node_id`) VALUES
(1, 2),
(2, 2);