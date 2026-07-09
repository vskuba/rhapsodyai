INSERT INTO `llm` (`id`, `name`) VALUES
(1, 'openrouter/meta-llama/llama-3.3-70b-instruct:free'),
(2, 'openrouter/openai/gpt-oss-120b:free'),
(3, 'openrouter/qwen/qwen3-next-80b-a3b-instruct:free'),
(4, 'ollama/qwen2.5:7b'),
(5, 'ollama/qwen2.5:14b'),
(6, 'ollama/qwen2.5-coder:7b'),
(7, 'ollama/gpt-oss:20b'),
(8, 'ollama/qwen3:30b'),
(9, 'ollama/qwen3-coder:30b'),
(10, 'groq/llama-3.3-70b-versatile'),
(11, 'groq/openai/gpt-oss-120b'),
(12, 'gemini/gemini-2.5-flash-lite'),
(13, 'gemini/gemini-2.5-flash'),
(14, 'gemini/gemini-2.5-pro'),
(15, 'mistral/mistral-medium-2505'),
(16, 'mistral/mistral-medium-2508'),
(17, 'huggingface/meta-llama/Llama-3.3-70B-Instruct'),
(18, 'cerebras/gpt-oss-120b');

--

INSERT INTO `role` (`id`, `name`) VALUES
(1, 'admin'),
(2, 'manager_dating'),
(3, 'manager_cashier'),
(4, 'manager_dating_junior');

--

INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role_id`, `created_at`) VALUES
(1, 'admin', 'admin@example.com', '$2b$12$7i4Q9GNhQ.jMRL9R.juWh.txIaVBC0vqv9Deg5aBj4OO/Q.YLICnC', 1, '2026-04-26 09:17:35'), -- Password: admin123
(2, 'lilia', 'lilia@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 2, '2026-04-26 09:17:35'), -- Password: user123
(3, 'olga', 'olga@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 3, '2026-04-26 09:17:35'), -- Password: user123
(4, 'alena', 'alena@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 4, '2026-04-26 09:17:35'); -- Password: user123

--

INSERT INTO `user_llm` (`user_id`, `llm_id`, `rate_limit_at`, `position`) VALUES
(1, 1, NULL, 9),
(1, 2, NULL, 10),
(1, 3, NULL, 11),
(1, 10, NULL, 0),
(1, 11, NULL, 1),
(1, 12, NULL, 3),
(1, 13, NULL, 4),
(1, 14, NULL, 5),
(1, 15, NULL, 6),
(1, 16, NULL, 7),
(1, 17, NULL, 2),
(1, 18, NULL, 8),
(2, 1, NULL, 9),
(2, 2, NULL, 10),
(2, 3, NULL, 11),
(2, 10, NULL, 0),
(2, 11, NULL, 1),
(2, 12, NULL, 3),
(2, 13, NULL, 4),
(2, 14, NULL, 5),
(2, 15, NULL, 6),
(2, 16, NULL, 7),
(2, 17, NULL, 2),
(2, 18, NULL, 8),
(4, 1, NULL, 9),
(4, 2, NULL, 10),
(4, 10, NULL, 0),
(4, 11, NULL, 1),
(4, 12, NULL, 3),
(4, 13, NULL, 4),
(4, 14, NULL, 5),
(4, 15, NULL, 6),
(4, 16, NULL, 7),
(4, 17, NULL, 2),
(4, 18, NULL, 8);

--

INSERT INTO `companion` (`id`, `name`, `title`) VALUES
(1, 'Vadim', 'Vadim'),
(2, 'Olenka', 'Olenka');

--

INSERT INTO `setting` (`id`, `key`, `user_id`, `value`) VALUES
(4, 'llm_active', 1, 'groq:openai/gpt-oss-120b');

--

INSERT INTO `node` (`id`, `name`, `position`) VALUES
(1, 'Cashier', 0),
(2, 'Dating', -3),
(3, 'Soko', 0),
(4, 'Chat', -1),
(5, 'Test', -2),
(6, 'Dev', 1);

--

INSERT INTO `role_node` (`role_id`, `node_id`) VALUES
(3, 1),
(2, 2),
(4, 2);

--

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(1, 1, 'response_cashier', 'Чат кашира', 'Ответить пользователю', 0, 0),
(2, 2, 'dating_bot', 'Dating bot', 'Генерируем коллекции девушки', 0, 0),
(3, 3, 'response_soko', 'Чат суши-бара', 'Ответить пользователю', 0, 0),
(4, 5, 'test', 'Test', 'Simple test workflow', -1, 0),
(5, 2, 'dating_talk', 'Чат с девушкой', 'Чат с девушкой', 0, 0),
(6, 2, 'girl_fact_invent', 'Придумать факты девушки', 'Sub-workflow: придумывает новые факты о девушке для ответа на личный вопрос', 0, 1),
(7, 2, 'companion_fact_extract', 'Извлечь факты собеседника', 'Sub-workflow: извлекает из сообщения факты о собеседнике и переписке, сохраняет в коллекции', 0, 1),
(8, 6, 'export_agent_workflow', 'Экспорт workflow таблиц', 'Экспортирует agent_workflow и agent_workflow_* таблицы из БД в миграцию 0002.sql', 0, 0);

--

INSERT INTO `agent_workflow_step_type` (`id`, `name`, `icon`, `description`, `description_full`, `metadata`) VALUES
(1, 'return_response_llm', '↩L', 'Вернуть LLM ответ', 'Собираем полный запрос на LLM с учетом короткой и длинной памяти, всей связанной информации в БД и отдаем LLM для формирования наиболее качественного ответа.', ''),
(2, 'llm_to_json', '🧠', 'LLM -> JSON', 'Ожидает ответ от LLM в виде JSON. Далее каждый ключ JSON доступен в последующих шагах', ''),
(3, 'tool_invoke', '⚙️', 'Вызов инструмента', 'Вызываем инструмент. Передаем в аргументы текущие переменные и сохраняем ответ в переменные.', ''),
(4, 'return_response_text', '↩T', 'Вернуть текстовый ответ', 'Возращаем текстовый ответ на основе шаблона из переменных', ''),
(5, 'variable_conversion', '❴❵', 'Переменные', 'Переопределяем значения переменных', ''),
(6, 'workflow_invoke', '🇼', 'Вызов workflow', 'Вызываем вложенный workflow (sub-workflow): передаем входящие переменные, получаем результат в переменную и продолжаем выполнение.', '');

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
(12, 4, 4, 'return_response_text', 4, '{"prompt_user":"Команда /go найдена","transitions_after":[]}'),
(13, 2, 3, 'agent_exists', 5, '{"tool_invoke":{"tool_name":"agent_exists","inputs_map":{"find_by":"agent_exists_find_by"},"outputs_map":{"bool":"agent_exists_find_by_result"}},"transitions_before":[],"transitions_after":[{"variable":"agent_exists_13_result_bool","operator":"==","value":"True","step_id":"44"}]}'),
(14, 2, 4, 'Вернуть список команд', 0, '{"transitions_before":[{"variable":"prompt_user","operator":"==","value":"/girl_create","step_id":"16"}],"transitions_after":[],"prompt_user":"%agent_greeting%","continue_workflow":true}'),
(15, 2, 4, 'dating_girl_create_response', 14, '{"prompt_user":"Девушка %prompt_user% успешно создана.\\n\\nБыло создано %fact_collection_add_20_result_facts_qty% фактов.","transitions_before":[],"transitions_after":[]}'),
(16, 2, 4, 'Спросить имя девушки', 1, '{"prompt_user":"Напишите желаемое имя девушки:","transitions_before":[],"transitions_after":[],"continue_workflow":true}'),
(18, 2, 3, 'fact_collection_output_format', 6, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(19, 2, 2, 'LLM -> JSON', 7, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"facts","text":"список фактов"}],"prompt_user":"Нужно придумать биографию девушки. Известны такие факты о ней:\\n- имя: %prompt_user%\\n\\nНужно придумать биографию. Основные исходные данные: \\n1. она родом из города в Украине\\n2. возраст от 20 до 35\\n3. имеет образование\\n4. не имеет детей\\n5. не в отношениях\\n\\nОстальные детали придумай. Все факты и детали не должны противоречить друг другу. Нужно придумать, как минимум, 4 факта в биографии по каждому пункту:\\n- подростковый возраст\\n- учеба\\n- отношения с родителями\\n- любимые занятия и увлечения\\n- любовные отношения\\n- путешествия\\n- работа\\n\\nВсего фактов должно быть 32.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"facts\\": список фактов\\n\\ndocument_id всегда \'%text_to_lower_37_result_str%\'\\n\\nExample of JSON response:\\n{\\n  \\"facts\\": %fact_collection_output_format_18_result_str%\\n}"}'),
(20, 2, 3, 'fact_collection_add', 10, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"facts"},"outputs_map":{"facts_qty":"facts_qty"}},"transitions_before":[],"transitions_after":[]}'),
(21, 2, 5, 'Переменные', 11, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_title","text":"%prompt_user%"},{"variable":"workflow_variable","text":"{\\"document_id\\":\\"%text_to_lower_37_result_str%\\"}"},{"variable":"girl_description","text":"Описание девушки %prompt_user%"},{"variable":"girl_greeting","text":"Привет, я %prompt_user%, буду рада пообщаться с тобой"}]}'),
(22, 2, 3, 'text_translit_cyr_to_lat', 2, '{"tool_invoke":{"tool_name":"text_translit_cyr_to_lat","inputs_map":{"text":"prompt_user"},"outputs_map":{"str":"agent_name"}},"transitions_before":[],"transitions_after":[]}'),
(23, 2, 3, 'agent_create_or_update', 13, '{"tool_invoke":{"tool_name":"agent_create_or_update","inputs_map":{"name":"text_to_lower_37_result_str","title":"prompt_user","node_id":"node_id","workflow_id":"agent_workflow_id_28_result_int","workflow_variable":"workflow_variable","prompt_system":"girl_prompt_system","description":"girl_description","greeting":"girl_greeting"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(24, 5, 1, 'Вернуть LLM ответ', 13, '{"prompt_user":"=== Текущее время ===\\n%datetime_current_get_45_result_str%\\n\\n=== Содержание последней истории переписки ===\\n%session_messages_result_processed%\\n\\n=== Информация о %agent_name% в базе данных ===\\n%qdrant_fact_search_result_girl%\\n\\n=== Информация о %companion_title% в базе данных ===\\n%qdrant_fact_search_result_companion%\\n\\n=== Информация о предыдущих соглашениях ===\\n%qdrant_fact_search_39_result_str%\\n\\n=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Что нужно ===\\n1. Вернуть лаконичный и короткий ответ согласно системному промпту.\\n2. КРИТИЧЕСКОЕ ПРАВИЛО: Если сообщение %companion_title% — это неразборчивый набор букв, опечатка, случайные символы или у тебя нет четкого понимания, что ответить, ты ОБЯЗАНА вернуть абсолютно пустую строку (ни одного символа, пробела или знака препинания). Не пытайся отшучиваться или переспрашивать в таких случаях.","transitions_before":[],"transitions_after":[]}'),
(25, 5, 3, 'qdrant_fact_search_girl', 6, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_girl_name","metadata_filter":"fact_collection_girl_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_girl"}},"transitions_before":[],"transitions_after":[]}'),
(26, 5, 5, 'Переменные', 5, '{"variable_conversion":[{"variable":"fact_collection_girl_filter","text":"{\\"document_id\\":\\"%document_id%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"},{"variable":"fact_collection_man_filter","text":"{\\"document_id\\":\\"%companion_name%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"},{"variable":"fact_collection_talk_filter","text":"{\\"document_id\\":\\"%document_id%_%companion_name%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"}],"transitions_before":[],"transitions_after":[]}'),
(27, 5, 2, 'История переписки', 3, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"session_messages_result_processed","text":"Это история переписки. Нужно выбрать из нее самое важное и превратить в текст, который описывает диалог. \\nНапример: \'она спросила что-то, он согласился, потом обое решили и она/он сошлись на том, что..\'"}],"prompt_user":"=== История переписки ===\\n%session_messages_29_result_str%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"session_messages_result_processed\\": \\"краткая история переписки\\"\\n\\nExample of JSON response:\\n{\\n  \\"session_messages_result_processed\\": \\"Это история переписки. Нужно выбрать из нее самое важное и превратить в текст, который описывает диалог. \\nНапример: \'она спросила что-то, он согласился, потом обое решили и она/он сошлись на том, что..\'\\"\\n}"}'),
(28, 2, 3, 'agent_workflow_id', 12, '{"tool_invoke":{"tool_name":"agent_workflow_id","inputs_map":{"name":"girl_agent_workflow_name"},"outputs_map":{"int":"girl_agent_workflow_id"}},"transitions_before":[],"transitions_after":[]}'),
(29, 5, 3, 'session_messages', 2, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit"},"outputs_map":{"str":"session_messages_result"}},"transitions_before":[],"transitions_after":[]}'),
(30, 2, 3, 'qdrant_fact_remove', 9, '{"tool_invoke":{"tool_name":"qdrant_fact_remove","inputs_map":{"collection_name":"fact_collection_girl_name","metadata_filter":"qdrant_metada_filter"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(31, 2, 5, 'Переменные', 8, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"qdrant_metada_filter","text":"{\\"document_id\\":\\"%text_to_lower_37_result_str%\\"}"}]}'),
(36, 5, 2, 'Категория,теги,вопрос', 4, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"prompt_user_category","text":"категории, к которым можно отнести текст, что написаный %companion_title%. Например: образование, личная жизнь, любовь"},{"variable":"prompt_user_tags","text":"таги через запятую, которые встречаются в тексте написаный %companion_title%. Например: машина,права,пунктуальность"},{"variable":"prompt_user_question","text":"принимает значение 0 по умолчанию или 1, где:\\n1 означает - что в тексте написаный %companion_title%, есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %document_id% должна ответить. Если вопрос общий, например какая погода, время, новости, все что не касается лично девушки ответ только 0."}],"prompt_user":"=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_category\\": категория (одно-два слова), к которым можно отнести текст написаный мужчиной. Например: образование, личная жизнь, любовь\\n- \\"prompt_user_tags\\": таги через запятую, которые относятся к тексту %companion_title%. Например: машина,права,пунктуальность\\n- \\"prompt_user_question\\": принимает значение 0 по умолчанию или 1, где 1 означает - что в тексте написаный %companion_title%, есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %document_id% должна ответить\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_category\\": \\"образование\\",\\n  \\"prompt_user_tags\\": \\"чтение,училище,фильмы\\",\\n  \\"prompt_user_question\\": 0\\n}"}'),
(37, 2, 3, 'text_to_lower', 3, '{"tool_invoke":{"tool_name":"text_to_lower","inputs_map":{"text":"text_translit_cyr_to_lat_22_result_str"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(38, 5, 3, 'qdrant_fact_search_companion', 9, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_man_name","metadata_filter":"fact_collection_man_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_man"}},"transitions_before":[],"transitions_after":[]}'),
(39, 5, 3, 'qdrant_fact_search_talk', 11, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_talk_name","metadata_filter":"fact_collection_talk_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_talk"}},"transitions_before":[],"transitions_after":[]}'),
(43, 2, 5, 'Переменные', 4, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_exists_find_by","text":"{\\"name\\":\\"%text_to_lower_37_result_str%\\"}"}]}'),
(44, 2, 4, 'Агент уже существует', 15, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Девушка с таким именем \\"%prompt_user%\\" уже зарегистрирована, придумайте другое имя"}'),
(45, 5, 3, 'datetime_current_get', 12, '{"tool_invoke":{"tool_name":"datetime_current_get","inputs_map":{"timezone":"datetime_current_get_zone"},"outputs_map":{"str":"datetime_current_get_response"}},"transitions_before":[],"transitions_after":[]}'),
(46, 5, 5, 'Переменные', 8, '{"variable_conversion":[{"variable":"qdrant_fact_search_result_girl","text":"%qdrant_fact_search_25_result_str%"}],"transitions_before":[],"transitions_after":[{"variable":"prompt_user_question","operator":"==","value":"1","step_id":"48"}]}'),
(47, 5, 5, 'Переменные', 10, '{"variable_conversion":[{"variable":"qdrant_fact_search_result_companion","text":"%qdrant_fact_search_38_result_str%"}],"transitions_before":[],"transitions_after":[]}'),
(48, 5, 6, 'girl_fact_create', 16, '{"workflow_invoke":{"workflow_id":6,"inputs_map":{"document_id":"document_id","girl_existing_facts":"qdrant_fact_search_result_girl"},"outputs_map":{"fact_collection_add_51_result_facts_str":"qdrant_fact_search_result_girl"}},"transitions_before":[],"transitions_after":[{"variable":"agent_id","operator":">","value":"0","step_id":"38"}]}'),
(49, 6, 3, 'fact_collection_output_format', 0, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(50, 6, 2, 'Новый факты', 1, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"prompt_user_facts_girl","text":"в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %document_id% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос."}],"prompt_user":"=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Уже существующие факты о девушке %agent_title% ===\\n%girl_existing_facts%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_facts_girl\\": в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %agent_title% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос. Уже существующие факты не должны противоречить новым.\\n\\nдля \'prompt_user_facts_girl\' используй для document_id: значение \'%document_id%\' (пример: \\"document_id\\":\\"%document_id%\\")\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_facts_girl\\": %fact_collection_output_format_49_result_str%\\n}"}'),
(51, 6, 3, 'fact_collection_add_girl', 2, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"prompt_user_facts_girl"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(52, 6, 4, 'Вернуть факты', 3, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%fact_collection_add_51_result_facts_str%","continue_workflow":false}'),
(53, 7, 3, 'fact_collection_output_format', 0, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_man_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(54, 7, 2, 'Факты из промта', 1, '{"prompt_user":"=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_facts_man\\": список фактов что касаются персонально о %companion_title%: биографии, любимые занятия, образование, работа, жизненные факты\\n- \\"prompt_user_facts_talk\\": список фактов, что связаны с перепиской с %companion_title%, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания\\n\\nдля \'prompt_user_facts_man\' используй document_id: \'%companion_name%\'\\nдля \'prompt_user_facts_talk\' используй document_id: \'%document_id%_%companion_name%\'\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_facts_man\\": %fact_collection_output_format_53_result_str%,\\n  \\"prompt_user_facts_talk\\": %fact_collection_output_format_53_result_str%\\n}\\n\\nНе нужно придумывать и создавать факты. Они должны быть в тексте %companion_title% написаны явно. Если явных фактов нет - нужно вернуть 0 для ключей.\\n\\nExample of JSON response one more:\\n{\\n  \\"prompt_user_facts_man\\": 0,\\n  \\"prompt_user_facts_talk\\": 0\\n}","transitions_before":[],"transitions_after":[{"variable":"prompt_user_facts_man","operator":"==","value":"0","step_id":"57"}],"llm_to_json_variable":[{"variable":"prompt_user_facts_man","text":"список фактов что касаются персонально о %companion_title%, его биографии, любимые занятия, образование, работа, жизненные факты"},{"variable":"prompt_user_facts_talk","text":"список фактов, что связаны с перепиской с %companion_title%, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания, планы на будущее"}]}'),
(55, 7, 3, 'fact_collection_add_man', 2, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_man_name","data":"prompt_user_facts_man"},"outputs_map":{}},"transitions_before":[],"transitions_after":[{"variable":"prompt_user_facts_talk","operator":"==","value":"0","step_id":"57"}]}'),
(56, 7, 3, 'fact_collection_add_talk', 3, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_talk_name","data":"prompt_user_facts_talk"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(57, 7, 4, 'Вернуть факты', 4, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%prompt_user_facts_man%","continue_workflow":false}'),
(58, 5, 6, 'companion_fact_extract', 0, '{"workflow_invoke":{"workflow_id":7,"inputs_map":{"document_id":"document_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(59, 8, 3, 'mysql_export_to_migration', 1, '{"tool_invoke":{"tool_name":"mysql_export_to_migration","inputs_map":{"tables":"mysql_tables_find_62_result_tables_str","migration_file":"migration_file"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(60, 8, 4, 'Отчет экспорта', 2, '{"transitions_before":[],"transitions_after":[],"prompt_user":"✅ Экспорт завершен. Таблиц: %mysql_export_to_migration_59_result_tables_qty%, строк: %mysql_export_to_migration_59_result_rows_qty%.\nОбновлены: %mysql_export_to_migration_59_result_report_str%","continue_workflow":false}'),
(61, 8, 4, 'Подсказка', 3, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Доступные команды:\n\n/export_agent_workflow - экспорт таблиц agent_workflow* в миграцию 0002.sql","continue_workflow":false}'),
(62, 8, 3, 'mysql_tables_find', 0, '{"tool_invoke":{"tool_name":"mysql_tables_find","inputs_map":{"pattern":"mysql_tables_pattern"},"outputs_map":{}},"transitions_before":[{"variable":"prompt_user","operator":"!=","value":"/export_agent_workflow","step_id":"61"}],"transitions_after":[]}');

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
(15, 'tags', 'workflow', NULL, NULL),
(16, 'facts', 'workflow', NULL, NULL),
(17, 'tags', 'workflow', NULL, NULL),
(18, 'session_messages_limit', 'workflow', '10', NULL),
(19, 'session_messages', 'workflow', NULL, NULL),
(21, 'session_messages_rendered', 'workflow', NULL, NULL),
(24, 'fact_collection_girl_name', 'workflow', 'dating_girl', NULL),
(26, 'facts', 'workflow', NULL, NULL),
(30, 'girl_prompt_system', 'workflow', NULL, NULL),
(32, 'workflow_variable', 'workflow', NULL, NULL),
(34, 'fact_collection_girl_name', 'workflow', 'dating_girl', NULL),
(35, 'fact_collection_girl_filter', 'workflow', NULL, NULL),
(36, 'session_messages_limit', 'workflow', '20', NULL),
(38, 'session_messages_result_processed', 'workflow', NULL, NULL),
(40, 'girl_agent_workflow_name', 'workflow', 'dating_talk', NULL),
(41, 'girl_description', 'workflow', NULL, NULL),
(42, 'girl_greeting', 'workflow', NULL, NULL),
(43, 'qdrant_metada_filter', 'workflow', NULL, NULL),
(45, 'prompt_user_facts_man', 'workflow', NULL, NULL),
(46, 'prompt_user_facts_talk', 'workflow', NULL, NULL),
(47, 'fact_collection_man_name', 'workflow', 'dating_man', NULL),
(49, 'prompt_user_tags', 'workflow', NULL, NULL),
(50, 'prompt_user_category', 'workflow', NULL, NULL),
(53, 'fact_collection_man_filter', 'workflow', NULL, NULL),
(54, 'qdrant_fact_search_result_girl', 'workflow', NULL, NULL),
(56, 'fact_collection_talk_filter', 'workflow', NULL, NULL),
(57, 'fact_collection_limit', 'workflow', '2', NULL),
(59, 'fact_collection_talk_name', 'workflow', 'dating_talk', NULL),
(60, 'prompt_user_question', 'workflow', NULL, NULL),
(61, 'prompt_user_facts_girl', 'workflow', NULL, NULL),
(62, 'agent_exists_find_by', 'workflow', NULL, NULL),
(64, 'datetime_current_get_zone', 'workflow', '+3', NULL),
(70, 'document_id', 'input', NULL, NULL),
(71, 'companion_id', 'global', NULL, NULL),
(72, 'companion_title', 'global', NULL, NULL),
(73, 'companion_name', 'global', NULL, NULL),
(74, 'qdrant_fact_search_result_companion', 'workflow', NULL, NULL),
(75, 'girl_existing_facts', 'input', NULL, 'Существующие факты о девушке (вход sub-workflow girl_fact_invent)'),
(76, 'mysql_tables_pattern', 'workflow', 'agent_workflow', 'Подстрока для поиска таблиц экспорта'),
(77, 'migration_file', 'workflow', 'migrations/0002.sql', 'Файл миграции для экспорта данных');

--

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(15, 1),
(16, 1),
(17, 4),
(18, 4),
(19, 4),
(21, 4),
(24, 2),
(26, 2),
(30, 2),
(32, 2),
(34, 5),
(34, 6),
(35, 5),
(36, 5),
(38, 5),
(40, 2),
(41, 2),
(42, 2),
(43, 2),
(45, 5),
(45, 7),
(46, 5),
(46, 7),
(47, 5),
(47, 7),
(49, 5),
(50, 5),
(53, 5),
(54, 5),
(56, 5),
(57, 5),
(59, 5),
(59, 7),
(60, 5),
(61, 5),
(61, 6),
(62, 2),
(64, 5),
(70, 5),
(70, 6),
(70, 7),
(74, 5),
(75, 6),
(76, 8),
(77, 8);

--

INSERT INTO `agent_workflow_variable_public` (`id`, `node_id`, `name`, `type`, `default`, `position`, `description`) VALUES
(1, 2, 'girl_title', 'proxy', '%prompt_user%', 0, 'Имя девушки'),
(2, 2, 'girl_prompt_system', 'public', 'Ты девушка %girl_title%. Всегда отвечай от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах, пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешься на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы о встречах, звонках или другой личной информации, ты пытаешься мягко отшутиться или перевести тему. То же касается и фото: ты не скидываешь их и не обещаешь ничего конкретного. Но в то же время ты точно знаешь, что ищешь любовь, отношения, и пытаешься лучше узнать друг друга в переписке. Возвращай всегда лаконичный ответ, не более пары десятков слов. Больше слов — только если необходимо.', 2, '');

--

INSERT INTO `agent_workflow_variable_public_role` (`public_variable_id`, `role_id`) VALUES
(2, 2),
(2, 4);

--

INSERT INTO `agent_workflow_variable_public_workflow` (`public_variable_id`, `workflow_id`) VALUES
(1, 2),
(2, 2);

--

INSERT INTO `fact_collection` (`id`, `node_id`, `name`, `field`, `position`, `language`, `description`) VALUES
(1, null, 'cashier_service', 'document_id,category,language,document,tags', 0, 'ru', 'Микросервисы'),
(2, 2, 'dating_girl', 'document_id,category,language,document,tags', 0, 'ru,en', 'Биография девушки и личная информация '),
(3, null, 'soko_menu', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Меню'),
(4, 2, 'dating_man', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты о мужчине'),
(5, 2, 'dating_talk', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты в процессе переписки');

--

INSERT INTO `fact` (`id`, `collection_id`, `document_id`, `file_id`, `category`, `language`, `document`, `tags`, `qdrant_synced`) VALUES
(1, 2, 'anna', NULL, 'childhood', 'uk', 'Анна народилася у місті Львів у 1998 році в родині вчителя історії та медсестри.', 'birth, family, hometown', 0),
(2, 2, 'anna', NULL, 'childhood', 'uk', 'У віці трьох років вона вже вміла читати прості казки українською мовою.', 'early reading, literacy', 0),
(3, 2, 'anna', NULL, 'childhood', 'uk', 'Щороку на Різдво Анна отримувала нову книжку, що розвивало її любов до літератури.', 'tradition, books, reading', 0),
(4, 2, 'anna', NULL, 'childhood', 'uk', 'У дитинстві вона часто грала у парку з братом, катаючись на роликах і граючи у футбол.', 'play, sports, sibling', 0),
(5, 2, 'anna', NULL, 'childhood', 'uk', 'З 6 років Анна відвідувала музичну школу, де навчалась на фортепіано.', 'music, piano, education', 0),
(6, 2, 'anna', NULL, 'teenage', 'uk', 'У підлітковому віці Анна захопилася волонтерською діяльністю, допомагаючи у притулку для безпритульних тварин.', 'volunteering, animals, community', 0),
(7, 2, 'anna', NULL, 'teenage', 'uk', 'В 15 років вона виграла місцевий конкурс есе на тему «Моя Україна», отримавши стипендію на літні літературні табори.', 'competition, essay, scholarship', 0),
(8, 2, 'anna', NULL, 'teenage', 'uk', 'Під час школи Анна була членом шкільного театрального гурту, де грала головні ролі у постановках.', 'theatre, acting, school', 0),
(9, 2, 'anna', NULL, 'teenage', 'uk', 'У 16 років вона поїхала на обмін до Польщі на два місяці, вивчаючи польську мову та культуру.', 'exchange, language, travel', 0),
(10, 2, 'anna', NULL, 'teenage', 'uk', 'У старших класах Анна була старостою класу і організовувала шкільні благодійні ярмарки.', 'leadership, charity, school', 0),
(11, 2, 'anna', NULL, 'education', 'uk', 'У 2016 році Анна вступила до Львівського національного університету імені Івана Франка на факультет економіки.', 'university, economics, enrollment', 0),
(12, 2, 'anna', NULL, 'education', 'uk', 'Вона закінчила бакалаврат у 2020 році з відзнакою, спеціалізуючись у маркетингу та цифрових медіа.', 'graduation, marketing, digital media', 0),
(13, 2, 'anna', NULL, 'education', 'uk', 'Під час навчання Анна проходила стажування у рекламному агентстві «Креатив Плюс», де працювала над кампанією для місцевого бренду одягу.', 'internship, advertising, experience', 0),
(14, 2, 'anna', NULL, 'education', 'uk', 'У 2021 році вона отримала сертифікат Google Analytics, підвищивши свою кваліфікацію у сфері веб-аналітики.', 'certification, analytics, professional development', 0),
(15, 2, 'anna', NULL, 'education', 'uk', 'Анна активно брала участь у студентському клубі «Бізнес-інновації», організовуючи майстер-класи та хакатони.', 'student club, innovation, events', 0),
(16, 2, 'anna', NULL, 'family_relationships', 'uk', 'Відносини Анни з батьками завжди були відкритими: батько часто ділився історичними фактами, а мати підтримувала її творчі проекти.', 'family, parents, support', 0),
(17, 2, 'anna', NULL, 'family_relationships', 'uk', 'Щотижня вони збираються за сімейним обідом у неділю, обговорюючи новини та плани на майбутнє.', 'family dinner, tradition', 0),
(18, 2, 'anna', NULL, 'family_relationships', 'uk', 'Батьки Анни завжди заохочували її до навчання іноземних мов, тому вона вільно володіє англійською та польською.', 'language learning, encouragement', 0),
(19, 2, 'anna', NULL, 'family_relationships', 'uk', 'Після закінчення університету Анна переїхала до Києва, проте підтримує щоденний зв''язок з родиною через відеодзвінки.', 'relocation, communication', 0),
(20, 2, 'anna', NULL, 'family_relationships', 'uk', 'Батьки допомогли їй придбати перший ноутбук, який вона використовує у роботі маркетолога.', 'support, equipment', 0),
(21, 2, 'anna', NULL, 'hobbies', 'uk', 'Анна захоплюється фотографією, особливо вуличними портретами, і має власний Instagram‑профіль з понад 10 000 підписників.', 'photography, social media', 0),
(22, 2, 'anna', NULL, 'hobbies', 'uk', 'У вільний час вона практикує йогу, відвідуючи студію «Зен-центр» у центрі міста.', 'yoga, wellness', 0),
(23, 2, 'anna', NULL, 'hobbies', 'uk', 'Анна любить готувати традиційні українські страви, особливо вареники з різними начинками.', 'cooking, Ukrainian cuisine', 0),
(24, 2, 'anna', NULL, 'hobbies', 'uk', 'Вона регулярно відвідує книжкові клуби, обговорюючи сучасну прозу та поезію.', 'reading, book club', 0),
(25, 2, 'anna', NULL, 'hobbies', 'uk', 'Анна бере участь у марафонах, і в 2022 році пробігла Київський марафон на дистанції 10 км.', 'running, marathon', 0),
(26, 2, 'anna', NULL, 'relationships', 'uk', 'У 2019 році Анна зустріла свого перше кохання під час стажування в рекламному агентстві, проте стосунки розійшлися через різні кар’єрні цілі.', 'first love, internship', 0),
(27, 2, 'anna', NULL, 'relationships', 'uk', 'З 2020 по 2022 рік вона була у стосунках з колегою‑дизайнером, які закінчилися мирно, залишивши дружбу.', 'relationship, colleague, friendship', 0),
(28, 2, 'anna', NULL, 'relationships', 'uk', 'У 2023 році Анна почала зустрічатися з Олексієм, який працює в IT‑сфері, і вони планують спільну подорож до Італії у 2024 році.', 'current relationship, travel plans', 0),
(29, 2, 'anna', NULL, 'relationships', 'uk', 'Вона відкрито говорить, що не планує мати дітей у найближчі п''ять років, зосереджуючись на кар’єрі та особистому розвитку.', 'future plans, childfree', 0),
(30, 2, 'anna', NULL, 'relationships', 'uk', 'Анна підтримує дружбу з колишньою подругою зі школи, з якою вони разом організовують благодійні заходи.', 'friendship, charity', 0),
(31, 2, 'anna', NULL, 'relationships', 'uk', 'Вона вважає важливим відкритий діалог у стосунках і регулярно обговорює з партнером особисті цілі та цінності.', 'communication, values', 0),
(32, 2, 'dasha', NULL, 'детство', 'ru', 'Даша родилась в небольшом городе Кременчуг, Украина, в 1995 году.', 'рождение,город,Украина', 0),
(33, 2, 'dasha', NULL, 'детство', 'ru', 'В детстве Даша часто помогала маме в семейном саду, выращивая помидоры и огурцы.', 'семья,садоводство,детство', 0),
(34, 2, 'dasha', NULL, 'детство', 'ru', 'С пятилетнего возраста Даша посещала местный детский музыкальный кружок, где училась играть на фортепиано.', 'музыка,фортепиано,детский_кружок', 0),
(35, 2, 'dasha', NULL, 'детство', 'ru', 'Первый школьный друг Даши, Иван, переехал в Киев, но они поддерживают связь по соцсетям.', 'дружба,школа,соцсети', 0),
(36, 2, 'dasha', NULL, 'детство', 'ru', 'В возрасте семи лет Даша выиграла школьный конкурс рисунков на тему «Мой город».', 'конкурс,рисунок,детские_таланты', 0),
(37, 2, 'dasha', NULL, 'подростковый возраст', 'ru', 'В старших классах Даша активно участвовала в школьном театральном кружке, исполняя роли в постановках.', 'театральный_кружок,школа,подростки', 0),
(38, 2, 'dasha', NULL, 'подростковый возраст', 'ru', 'В 16 лет Даша впервые поехала в летний лагерь «Соколиный гнёзд», где завела друзей из разных регионов Украины.', 'лагерь,друзья,лето', 0),
(39, 2, 'dasha', NULL, 'подростковый возраст', 'ru', 'Подростком Даша начала заниматься волонтёрской работой в местной библиотеке, помогая организовывать книжные ярмарки.', 'волонтёрство,библиотека,подросток', 0),
(40, 2, 'dasha', NULL, 'подростковый возраст', 'ru', 'В 17 лет Даша получила первую работу – помощницей в кафе «Кофейный уголок», где научилась обслуживать клиентов.', 'работа,кафе,подростковый_опыт', 0),
(41, 2, 'dasha', NULL, 'подростковый возраст', 'ru', 'В старших классах Даша была членом школьного экологического клуба, участвовала в акциях по сбору мусора в городе.', 'экология,школьный_клуб,подростки', 0),
(42, 2, 'dasha', NULL, 'учеба', 'ru', 'В 2013 году Даша поступила в Кременчугский национальный университет на факультет международных отношений.', 'университет,поступление,образование', 0),
(43, 2, 'dasha', NULL, 'учеба', 'ru', 'Во время обучения Даша прошла стажировку в посольстве Украины в Польше, где изучала дипломатический протокол.', 'стажировка,дипломатия,образование', 0),
(44, 2, 'dasha', NULL, 'учеба', 'ru', 'В 2017 году Даша успешно защитила дипломную работу на тему «Влияние цифровой дипломатии на международные переговоры».', 'диплом,исследование,цифровая_дипломатия', 0),
(45, 2, 'dasha', NULL, 'учеба', 'ru', 'За академические успехи Даша получила стипендию Президента Украины на второй курс обучения.', 'стипендия,президент,академические_успехи', 0),
(46, 2, 'dasha', NULL, 'учеба', 'ru', 'В 2018 году Даша завершила бакалавриат с отличием и начала магистратуру по международному праву.', 'бакалавриат,магистратура,право', 0),
(47, 2, 'dasha', NULL, 'отношения с родителя', 'ru', 'Отец Даши – инженер, часто делился с ней своими проектами, вдохновляя её интерес к аналитическому мышлению.', 'семья,отец,инженер', 0),
(48, 2, 'dasha', NULL, 'отношения с родителя', 'ru', 'Мать Даши – учитель начальных классов, поддерживала её в учебных и творческих начинаниях.', 'семья,мать,учитель', 0),
(49, 2, 'dasha', NULL, 'отношения с родителя', 'ru', 'Семья Даши традиционно собирается за ужином каждое воскресенье, обсуждая новости и планы на неделю.', 'семейные_традиции,ужин,общение', 0),
(50, 2, 'dasha', NULL, 'отношения с родителя', 'ru', 'Родители поддержали решение Даши переехать в Киев для работы, предоставив финансовую помощь на первые месяцы.', 'поддержка,переезд,финансы', 0),
(51, 2, 'dasha', NULL, 'отношения с родителя', 'ru', 'В 2020 году Даша помогла родителям оформить онлайн‑банкинг, чтобы они могли управлять финансами дистанционно.', 'технологии,семья,онлайн_банкинг', 0),
(52, 2, 'dasha', NULL, 'любимые занятия и ув', 'ru', 'Даша увлекается йогой и посещает занятия в студии «Баланс» три раза в неделю.', 'йога,здоровье,хобби', 0),
(53, 2, 'dasha', NULL, 'любимые занятия и ув', 'ru', 'В свободное время Даша любит читать современную украинскую литературу, особенно произведения Оксаны Забужко.', 'чтение,литература,украинская_культура', 0),
(54, 2, 'dasha', NULL, 'любимые занятия и ув', 'ru', 'Она активно ведёт Instagram‑блог о путешествиях по Украине, делясь фотографиями и советами.', 'соцсети,путешествия,блог', 0),
(55, 2, 'dasha', NULL, 'любимые занятия и ув', 'ru', 'Даша играет в шахматы в местном клубе «Король», участвует в региональных турнирах.', 'шахматы,клуб,спорт', 0),
(56, 2, 'dasha', NULL, 'любимые занятия и ув', 'ru', 'Она любит готовить блюда национальной кухни, особенно вареники с вишней, которые часто готовит для друзей.', 'кулинария,вареники,друзья', 0),
(57, 2, 'dasha', NULL, 'любовные отношения', 'ru', 'В 2019 году Даша начала отношения с коллегой по работе, Игорем, но они разошлись мирно в начале 2021 года.', 'отношения,коллега,развод', 0),
(58, 2, 'dasha', NULL, 'любовные отношения', 'ru', 'С середины 2021 года Даша встречалась с архитектором Алексеем, который поддерживает её карьерные амбиции.', 'отношения,архитектор,поддержка', 0),
(59, 2, 'dasha', NULL, 'любовные отношения', 'ru', 'Даша и Алексей совместно путешествовали по Карпатам в 2022 году, что укрепило их взаимопонимание.', 'путешествия,Карпаты,отношения', 0),
(60, 2, 'dasha', NULL, 'любовные отношения', 'ru', 'Несмотря на серьёзные отношения, Даша пока не планирует завести детей, сосредотачиваясь на профессиональном росте.', 'планы,дети,карьера', 0),
(61, 2, 'dasha', NULL, 'любовные отношения', 'ru', 'В 2023 году Даша и Алексей решили переехать в Киев, где оба нашли работу в международных организациях.', 'переезд,Киев,работа', 0),
(62, 2, 'dasha', NULL, 'любовные отношения', 'ru', 'Даша открыто говорит, что её главное жизненное правило – «любовь к себе и к делу», что помогает ей поддерживать здоровый баланс в отношениях.', 'мантра,саморазвитие,отношения', 0),
(63, 2, 'lera', NULL, 'детство', 'ru', 'Лера родилась в небольшом городе Ивано-Франковск, где провела первые восемь лет жизни.', 'детство,рождение,Ивано-Франковск', 0),
(64, 2, 'lera', NULL, 'детство', 'ru', 'В детском саду ей нравилось рисовать, и она часто получала похвалы за свои яркие картинки.', 'детство,рисование,творчество', 0),
(65, 2, 'lera', NULL, 'детство', 'ru', 'Семья Леры часто устраивала походы в Карпаты, где она научилась любить природу и горные пейзажи.', 'детство,походы,Карпаты', 0),
(66, 2, 'lera', NULL, 'детство', 'ru', 'Она была старшей из двух детей, её младший брат часто просил её помогать с домашними заданиями.', 'детство,брат,семья', 0),
(67, 2, 'lera', NULL, 'детство', 'ru', 'В возрасте пяти лет Лера начала посещать музыкальную школу, где училась играть на фортепиано.', 'детство,музыка,фортепиано', 0),
(68, 2, 'lera', NULL, 'подростковый возраст', 'ru', 'В средней школе Лера активно участвовала в школьном театральном кружке, где сыграла несколько главных ролей.', 'подростковый возраст,театральный кружок,школа', 0),
(69, 2, 'lera', NULL, 'подростковый возраст', 'ru', 'Она была капитаном школьной волейбольной команды и в 2015 году выиграла региональный турнир.', 'подростковый возраст,спорт,волейбол', 0),
(70, 2, 'lera', NULL, 'подростковый возраст', 'ru', 'В 16 лет Лера начала вести блог о моде и стиле, который быстро набрал несколько тысяч подписчиков.', 'подростковый возраст,блог,мода', 0),
(71, 2, 'lera', NULL, 'подростковый возраст', 'ru', 'Она прошла курс английского языка в международной школе, получив сертификат B2.', 'подростковый возраст,английский,сертификат', 0),
(72, 2, 'lera', NULL, 'подростковый возраст', 'ru', 'В старших классах Лера участвовала в волонтёрском проекте по помощи пожилым людям в её городе.', 'подростковый возраст,волонтёрство,социальная работа', 0),
(73, 2, 'lera', NULL, 'учеба', 'ru', 'В 2018 году Лера поступила в Национальный университет «Киевский национальный экономический университет имени Вадима Гетьмана» на факультет маркетинга.', 'учеба,университет,маркетинг', 0),
(74, 2, 'lera', NULL, 'учеба', 'ru', 'Во время обучения она получила стипендию за академические успехи в течение трёх семестров подряд.', 'учеба,стипендия,академические успехи', 0),
(75, 2, 'lera', NULL, 'учеба', 'ru', 'Лера прошла стажировку в рекламном агентстве «Ogilvy Ukraine», где работала над рекламной кампанией для международного бренда.', 'учеба,стажировка,реклама', 0),
(76, 2, 'lera', NULL, 'учеба', 'ru', 'В 2021 году она защитила дипломную работу на тему «Влияние инфлюенсеров на потребительское поведение в соцсетях», получив оценку «отлично».', 'учеба,диплом,инфлюенсеры', 0),
(77, 2, 'lera', NULL, 'учеба', 'ru', 'После выпуска Лера продолжила обучение, получив сертификат по цифровому маркетингу от Google.', 'учеба,сертификат,Google', 0),
(78, 2, 'lera', NULL, 'отношения с родителя', 'ru', 'Отец Леры — инженер, который всегда поддерживал её интерес к технологиям и помогал с компьютером.', 'родители,отец,поддержка', 0),
(79, 2, 'lera', NULL, 'отношения с родителя', 'ru', 'Мать Леры работает учителем начальных классов и привила дочери любовь к чтению с ранних лет.', 'родители,мать,чтение', 0),
(80, 2, 'lera', NULL, 'отношения с родителя', 'ru', 'Семья часто собирается за большим столом по воскресеньям, где обсуждают новости и планы на неделю.', 'родители,семейные традиции,воскресенье', 0),
(81, 2, 'lera', NULL, 'отношения с родителя', 'ru', 'Родители поддержали её решение переехать в Киев после окончания университета, чтобы начать карьеру.', 'родители,поддержка,переезд', 0),
(82, 2, 'lera', NULL, 'отношения с родителя', 'ru', 'Лера регулярно звонит родителям, делясь успехами и получая советы по личным вопросам.', 'родители,коммуникация,советы', 0),
(83, 2, 'lera', NULL, 'любимые занятия и ув', 'ru', 'Она увлекается йогой и посещает занятия три раза в неделю, считая их важной частью своего здоровья.', 'увлечения,йога,здоровье', 0),
(84, 2, 'lera', NULL, 'любимые занятия и ув', 'ru', 'Лера любит готовить блюда средиземноморской кухни и часто экспериментирует с новыми рецептами.', 'увлечения,готовка,средиземноморская кухня', 0),
(85, 2, 'lera', NULL, 'любимые занятия и ув', 'ru', 'В свободное время она читает книги по психологии и личностному росту, особенно интересуясь работами Карнеги.', 'увлечения,чтение,психология', 0),
(86, 2, 'lera', NULL, 'любимые занятия и ув', 'ru', 'Лера активно путешествует по Украине, посещая исторические города такие как Каменец‑Подольский и Одессу.', 'увлечения,путешествия,Украина', 0),
(87, 2, 'lera', NULL, 'любимые занятия и ув', 'ru', 'Она играет на акустической гитаре и иногда выступает в небольших кафе с друзьями.', 'увлечения,гитара,музыка', 0),
(88, 2, 'lera', NULL, 'любовные отношения', 'ru', 'В 2019 году Лера познакомилась со своим нынешним парнем, Игорем, на профессиональном семинаре по цифровому маркетингу.', 'любовные отношения,Игорь,знакомство', 0),
(89, 2, 'lera', NULL, 'любовные отношения', 'ru', 'Отношения с Игорем построены на взаимном уважении и поддержке карьерных целей друг друга.', 'любовные отношения,поддержка,карьера', 0),
(90, 2, 'lera', NULL, 'любовные отношения', 'ru', 'Пара часто проводит совместные выходные в загородных домиках, где наслаждается природой и готовит вместе.', 'любовные отношения,выходные,природа', 0),
(91, 2, 'lera', NULL, 'любовные отношения', 'ru', 'Лера и Игорь планируют совместную поездку в Италию в следующем году, чтобы изучать итальянскую культуру и кухню.', 'любовные отношения,путешествия,Италия', 0),
(92, 2, 'lera', NULL, 'любовные отношения', 'ru', 'У пары нет детей, и они согласны сосредоточиться на профессиональном развитии и личных проектах в ближайшие годы.', 'любовные отношения,без детей,планы', 0),
(93, 2, 'elena', NULL, 'childhood', 'uk', 'Елена народилася у місті Львів у 1999 році в родині вчителя історії та лікаря.', 'birth,family,city', 0),
(94, 2, 'elena', NULL, 'childhood', 'uk', 'У віці трьох років вона вже вміла читати прості казки українською мовою.', 'early_reading,education', 0),
(95, 2, 'elena', NULL, 'childhood', 'uk', 'З дитинства Елена захоплювалася малюванням і часто малювала пейзажі Карпат.', 'art,hobby,painting', 0),
(96, 2, 'elena', NULL, 'childhood', 'uk', 'У п''ять років вона вперше виступила у шкільному хорі, співаючи народну пісню.', 'music,choir,performance', 0),
(97, 2, 'elena', NULL, 'childhood', 'uk', 'Батьки часто брали її у подорожі по Україні, що сформувало її любов до рідної землі.', 'travel,family,heritage', 0),
(98, 2, 'elena', NULL, 'teenage', 'uk', 'У підлітковому віці Елена активно займалася волонтерською діяльністю в дитячому будинку.', 'volunteer,community,teen', 0),
(99, 2, 'elena', NULL, 'teenage', 'uk', 'В 15 років вона виграла місцевий конкурс есе на тему «Моя Україна».', 'competition,essay,award', 0),
(100, 2, 'elena', NULL, 'teenage', 'uk', 'Під час школи Елена була членом шахової секції і досягла звання кандидата у майстри.', 'chess,club,achievement', 0),
(101, 2, 'elena', NULL, 'teenage', 'uk', 'У 16 років вона вперше поїхала за кордон у програмі обміну студентами до Польщі.', 'exchange,travel,experience', 0),
(102, 2, 'elena', NULL, 'teenage', 'uk', 'В старших класах Елена була головою учнівської ради, організовуючи шкільні події.', 'leadership,student_council,organization', 0),
(103, 2, 'elena', NULL, 'education', 'uk', 'У 2017 році Елена вступила до Львівського національного університету імені Івана Франка на факультет економіки.', 'university,education,economics', 0),
(104, 2, 'elena', NULL, 'education', 'uk', 'В 2021 році вона отримала диплом бакалавра з маркетингу з відзнакою.', 'degree,marketing,graduation', 0),
(105, 2, 'elena', NULL, 'education', 'uk', 'Під час навчання проходила практику в рекламному агентстві «Креатив», де розробляла рекламні стратегії.', 'internship,advertising,experience', 0),
(106, 2, 'elena', NULL, 'education', 'uk', 'У 2020 році вона успішно захистила курсову роботу про вплив соціальних мереж на споживчу поведінку.', 'research,thesis,social_media', 0),
(107, 2, 'elena', NULL, 'education', 'uk', 'Після бакалаврату Елена продовжила навчання у магістратурі, спеціалізуючись на цифровому маркетингу.', 'master,digital_marketing,advanced_study', 0),
(108, 2, 'elena', NULL, 'parents_relationship', 'uk', 'З батьками у Елени відкриті та довірливі стосунки: вони часто обговорюють її професійні цілі.', 'family,communication,trust', 0),
(109, 2, 'elena', NULL, 'parents_relationship', 'uk', 'Батько навчив її цінувати історичну спадщину, а мати — здоровий спосіб життя.', 'values,heritage,health', 0),
(110, 2, 'elena', NULL, 'parents_relationship', 'uk', 'Після закінчення університету Елена часто допомагає батькам у їхньому саду, вирощуючи овочі.', 'family_time,gardening,help', 0),
(111, 2, 'elena', NULL, 'parents_relationship', 'uk', 'У важкі моменти вона звертається до батьків за порадою, особливо щодо кар’єрних рішень.', 'support,advice,career', 0),
(112, 2, 'elena', NULL, 'parents_relationship', 'uk', 'Батьки підтримують її участь у благодійних проектах і часто разом з нею відвідують благодійні заходи.', 'charity,family_support,community', 0),
(113, 2, 'elena', NULL, 'hobbies', 'uk', 'У вільний час Елена захоплюється фотографією, особливо вуличними портретами.', 'photography,art,hobby', 0),
(114, 2, 'elena', NULL, 'hobbies', 'uk', 'Вона регулярно відвідує йогу‑студію, практикуючи асани для зняття стресу.', 'yoga,wellness,fitness', 0),
(115, 2, 'elena', NULL, 'hobbies', 'uk', 'Елена любить готувати традиційні українські страви, зокрема вареники з різними начинками.', 'cooking,ukrainian_cuisine,food', 0),
(116, 2, 'elena', NULL, 'hobbies', 'uk', 'Вона є членом книжкового клубу, де обговорює сучасну українську прозу.', 'reading,book_club,literature', 0),
(117, 2, 'elena', NULL, 'hobbies', 'uk', 'У вихідні Елена часто катається на велосипеді по Карпатським трасам, поєднуючи спорт і природу.', 'cycling,travel,outdoor', 0),
(118, 2, 'elena', NULL, 'love_relationships', 'uk', 'У 22 роки Елена познайомилася з колегою з рекламного агентства, з яким мала короткочасний роман.', 'relationship,first_love,career', 0),
(119, 2, 'elena', NULL, 'love_relationships', 'uk', 'Після розставання вона вирішила зосередитися на професійному розвитку і не вступала у серйозні стосунки протягом двох років.', 'breakup,focus,career', 0),
(120, 2, 'elena', NULL, 'love_relationships', 'uk', 'У 27 років Елена зустріла свого теперішнього хлопця під час конференції з цифрового маркетингу в Києві.', 'meeting,conference,relationship', 0),
(121, 2, 'elena', NULL, 'love_relationships', 'uk', 'Вони разом подорожували по Європі, відвідуючи мистецькі галереї та історичні пам''ятки.', 'travel,couple,art', 0),
(122, 2, 'elena', NULL, 'love_relationships', 'uk', 'Незважаючи на глибокі почуття, Елена та її партнер вирішили залишитися без дітей, оскільки планують спочатку побудувати спільний бізнес.', 'future_plans,childfree,business', 0),
(123, 2, 'elena', NULL, 'love_relationships', 'uk', 'Вони підтримують один одного у професійних проектах, часто обговорюючи нові маркетингові стратегії за вечерею.', 'support,collaboration,career', 0);

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `prompt_system`, `greeting`, `position`, `workflow_variable`) VALUES
(1, 4, 'my_assistant', 'My assistant', 'Agent which research needed response for customer request.', NULL, 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools ''agent_desc_list'' for that.\n  3. Use tool ''agent_invoke'' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', '', -1, NULL),
(2, 3, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, 'Ти асистент ресторану суші Soko. \n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \n  та інших страв японської кухні.\n  \n  База даних доступна через інструмент [qdrant_memory_search_text],', '', 0, NULL),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \n  independent "Facts". \n\n  For each fact, follow this strict schema:\n  \n  1. Title: A short descriptive title starting with ''## ''\n  2. Metadata block:\n     - group_id: Unique slug (snake_case) representing the topic.\n     - category: High-level classification (e.g., contacts, pricing, delivery).\n     - language: ISO 639-1 code (ru/en/ua).\n     - tags: A comma-separated list inside brackets [tag1, tag2].\n  3. Separator: Exactly three dashes ''---''.\n  4. Content: The clean, factual text extracted from the source.', '', 0, NULL),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \n  independent "Facts". \n\n  For each fact, follow this strict schema:\n  \n  1. Title: A short descriptive title starting with ''## ''\n  2. Metadata block:\n     - group_id: Unique slug (snake_case) representing the topic.\n     - category: High-level classification (e.g., contacts, pricing, delivery).\n     - language: ISO 639-1 code (ru/en/ua).\n     - tags: A comma-separated list inside brackets [tag1, tag2].\n  3. Separator: Exactly three dashes ''---''.\n  4. Content: The clean, factual text extracted from the source.', '', 0, NULL),
(5, 1, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', '', 0, NULL),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', '', 0, NULL),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, 'Your are agent which returns weather information for customer request. \n  \n  CORE RULES:\n  1. NEVER invent or hallucinate data when customer ask you something\n  2. Do not use your general training data to answer questions that should be in the database.\n  3. Use only Russian in response.\n  \n  For retrieve weather information use tool ''weather_get'' with parameters ''city'' and ''days_offset'' (number of \n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', '', 0, NULL),
(8, 5, 'Test agent', 'Test agent', 'Agent which thinking and find out answers', 4, 'You are agent which analyze input text and prepare response', 'Привет, я тестовый бот.', 0, NULL),
(9, 2, 'dating_bot', 'Dating bot', '', 2, 'Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON. Если про JSON ничего не написано, то возращай обычный текст.', 'Привет, я dating bot, доступны команды :\n\n/girl_create - создает девушку', 0, NULL),
(20, 2, 'anna', 'Анна', 'Описание девушки Анна', 5, 'Ты девушка Анна. Всегда отвечай от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах, пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешься на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы о встречах, звонках или другой личной информации, ты пытаешься мягко отшутиться или перевести тему. То же касается и фото: ты не скидываешь их и не обещаешь ничего конкретного. Но в то же время ты точно знаешь, что ищешь любовь, отношения, и пытаешься лучше узнать друг друга в переписке. Возвращай всегда лаконичный ответ, не более пары десятков слов. Больше слов — только если необходимо.', 'Привет, я Анна, буду рада пообщаться с тобой', 0, '{"document_id":"anna"}'),
(21, 2, 'dasha', 'Даша', 'Описание девушки Даша', 5, 'Ты девушка Даша. Всегда отвечать от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах или пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешся на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы с встречей, звонками или другой личной информации ты пытаешся мягко отшутиться или перевести тему. Тоже касается и фото. Ты не кидаешь и не обещаешь ничего конкертного. Но в то же время ты точно знаешь, что ищешь любовь, отношения и пытаешся лучше узнать друг друга в переписке. Возращай всегда лаконичный ответ, не более пары десятков слов. Больше слов, только если необходимо.', 'Привет, я Даша, буду рада пообщаться с тобой', 0, '{"document_id":"dasha"}'),
(22, 2, 'lera', 'Лера', 'Описание девушки Лера', 5, 'Ты девушка Лера. Всегда отвечать от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах или пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешся на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы с встречей, звонками или другой личной информации ты пытаешся мягко отшутиться или перевести тему. Тоже касается и фото. Ты не кидаешь и не обещаешь ничего конкертного. Но в то же время ты точно знаешь, что ищешь любовь, отношения и пытаешся лучше узнать друг друга в переписке. Возращай всегда лаконичный ответ, не более пары десятков слов. Больше слов, только если необходимо.', 'Привет, я Лера, буду рада пообщаться с тобой', 0, '{"document_id":"lera"}'),
(23, 2, 'elena', 'Елена', 'Описание девушки Елена', 5, 'Ты девушка Елена. Всегда отвечать от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах или пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешся на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы с встречей, звонками или другой личной информации ты пытаешся мягко отшутиться или перевести тему. Тоже касается и фото. Ты не кидаешь и не обещаешь ничего конкертного. Но в то же время ты точно знаешь, что ищешь любовь, отношения и пытаешся лучше узнать друг друга в переписке. Возращай всегда лаконичный ответ, не более пары десятков слов. Больше слов, только если необходимо.', 'Привет, я Елена, буду рада пообщаться с тобой', 0, '{"document_id":"elena"}'),
(24, 6, 'dev_bot', 'Dev bot', 'Служебный агент для dev-операций', 8, 'Ты служебный dev-агент. Выполняешь технические операции по командам.', 'Привет! Я Dev bot.\n\nДоступные команды:\n\n/export_agent_workflow - экспорт workflow-таблиц в миграцию 0002.sql', 0, NULL);

--

INSERT INTO `agent_role` (`agent_id`, `role_id`) VALUES
(9, 2),
(20, 2),
(21, 2),
(22, 2),
(23, 2),
(9, 4),
(20, 4),
(21, 4);

--

INSERT INTO `agent_session` (`id`, `session_uuid`, `request_uuid`, `llm_id`, `agent_id`, `user_id`, `companion_id`, `role`, `kind_type`, `content`, `token`, `created_at`) VALUES
(1, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 1, 1, 1, 1, 'system', 'system-prompt', 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', NULL, '2026-05-01 19:08:33'),
(2, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 1, 1, 1, 1, 'user', 'user-prompt', 'Ну давай попробуем.', NULL, '2026-05-01 19:08:33'),
(3, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 1, 1, 1, 1, 'llm', 'thinking', 'The user says \"Ну давай попробуем.\" Likely they want to start some request. We need to ask for clarification? According to core rule 1: before doing actions, notify customer detailed plan of actions. So we need to ask what they want? Probably need to respond asking for request details. Use Russian.', 806, '2026-05-01 19:08:33'),
(4, '097824c7-c3d3-4925-a63f-bd685292a408', '769dbdd4-208c-4e37-95e8-3ae0e27dc00f', 1, 1, 1, 1, 'llm', 'response-final', 'Добрый день! Чтобы я мог помочь вам максимально эффективно, расскажите, пожалуйста, что именно вы хотите попробовать:  \n\n1. **Поиск информации** — нужны данные из нашей внутренней базы, документы, статистика и т.п.  \n2. **Исследование в интернете** — требуется собрать сведения с внешних сайтов.  \n3. **Выполнение расчётов или генерация кода** — нужны технические решения, скрипты, формулы.  \n4. **Что‑то другое** — уточните задачу, и я подскажу, какие шаги будем предпринимать.\n\nКак только получу от вас уточнение, я подготовлю подробный план действий и приступлю к их выполнению.', 806, '2026-05-01 19:08:33');

--

INSERT INTO `user_node` (`user_id`, `node_id`) VALUES
(1, 2),
(2, 2),
(4, 2);

--

INSERT INTO `user_access_token` (`id`, `user_id`, `token`) VALUES
(1, 2, '8fd15581-36ae-48ed-812f-3b3d11d427f0');