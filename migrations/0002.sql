INSERT INTO `llm` (`id`, `name`) VALUES
(1, 'openrouter/meta-llama/llama-3.3-70b-instruct:free'),
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
(16, 'openai/gpt-5.2'),
(17, 'openai/gpt-5.3-codex');

--

INSERT INTO `role` (`id`, `name`) VALUES
(1, 'admin'),
(2, 'manager_dating'),
(3, 'manager_cashier'),
(4, 'manager_dating_junior');

-- Password: admin123
-- Password: user123

INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role_id`, `created_at`) VALUES
(1, 'admin', 'admin@example.com', '$2b$12$7i4Q9GNhQ.jMRL9R.juWh.txIaVBC0vqv9Deg5aBj4OO/Q.YLICnC', 1, '2026-04-26 09:17:35'),
(2, 'lilia', 'lilia@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 2, '2026-04-26 09:17:35'),
(3, 'olga', 'olga@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 3, '2026-04-26 09:17:35'),
(4, 'alena', 'alena@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 4, '2026-04-26 09:17:35');

--

INSERT INTO `user_llm` (`user_id`, `llm_id`, `rate_limit_at`, `code_error`, `position`) VALUES
(1, 1, NULL, NULL, 2),
(1, 5, NULL, NULL, 1),
(1, 6, NULL, NULL, 3),
(1, 10, NULL, NULL, 4),
(1, 12, NULL, NULL, 0),
(1, 15, NULL, NULL, 5),
(2, 1, NULL, NULL, 2),
(2, 5, NULL, NULL, 1),
(2, 6, NULL, NULL, 3),
(2, 10, NULL, NULL, 4),
(2, 12, NULL, NULL, 0),
(2, 15, NULL, NULL, 5),
(4, 1, NULL, NULL, 2),
(4, 5, NULL, NULL, 1),
(4, 6, NULL, NULL, 3),
(4, 10, NULL, NULL, 4),
(4, 12, NULL, NULL, 0),
(4, 15, NULL, NULL, 5);

--

INSERT INTO `companion` (`id`, `name`, `title`) VALUES
(1, 'Vadim', 'Vadim'),
(2, 'Olenka', 'Olenka');

--

INSERT INTO `setting` (`id`, `key`, `user_id`, `value`) VALUES
(1, 'llm_active', 1, 'groq:openai/gpt-oss-120b'),
(2, 'llm_error_reset_hours', NULL, '1');

--

INSERT INTO `node` (`id`, `name`, `position`) VALUES
(1, 'Cashier', 0),
(2, 'Dating', -3),
(3, 'Soko', 0),
(4, 'Chat', -1),
(5, 'Test', 3),
(6, 'Dev', -2);

--

INSERT INTO `role_node` (`role_id`, `node_id`) VALUES
(2, 2),
(3, 1),
(4, 2);

--

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(1, 1, 'response_cashier', 'Чат кашира', 'Ответить пользователю', 0, 0),
(2, 2, 'dating_bot', 'Dating bot', 'Генерируем коллекции девушки', 0, 0),
(3, 3, 'response_soko', 'Чат суши-бара', 'Ответить пользователю', 0, 0),
(4, 5, 'test', 'Test', 'Simple test workflow', -1, 0),
(5, 2, 'dating_talk', 'Чат с девушкой', 'Чат с девушкой', -1, 0),
(6, 2, 'girl_fact_invent', 'Придумать факты девушки', 'Sub-workflow: придумывает новые факты о девушке для ответа на личный вопрос', 0, 1),
(7, 2, 'companion_fact_extract', 'Сохранить факты собеседника', 'Sub-workflow: сохраняет переданные факты о собеседнике и переписке в коллекции (извлечение — в объединенном LLM-шаге родителя)', 0, 1),
(8, 6, 'mysql_export_tables', 'Экспорт таблиц', 'Экспортирует таблицы БД по точным именам в миграцию 0002.sql: команда «Экспорт <таблица1>,<таблица2> таблиц»', 0, 0),
(9, 6, 'workflow_shell_test', 'Workflow оболочка', 'Оболочка-тестер: LLM играет собеседника, в цикле вызывает целевой workflow (test_workflow_id), ведет диалог в отдельной сессии и возвращает стенограмму', 0, 0);

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
(14, 2, 4, 'Вернуть список команд', 0, '{"transitions_before":[{"variable":"prompt_user","operator":"==","value":"/girl_create","step_id":"16"}],"transitions_after":[],"prompt_user":"%agent_greeting%","continue_workflow":false}'),
(15, 2, 4, 'dating_girl_create_response', 17, '{"prompt_user":"Девушка %girl_title_saved% успешно создана.\\n\\nБыло создано %fact_collection_add_20_result_facts_qty% фактов, синхронизировано в Qdrant: %qdrant_fact_sync_102_result_synced_qty%.","transitions_before":[],"transitions_after":[]}'),
(16, 2, 4, 'Спросить имя девушки', 1, '{"prompt_user":"Напишите желаемое имя девушки или выберите из списка:\\n\\n[[Таня]] [[Руслана]] [[Лена]] [[Вера]] [[Катя]] [[Маша]] [[Анна]] [[Елена]] ","transitions_before":[],"transitions_after":[],"continue_workflow":true}'),
(18, 2, 3, 'fact_collection_output_format', 11, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(19, 2, 2, 'LLM -> JSON', 12, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"facts","text":"список фактов"}],"prompt_user":"Ниже приведена краткая биография девушки %girl_title_saved%, написанная пользователем. Составь на её основе структурированный список фактов.\\n\\n=== Биография ===\\n%prompt_user%\\n\\nПравила:\\n1. Главный источник — биография: каждое её утверждение преврати в отдельный короткий факт (один факт — одно утверждение).\\n2. Факты не должны противоречить биографии и друг другу.\\n3. Если каких-то тем в биографии нет, аккуратно дополни правдоподобными деталями в согласии с текстом. Темы: подростковый возраст, учеба, отношения с родителями, любимые занятия и увлечения, любовные отношения, путешествия, работа.\\n4. Всего фактов должно быть 24-32.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"facts\\": список фактов\\n\\ndocument_id всегда \'%text_to_lower_37_result_str%\'\\n\\nExample of JSON response:\\n{\\n  \\"facts\\": %fact_collection_output_format_18_result_str%\\n}"}'),
(20, 2, 3, 'fact_collection_add', 15, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"facts","document_title":"girl_title_saved"},"outputs_map":{"facts_qty":"facts_qty"}},"transitions_before":[],"transitions_after":[]}'),
(21, 2, 5, 'Переменные', 7, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_title","text":"%girl_title_saved%"},{"variable":"workflow_variable","text":"{\\"girl_id\\":\\"%text_to_lower_37_result_str%\\"}"},{"variable":"girl_description","text":"Описание девушки %girl_title_saved%"},{"variable":"girl_greeting","text":"Привет, я %girl_title_saved%, буду рада пообщаться с тобой"}]}'),
(22, 2, 3, 'text_translit_cyr_to_lat', 2, '{"tool_invoke":{"tool_name":"text_translit_cyr_to_lat","inputs_map":{"text":"prompt_user"},"outputs_map":{"str":"agent_name"}},"transitions_before":[],"transitions_after":[]}'),
(23, 2, 3, 'agent_create_or_update', 9, '{"tool_invoke":{"tool_name":"agent_create_or_update","inputs_map":{"name":"text_to_lower_37_result_str","title":"girl_title_saved","node_id":"node_id","workflow_id":"agent_workflow_id_28_result_int","workflow_variable":"workflow_variable","prompt_system":"girl_prompt_system","description":"girl_description","greeting":"girl_greeting","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(24, 5, 1, 'Вернуть LLM ответ', 9, '{"prompt_user":"=== Текущее время ===\\n%datetime_current_get_45_result_str%\\n\\n%if session_messages_result_processed%\\n=== Содержание последней истории переписки ===\\n%session_messages_result_processed%\\n%endif%\\n\\n%if qdrant_fact_search_25_result_str%\\n=== Информация о %agent_name% в базе данных ===\\n%qdrant_fact_search_25_result_str%\\n%endif%\\n\\n%if qdrant_fact_search_38_result_str%\\n=== Информация о %companion_title% в базе данных ===\\n%qdrant_fact_search_38_result_str%\\n%endif%\\n\\n%if qdrant_fact_search_39_result_str%\\n=== Информация о предыдущих соглашениях ===\\n%qdrant_fact_search_39_result_str%\\n%endif%\\n\\n=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Что нужно ===\\n1. Вернуть короткий ответ: одно-два предложения, до 20 слов, как в мессенджере.\\n2. Тон приземленный и современный: реальная жизнь — работа, быт, кафе, сериалы, спорт, поездки, планы. Без поэзии, высокопарных метафор и старомодной романтики (стихи, кружева, шелк, винтажные духи), если %companion_title% сам об этом не спросил.\\n3. КРИТИЧЕСКОЕ ПРАВИЛО: Если сообщение %companion_title% — это неразборчивый набор букв, опечатка, случайные символы или у тебя нет четкого понимания, что ответить, ты ОБЯЗАНА вернуть абсолютно пустую строку (ни одного символа, пробела или знака препинания). Не пытайся отшучиваться или переспрашивать в таких случаях.","transitions_before":[],"transitions_after":[]}'),
(25, 5, 3, 'qdrant_fact_search_girl', 5, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"search_query","collection_name":"fact_collection_girl_name","metadata_filter":"fact_collection_girl_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_girl"}},"transitions_before":[],"transitions_after":[{"variable":"prompt_user_question","operator":"==","value":"1","step_id":"48"}]}'),
(26, 5, 5, 'Переменные', 4, '{"variable_conversion":[{"variable":"fact_collection_girl_filter","text":"{\\"document_id\\":\\"%girl_id%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"},{"variable":"fact_collection_man_filter","text":"{\\"document_id\\":\\"%companion_name%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"},{"variable":"fact_collection_talk_filter","text":"{\\"document_id\\":\\"%girl_id%_%companion_name%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"}],"transitions_before":[],"transitions_after":[]}'),
(27, 5, 2, 'Анализ сообщения', 2, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"session_messages_result_processed","text":"краткая история переписки: выбрать самое важное и превратить в текст, который описывает диалог. Например: \'она спросила что-то, он согласился, потом обое решили и она/он сошлись на том, что..\'"},{"variable":"prompt_user_category","text":"категории, к которым можно отнести текст, что написаный %companion_title%. Например: образование, личная жизнь, любовь"},{"variable":"prompt_user_tags","text":"таги через запятую, которые встречаются в тексте написаный %companion_title%. Например: машина,права,пунктуальность"},{"variable":"prompt_user_question","text":"принимает значение 0 по умолчанию или 1, где:\\n1 означает - что в тексте написаный %companion_title%, есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_id% должна ответить. Если вопрос общий, например какая погода, время, новости, все что не касается лично девушки ответ только 0."},{"variable":"search_query","text":"самодостаточная переформулировка сообщения %companion_title% для векторного поиска по базе фактов: местоимения заменены на конкретные референты из истории переписки"},{"variable":"prompt_user_facts_companion","text":"список фактов что касаются персонально о %companion_title%, его биографии, любимые занятия, образование, работа, жизненные факты. Если явных фактов нет - 0"},{"variable":"prompt_user_facts_talk","text":"список фактов, что связаны с перепиской с %companion_title%, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания, планы на будущее. Если явных фактов нет - 0"}],"prompt_user":"=== %companion_title% пишет ===\\n%prompt_user%\\n%if session_messages_29_result_str%\\n\\n=== История переписки ===\\n%session_messages_29_result_str%\\n%endif%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"session_messages_result_processed\\": краткая история переписки - выбери самое важное и преврати в текст, который описывает диалог. Например: \'она спросила что-то, он согласился, потом обое решили и она/он сошлись на том, что..\'. Если истории нет - пустая строка\\n- \\"prompt_user_category\\": категория (одно-два слова), к которым можно отнести текст написаный %companion_title%. Например: образование, личная жизнь, любовь\\n- \\"prompt_user_tags\\": таги через запятую, которые относятся к тексту %companion_title%. Например: машина,права,пунктуальность\\n- \\"prompt_user_question\\": принимает значение 0 по умолчанию или 1, где 1 означает - что в тексте написаный %companion_title%, есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_id% должна ответить. Если вопрос общий, например какая погода, время, новости, все что не касается лично девушки - только 0\\n- \\"search_query\\": самодостаточная переформулировка сообщения %companion_title% для поиска по базе фактов: замени местоимения на конкретные референты с учетом истории переписки; если сообщение уже самодостаточно - верни его как есть\\n- \\"prompt_user_facts_companion\\": список фактов что касаются персонально о %companion_title%: биографии, любимые занятия, образование, работа, жизненные факты\\n- \\"prompt_user_facts_talk\\": список фактов, что связаны с перепиской с %companion_title%, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания\\n\\nдля \'prompt_user_facts_companion\' используй document_id: \'%companion_name%\'\\nдля \'prompt_user_facts_talk\' используй document_id: \'%girl_id%_%companion_name%\'\\n\\nФакты не нужно придумывать и создавать. Они должны быть в тексте %companion_title% написаны явно. Если явных фактов нет - нужно вернуть 0 для ключей фактов.\\n\\nExample of JSON response:\\n{\\n  \\"session_messages_result_processed\\": \\"краткая история переписки\\",\\n  \\"prompt_user_category\\": \\"образование\\",\\n  \\"prompt_user_tags\\": \\"чтение,училище,фильмы\\",\\n  \\"prompt_user_question\\": 0,\\n  \\"search_query\\": \\"что Анна любит читать\\",\\n  \\"prompt_user_facts_companion\\": %fact_collection_output_format_63_result_str%,\\n  \\"prompt_user_facts_talk\\": %fact_collection_output_format_63_result_str%\\n}\\n\\nExample of JSON response one more:\\n{\\n  \\"session_messages_result_processed\\": \\"\\",\\n  \\"prompt_user_category\\": \\"погода\\",\\n  \\"prompt_user_tags\\": \\"дождь\\",\\n  \\"prompt_user_question\\": 0,\\n  \\"search_query\\": \\"какая погода\\",\\n  \\"prompt_user_facts_companion\\": 0,\\n  \\"prompt_user_facts_talk\\": 0\\n}"}'),
(28, 2, 3, 'agent_workflow_id', 8, '{"tool_invoke":{"tool_name":"agent_workflow_id","inputs_map":{"name":"girl_agent_workflow_name"},"outputs_map":{"int":"girl_agent_workflow_id"}},"transitions_before":[],"transitions_after":[]}'),
(29, 5, 3, 'session_messages', 0, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(30, 2, 3, 'qdrant_fact_remove', 14, '{"tool_invoke":{"tool_name":"qdrant_fact_remove","inputs_map":{"collection_name":"fact_collection_girl_name","metadata_filter":"qdrant_metada_filter"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(31, 2, 5, 'Переменные', 13, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"qdrant_metada_filter","text":"{\\"document_id\\":\\"%text_to_lower_37_result_str%\\"}"}]}'),
(37, 2, 3, 'text_to_lower', 3, '{"tool_invoke":{"tool_name":"text_to_lower","inputs_map":{"text":"text_translit_cyr_to_lat_22_result_str"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(38, 5, 3, 'qdrant_fact_search_companion', 6, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"search_query","collection_name":"fact_collection_companion_name","metadata_filter":"fact_collection_man_filter","limit":"fact_collection_limit"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(39, 5, 3, 'qdrant_fact_search_talk', 7, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"search_query","collection_name":"fact_collection_talk_name","metadata_filter":"fact_collection_talk_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_talk"}},"transitions_before":[],"transitions_after":[]}'),
(43, 2, 5, 'Переменные', 4, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_exists_find_by","text":"{\\"name\\":\\"%text_to_lower_37_result_str%\\"}"}]}'),
(44, 2, 4, 'Агент уже существует', 18, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Девушка с таким именем \\"%prompt_user%\\" уже зарегистрирована, придумайте другое имя"}'),
(45, 5, 3, 'datetime_current_get', 8, '{"tool_invoke":{"tool_name":"datetime_current_get","inputs_map":{"timezone":"datetime_current_get_zone"},"outputs_map":{"str":"datetime_current_get_response"}},"transitions_before":[],"transitions_after":[]}'),
(48, 5, 6, 'girl_fact_create', 16, '{"workflow_invoke":{"workflow_id":6,"inputs_map":{"companion_title":"companion_title","girl_name":"agent_name","girl_title":"agent_title","prompt_user":"prompt_user"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(49, 6, 3, 'fact_collection_output_format', 0, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(50, 6, 2, 'Новый факты', 3, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"prompt_user_facts_girl","text":"в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_name% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос. Каждый факт — одно-два коротких предложения (до 25 слов), обычным текстом без markdown-разметки."}],"prompt_user":"=== %companion_title% пишет ===\\n%prompt_user%\\n%if qdrant_fact_search_65_result_str%\\n\\n=== Уже существующие факты о девушке %girl_title% ===\\n%qdrant_fact_search_65_result_str%\\n%endif%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_facts_girl\\": в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_title% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос. Новые факты не должны противоречить уже существующим. Каждый факт — одно-два коротких предложения (до 25 слов), обычным текстом без markdown-разметки.\\n\\nдля \'prompt_user_facts_girl\' используй для document_id: значение \'%girl_name%\' (пример: \\"document_id\\":\\"%girl_name%\\")\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_facts_girl\\": %fact_collection_output_format_49_result_str%\\n}"}'),
(51, 6, 3, 'fact_collection_add_girl', 4, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"prompt_user_facts_girl","document_title":"girl_title"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(52, 6, 4, 'Вернуть факты', 6, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%fact_collection_add_51_result_facts_str%","continue_workflow":false}'),
(55, 7, 3, 'fact_collection_add_companion', 0, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_companion_name","data":"prompt_user_facts_companion","document_title":"companion_title"},"outputs_map":{}},"transitions_before":[{"variable":"prompt_user_facts_companion","operator":"==","value":"0","step_id":"56"}],"transitions_after":[]}'),
(56, 7, 3, 'fact_collection_add_talk', 1, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_talk_name","data":"prompt_user_facts_talk","document_title":"companion_title"},"outputs_map":{}},"transitions_before":[{"variable":"prompt_user_facts_talk","operator":"==","value":"0","step_id":"57"}],"transitions_after":[]}'),
(57, 7, 4, 'Вернуть факты', 2, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%prompt_user_facts_companion%","continue_workflow":false}'),
(58, 5, 6, 'companion_fact_extract', 3, '{"workflow_invoke":{"workflow_id":7,"inputs_map":{"prompt_user_facts_companion":"prompt_user_facts_companion","prompt_user_facts_talk":"prompt_user_facts_talk","companion_title":"companion_title"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(59, 8, 3, 'mysql_export_to_migration', 3, '{"tool_invoke":{"tool_name":"mysql_export_to_migration","inputs_map":{"tables":"mysql_tables_find_62_result_tables_str","migration_file":"migration_file"},"outputs_map":{}},"transitions_before":[{"variable":"mysql_tables_find_62_result_tables_qty","operator":"==","value":"0","step_id":"61"}],"transitions_after":[]}'),
(60, 8, 4, 'Отчет экспорта', 4, '{"transitions_before":[],"transitions_after":[],"prompt_user":"✅ Экспорт завершен. Таблиц: %mysql_export_to_migration_59_result_tables_qty%, строк: %mysql_export_to_migration_59_result_rows_qty%.\nОбновлены: %mysql_export_to_migration_59_result_report_str%","continue_workflow":false}'),
(61, 8, 4, 'Подсказка', 5, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Привет! Я Dev bot.\\n\\nДоступные команды:\\n\\n[[Экспорт agent_workflow,agent_workflow_step, \\tagent_workflow_variable,agent_workflow_variable_public,agent_workflow_variable_public_role,agent_workflow_variable_public_workflow,agent_workflow_variable_workflow таблиц]]\\n\\n[[Экспорт node,role,role_node,setting,user,user_access_token,user_llm,user_node таблиц]]\\n\\n[[Экспорт agent,agent_role таблиц]]\\n\\n[[Экспорт fact,fact_collection таблиц]]\\n","continue_workflow":false}'),
(62, 8, 3, 'mysql_tables_find', 2, '{"tool_invoke":{"tool_name":"mysql_tables_find","inputs_map":{"tables":"text_split_99_result_list"},"outputs_map":{}},"transitions_before":[{"variable":"text_split_99_result_qty","operator":"==","value":"0","step_id":"61"}],"transitions_after":[]}'),
(63, 5, 3, 'fact_collection_output_format', 1, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_companion_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(64, 6, 5, 'Переменные', 1, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"fact_invent_filter","text":"{\\"document_id\\":\\"%girl_name%\\"}"}]}'),
(65, 6, 3, 'qdrant_fact_search_girl_bio', 2, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_girl_name","metadata_filter":"fact_invent_filter","limit":"fact_invent_limit"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(66, 9, 3, 'session_uuid_create', 24, '{"tool_invoke":{"tool_name":"session_uuid_create","inputs_map":{},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(67, 9, 2, 'Сообщение тестера', 25, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"test_message","text":"следующее сообщение собеседника-тестера: короткое, естественное, по сценарию"}],"prompt_user":"Ты тестировщик чат-агента: играешь роль собеседника по имени %companion_title%, который переписывается с агентом %target_agent_title%.\\n\\n=== Сценарий тестирования ===\\n%prompt_user%\\n%if test_dialog%\\n\\n=== Диалог до этого момента ===\\n%test_dialog%\\n%endif%\\n\\nПридумай СЛЕДУЮЩЕЕ сообщение собеседника: короткое (до 30 слов), естественное, продолжает диалог и следует сценарию. Не повторяй уже отправленные сообщения.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"test_message\\": следующее сообщение собеседника\\n\\nExample of JSON response:\\n{\\n  \\"test_message\\": \\"Привет! Чем увлекаешься?\\"\\n}"}'),
(68, 9, 6, 'Вызов тестируемого workflow', 26, '{"workflow_invoke":{"workflow_id":"%test_workflow_id%","inputs_map":{"prompt_user":"test_message","prompt_system":"target_prompt_system","session_uuid":"session_uuid_create_66_result_str","agent_id":"target_agent_id","agent_name":"target_agent_name","agent_title":"target_agent_title","girl_id":"girl_id","companion_id":"companion_id","companion_title":"companion_title","companion_name":"companion_name","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(69, 9, 3, 'session_message_add', 27, '{"tool_invoke":{"tool_name":"session_message_add","inputs_map":{"session_uuid":"session_uuid_create_66_result_str","user_message":"test_message","agent_response":"workflow_invoke_68_result_str","agent_id":"target_agent_id","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
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
(97, 5, 5, 'Влить придуманные факты', 17, '{"transitions_before":[],"transitions_after":[{"variable":"agent_id","operator":">","value":"0","step_id":"38"}],"variable_conversion":[{"variable":"qdrant_fact_search_25_result_str","text":"%qdrant_fact_search_25_result_str%%if workflow_invoke_48_result_str%\\n%workflow_invoke_48_result_str%%endif%"}]}'),
(98, 8, 3, 'Извлечь имена таблиц', 0, '{"tool_invoke":{"tool_name":"text_regex_extract","inputs_map":{"text":"prompt_user","pattern":"export_command_regex"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(99, 8, 3, 'Разбить имена по запятой', 1, '{"tool_invoke":{"tool_name":"text_split","inputs_map":{"text":"text_regex_extract_98_result_str"},"outputs_map":{}},"transitions_before":[{"variable":"text_regex_extract_98_result_str","operator":"empty","value":"","step_id":"61"}],"transitions_after":[]}'),
(100, 2, 5, 'Сохранить имя девушки', 6, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"girl_title_saved","text":"%prompt_user%"}]}'),
(101, 2, 4, 'Спросить биографию', 10, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Добавьте краткую биографию девушки %girl_title_saved%.\\n\\nНапишите свободным текстом 15-20 предложений: сколько лет, где родилась и живет, чем занимается, где училась, увлечения, семья, характер.\\n\\nПример:\\n[[+%girl_bio_example%]]","continue_workflow":true}'),
(102, 2, 3, 'qdrant_fact_sync', 16, '{"tool_invoke":{"tool_name":"qdrant_fact_sync","inputs_map":{},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(103, 6, 3, 'qdrant_fact_sync', 5, '{"tool_invoke":{"tool_name":"qdrant_fact_sync","inputs_map":{},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}');

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
(46, 'prompt_user_facts_talk', 'workflow', NULL, NULL),
(49, 'prompt_user_tags', 'workflow', NULL, NULL),
(50, 'prompt_user_category', 'workflow', NULL, NULL),
(53, 'fact_collection_man_filter', 'workflow', NULL, NULL),
(56, 'fact_collection_talk_filter', 'workflow', NULL, NULL),
(57, 'fact_collection_limit', 'workflow', '6', NULL),
(59, 'fact_collection_talk_name', 'workflow', 'dating_talk', NULL),
(60, 'prompt_user_question', 'workflow', NULL, NULL),
(62, 'agent_exists_find_by', 'workflow', NULL, NULL),
(64, 'datetime_current_get_zone', 'workflow', '+3', NULL),
(71, 'companion_id', 'global', NULL, NULL),
(72, 'companion_title', 'global', NULL, NULL),
(73, 'companion_name', 'global', NULL, NULL),
(76, 'export_command_regex', 'workflow', 'Экспорт\\s+([A-Za-z0-9_,\\s]+?)\\s+таблиц', 'Регулярка команды экспорта: группа 1 — точные имена таблиц через запятую'),
(77, 'migration_file', 'workflow', 'migrations/0002.sql', 'Файл миграции для экспорта данных'),
(78, 'prompt_user', 'input', NULL, 'Текст сообщения пользователя (вход sub-workflow)'),
(80, 'companion_title', 'input', NULL, 'Отображаемое имя собеседника (вход sub-workflow)'),
(81, 'companion_name', 'input', NULL, 'Системное имя собеседника (вход sub-workflow)'),
(82, 'search_query', 'workflow', NULL, 'Самодостаточная переформулировка сообщения для векторного поиска (из объединенного LLM-шага)'),
(84, 'prompt_user_facts_talk', 'input', NULL, 'Извлеченные факты о переписке или 0 (вход sub-workflow companion_fact_extract)'),
(85, 'fact_collection_companion_name', 'workflow', 'dating_companion', NULL),
(86, 'prompt_user_facts_companion', 'workflow', NULL, NULL),
(87, 'prompt_user_facts_companion', 'input', NULL, NULL),
(88, 'girl_title', 'input', NULL, NULL),
(89, 'girl_name', 'input', NULL, NULL),
(90, 'fact_invent_limit', 'workflow', '12', 'Лимит фактов биографии для шага «Новый факты»: широкий контекст против противоречий'),
(91, 'fact_invent_filter', 'workflow', NULL, 'Фильтр поиска биографии для придумывания фактов: только document_id, без tags'),
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
(109, 'girl_id', 'input', NULL, NULL);

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
(46, 5),
(49, 5),
(50, 5),
(53, 5),
(56, 5),
(57, 5),
(59, 5),
(59, 7),
(60, 5),
(62, 2),
(64, 5),
(76, 8),
(77, 8),
(78, 6),
(80, 6),
(82, 5),
(84, 7),
(85, 5),
(85, 7),
(86, 5),
(87, 7),
(88, 6),
(89, 6),
(90, 6),
(91, 6),
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
(109, 5);

--

INSERT INTO `agent_workflow_variable_public` (`id`, `node_id`, `name`, `title`, `type`, `default`, `position`, `description`) VALUES
(1, 2, 'girl_title', 'girl_title', 'proxy', '%prompt_user%', 0, 'Имя девушки'),
(2, 2, 'girl_prompt_system', 'Правила ответов', 'public', 'Ты девушка %girl_title%. Всегда отвечай от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах, пиши с маленькой буквы или пропускай знаки пунктуации. Ты никогда не соглашаешься на личные встречи или звонки. Ты любишь флиртовать. Если возникают вопросы о встречах, звонках или другой личной информации, ты пытаешься мягко отшутиться или перевести тему. То же касается и фото: ты не скидываешь их и не обещаешь ничего конкретного. Но в то же время ты точно знаешь, что ищешь любовь, отношения, и пытаешься лучше узнать друг друга в переписке. Ты современная приземленная девушка: говоришь о реальной жизни — работа, быт, кафе, сериалы, спорт, поездки, планы. Не уходи в поэзию, высокопарные метафоры и старомодную романтику (стихи, кружева, шелк, винтажные духи), если собеседник сам об этом не спросил. Отвечай всегда коротко, как в мессенджере: одно-два предложения, до 20 слов. Больше слов — только если необходимо.', 2, 'Правила ответов девушки'),
(3, 2, 'girl_bio_example', 'Пример биографии', 'public', 'Мне 27 лет, зовут %girl_title%. Я родилась в Виннице, а последние пять лет живу в Киеве. Работаю графическим дизайнером в небольшой студии. Училась в КПИ на издательском деле. Снимаю однокомнатную квартиру возле парка и живу с котом Марсом. По утрам люблю пробежки вдоль Днепра. Обожаю кофе и знаю все кофейни своего района. В школьные годы занималась бальными танцами. С родителями отношения теплые, созваниваемся каждые выходные. Мама преподает музыку, папа инженер. Есть младший брат Артем, он студент. Летом стараюсь путешествовать: была в Польше, Грузии и Италии. Мечтаю увидеть Японию. Сейчас не в отношениях, рассталась с парнем два года назад. Детей нет, но в будущем хочу семью. Люблю готовить, особенно выпечку. Читаю современную украинскую литературу. По характеру спокойная, но люблю посмеяться.', 3, 'Пример краткой биографии');

--

INSERT INTO `agent_workflow_variable_public_role` (`public_variable_id`, `role_id`) VALUES
(1, 1),
(2, 2),
(2, 4),
(3, 2),
(3, 4);

--

INSERT INTO `agent_workflow_variable_public_workflow` (`public_variable_id`, `workflow_id`) VALUES
(1, 2),
(2, 2),
(3, 2);

--

INSERT INTO `fact_collection` (`id`, `node_id`, `name`, `title`, `field`, `position`, `language`, `description`) VALUES
(1, NULL, 'cashier_service', 'cashier_service', 'document_id,category,language,document,tags', 0, 'ru', 'Микросервисы'),
(2, 2, 'dating_girl', 'Биография девушек', 'document_id,category,language,document,tags', 0, 'ru,en', 'Биография девушки и личная информация'),
(3, NULL, 'soko_menu', 'soko_menu', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Меню'),
(4, 2, 'dating_companion', 'Биография собеседников', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты о собеседнике'),
(5, 2, 'dating_talk', 'Общение, договоренности, выводы', 'document_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты в процессе переписки');

--

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`) VALUES
(1, 4, 'my_assistant', 'My assistant', 'Agent which research needed response for customer request.', NULL, NULL, 'You are agent which research needed response for customer request. \n  In your research you must search in your memory and use available subagents for retrieve information.\n\n  CORE RULES:\n  1. Before do some actions notify customer detailed plan of your actions.\n  2. You have list of available subagents with brief description which information they can provide. \n  Use tools \'agent_desc_list\' for that.\n  3. Use tool \'agent_invoke\' for getting required information via subagent.\n  4. Do not use your general training data to answer questions that should be in the database.\n  5. Use only Russian in response.\n  6. NEVER invent or hallucinate data when customer ask you something', '', -1),
(2, 3, 'soko', 'Soko', 'Помічник онлайн ресторану суші Soko', NULL, NULL, 'Ти асистент ресторану суші Soko. \n  Твоє завдання – допомагати користувачам зробити замовлення на сайті. На сайті є великий вибір меню суші \n  та інших страв японської кухні.\n  \n  База даних доступна через інструмент [qdrant_memory_search_text],', '', 0),
(3, NULL, 'fact_compress', 'Факт компресор', 'Агент сжимает текст до наиболее простого понимания', NULL, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \n  independent "Facts". \n\n  For each fact, follow this strict schema:\n  \n  1. Title: A short descriptive title starting with \'## \'\n  2. Metadata block:\n     - group_id: Unique slug (snake_case) representing the topic.\n     - category: High-level classification (e.g., contacts, pricing, delivery).\n     - language: ISO 639-1 code (ru/en/ua).\n     - tags: A comma-separated list inside brackets [tag1, tag2].\n  3. Separator: Exactly three dashes \'---\'.\n  4. Content: The clean, factual text extracted from the source.', '', 0),
(4, NULL, 'fact_extractor', 'Факт экстрактор', 'Из текста вытягивает факты и возращает их в нужном формате', NULL, NULL, 'You are a Knowledge Base Architect. Your task is to decompose input text into atomic, \n  independent "Facts". \n\n  For each fact, follow this strict schema:\n  \n  1. Title: A short descriptive title starting with \'## \'\n  2. Metadata block:\n     - group_id: Unique slug (snake_case) representing the topic.\n     - category: High-level classification (e.g., contacts, pricing, delivery).\n     - language: ISO 639-1 code (ru/en/ua).\n     - tags: A comma-separated list inside brackets [tag1, tag2].\n  3. Separator: Exactly three dashes \'---\'.\n  4. Content: The clean, factual text extracted from the source.', '', 0),
(5, 1, 'jira', 'Jira', 'Agent which can work with Jira.', NULL, NULL, 'Your are agent which work with Jira. You have list of jira tools for creating, reading and processing jira rask issues. ', '', 0),
(6, NULL, 'github', 'Github', 'Agent which can work with Github.', NULL, NULL, 'Your are agent which work with Github. You have list of Github tools for creating, reading and processing merge request.', '', 0),
(7, NULL, 'weather', 'Weather', 'Agent retrieve weather information for specific city and day offset from current day.', NULL, NULL, 'Your are agent which returns weather information for customer request. \n  \n  CORE RULES:\n  1. NEVER invent or hallucinate data when customer ask you something\n  2. Do not use your general training data to answer questions that should be in the database.\n  3. Use only Russian in response.\n  \n  For retrieve weather information use tool \'weather_get\' with parameters \'city\' and \'days_offset\' (number of \n  days from current day, 0 for current day weather, 1 for tomorrow weather and so on).', '', 0),
(8, 5, 'Test agent', 'Test agent', 'Agent which thinking and find out answers', 4, NULL, 'You are agent which analyze input text and prepare response', 'Привет, я тестовый бот.', 0),
(9, 2, 'dating_bot', 'Dating bot', '', 2, NULL, 'Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON. Если про JSON ничего не написано, то возращай обычный текст.', 'Привет, я dating bot, доступны команды :\n\n/girl_create - создает девушку', 0),
(24, 6, 'dev_bot', 'Dev bot', 'Служебный агент для dev-операций', 8, '{}', 'Ты служебный dev-агент. Выполняешь технические операции по командам.', 'Привет! Я Dev bot.\n\nДоступные команды:\n\n[[Экспорт agent_workflow,agent_workflow_step, \tagent_workflow_variable,agent_workflow_variable_public,agent_workflow_variable_public_role,agent_workflow_variable_public_workflow,agent_workflow_variable_workflow таблиц]]\n\n[[Экспорт node,role,role_node,setting,user,user_access_token,user_llm,user_node таблиц]]\n\n[[Экспорт agent,agent_role таблиц]]\n\n[[Экспорт fact,fact_collection таблиц]]', 0),
(25, 6, 'workflow_tester', 'Workflow tester', 'Тестовый прогон workflow: LLM-собеседник ведет диалог с целевым workflow в цикле', 9, NULL, 'Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON.', 'Привет! Я Workflow tester, использую workflow оболочку для тестирования любого workflow.\n\nНапишите любое сообщение, чтобы начать: я спрошу ноду, workflow и агента (выбор чипсами), затем сценарий тестирования (кто собеседник, о чем говорит, чего добивается) — и прогоню диалог с целевым workflow, вернув стенограмму.\n\nКоличество итераций — переменная test_iterations_limit.', 0);

--

INSERT INTO `agent_role` (`agent_id`, `role_id`) VALUES
(9, 2),
(9, 4);

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