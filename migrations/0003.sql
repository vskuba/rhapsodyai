-- Dating: все данные подпроекта - workflow (dating_bot/dating_talk/sub-flows),
-- их шаги и переменные, публичные переменные, агент dating_bot, привязки ролей.

INSERT INTO `role_node` (`role_id`, `node_id`) VALUES
(2, 2),
(4, 2);

--

INSERT INTO `user_node` (`user_id`, `node_id`) VALUES
(1, 2),
(2, 2),
(4, 2);

--

INSERT INTO `fact_collection` (`id`, `node_id`, `name`, `title`, `field`, `position`, `language`, `description`) VALUES
(2, 2, 'dating_girl', 'Биография девушек', 'document_id,user_id,category,language,document,tags', 0, 'ru,en', 'Биография девушки и личная информация'),
(4, 2, 'dating_companion', 'Биография собеседников', 'document_id,user_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты о собеседнике'),
(5, 2, 'dating_talk', 'Общение, договоренности, выводы', 'document_id,user_id,category,language,document,tags', 0, 'ru,en,ua', 'Факты в процессе переписки');

--

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(2, 2, 'dating_bot', 'Dating bot', 'Генерируем коллекции девушки', 1, 0),
(5, 2, 'dating_talk', 'Чат с девушкой', 'Чат с девушкой', 0, 0),
(6, 2, 'girl_fact_invent', 'Придумать факты девушки', 'Sub-workflow: придумывает новые факты о девушке для ответа на личный вопрос', 0, 1),
(7, 2, 'companion_fact_extract', 'Сохранить факты собеседника', 'Sub-workflow: сохраняет переданные факты о собеседнике и переписке в коллекции (извлечение — в объединенном LLM-шаге родителя)', 0, 1);

--

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(13, 2, 3, 'agent_exists', 5, '{"tool_invoke":{"tool_name":"agent_exists","inputs_map":{"find_by":"agent_exists_find_by"},"outputs_map":{"bool":"agent_exists_find_by_result"}},"transitions_before":[],"transitions_after":[{"variable":"agent_exists_13_result_bool","operator":"==","value":"True","step_id":"44"}]}'),
(14, 2, 4, 'Вернуть список команд', 0, '{"transitions_before":[{"variable":"prompt_user","operator":"==","value":"/girl_create","step_id":"16"},{"variable":"prompt_user","operator":"==","value":"/girl_remove","step_id":"111"}],"transitions_after":[],"prompt_user":"%agent_greeting%","continue_workflow":false}'),
(15, 2, 4, 'dating_girl_create_response', 17, '{"prompt_user":"Девушка %girl_title_saved% успешно создана.\\n\\nБыло создано %fact_collection_add_20_result_facts_qty% фактов, синхронизировано в Qdrant: %qdrant_fact_sync_102_result_synced_qty%.","transitions_before":[],"transitions_after":[]}'),
(16, 2, 4, 'Спросить имя девушки', 1, '{"prompt_user":"Напишите желаемое имя девушки или выберите из списка:\\n\\n[[Таня]] [[Руслана]] [[Лена]] [[Вера]] [[Катя]] [[Маша]] [[Анна]] [[Елена]] ","transitions_before":[],"transitions_after":[],"continue_workflow":true}'),
(18, 2, 3, 'fact_collection_output_format', 11, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{"str":"fact_collection_output_format_response"}},"transitions_before":[],"transitions_after":[]}'),
(19, 2, 2, 'LLM -> JSON', 12, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"facts","text":"список фактов"}],"prompt_user":"Ниже приведена краткая биография девушки %girl_title_saved%, написанная пользователем. Составь на её основе структурированный список фактов.\\n\\n=== Биография ===\\n%prompt_user%\\n\\nПравила:\\n1. Главный источник — биография: каждое её утверждение преврати в отдельный короткий факт (один факт — одно утверждение).\\n2. Факты не должны противоречить биографии и друг другу.\\n3. Если каких-то тем в биографии нет, аккуратно дополни правдоподобными деталями в согласии с текстом. Темы: подростковый возраст, учеба, отношения с родителями, любимые занятия и увлечения, любовные отношения, путешествия, работа.\\n4. Всего фактов должно быть 24-32.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"facts\\": список фактов\\n\\ndocument_id всегда \'%text_to_lower_37_result_str%\'\\n\\nExample of JSON response:\\n{\\n  \\"facts\\": %fact_collection_output_format_18_result_str%\\n}"}'),
(20, 2, 3, 'fact_collection_add', 15, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"facts","document_title":"girl_title_saved","user_id":"user_id"},"outputs_map":{"facts_qty":"facts_qty"}},"transitions_before":[],"transitions_after":[]}'),
(21, 2, 5, 'Переменные', 7, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_title","text":"%girl_title_saved%"},{"variable":"workflow_variable","text":"{\\"girl_id\\":\\"%text_to_lower_37_result_str%\\"}"},{"variable":"girl_description","text":"Описание девушки %girl_title_saved%"},{"variable":"girl_greeting","text":"Привет, я %girl_title_saved%, буду рада пообщаться с тобой"}]}'),
(22, 2, 3, 'text_translit_cyr_to_lat', 2, '{"tool_invoke":{"tool_name":"text_translit_cyr_to_lat","inputs_map":{"text":"prompt_user"},"outputs_map":{"str":"agent_name"}},"transitions_before":[],"transitions_after":[]}'),
(23, 2, 3, 'agent_create_or_update', 9, '{"tool_invoke":{"tool_name":"agent_create_or_update","inputs_map":{"name":"text_to_lower_37_result_str","title":"girl_title_saved","node_id":"node_id","workflow_id":"agent_workflow_id_28_result_int","workflow_variable":"workflow_variable","prompt_system":"girl_prompt_system","description":"girl_description","greeting":"girl_greeting","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(24, 5, 2, 'Генерация ответа', 10, '{"llm_to_json_variable": [{"variable": "girl_response", "text": "ответ девушки собеседнику (пустая строка, если отвечать не нужно)"}], "prompt_user": "=== Текущее время ===\\n%datetime_current_get_45_result_str%\\n\\n%if session_messages_29_result_str%\\n=== История переписки (детально, время сообщений в квадратных скобках) ===\\n%session_messages_29_result_str%\\n%endif%\\n\\n%if session_messages_result_processed%\\n=== Краткая выдержка истории переписки ===\\n%session_messages_result_processed%\\n%endif%\\n\\n%if qdrant_fact_search_25_result_str%\\n=== Информация о %agent_name% в базе данных ===\\n%qdrant_fact_search_25_result_str%\\n%endif%\\n\\n%if qdrant_fact_search_38_result_str%\\n=== Информация о %companion_title% в базе данных ===\\n%qdrant_fact_search_38_result_str%\\n%endif%\\n\\n%if qdrant_fact_search_39_result_str%\\n=== Информация о предыдущих соглашениях ===\\n%qdrant_fact_search_39_result_str%\\n%endif%\\n\\n=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Что нужно ===\\n1. Вернуть короткий ответ: одно-два предложения, до 20 слов, как в мессенджере.\\n2. Тон приземленный и современный: реальная жизнь — работа, быт, кафе, сериалы, спорт, поездки, планы. Без поэзии, высокопарных метафор и старомодной романтики (стихи, кружева, шелк, винтажные духи), если %companion_title% сам об этом не спросил.\\n3. Ответ должен соответствовать текущему времени суток и времени сообщений в истории (в квадратных скобках): не здоровайся и не описывай утренние дела вечером или ночью, и наоборот.\\n4. КРИТИЧЕСКОЕ ПРАВИЛО: Если сообщение %companion_title% — это неразборчивый набор букв, опечатка, случайные символы или у тебя нет четкого понимания, что ответить, ты ОБЯЗАНА вернуть абсолютно пустую строку (ни одного символа, пробела или знака препинания). Не пытайся отшучиваться или переспрашивать в таких случаях.\\n5. Отвечай строго на языке: %user_language%.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"girl_response\\": твой ответ собеседнику; если по правилам выше отвечать не нужно - строго пустая строка\\n\\nExample of JSON response:\\n{\\n  \\"girl_response\\": \\"привет, как прошел день?\\"\\n}\\n\\nExample of JSON response one more:\\n{\\n  \\"girl_response\\": \\"\\"\\n}", "transitions_before": [], "transitions_after": []}'),
(25, 5, 3, 'qdrant_fact_search_girl', 7, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"search_query","collection_name":"fact_collection_girl_name","metadata_filter":"fact_collection_girl_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_girl"}},"transitions_before":[],"transitions_after":[{"variable":"prompt_user_question","operator":"==","value":"1","step_id":"48"}]}'),
(26, 5, 5, 'Переменные', 6, '{"variable_conversion":[{"variable":"fact_collection_girl_filter","text":"{\\"user_id\\":%user_id%,\\"tags\\":\\"%prompt_user_tags%\\"}"},{"variable":"fact_collection_man_filter","text":"{\\"user_id\\":%user_id%,\\"document_id\\":\\"%companion_name%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"},{"variable":"fact_collection_talk_filter","text":"{\\"user_id\\":%user_id%,\\"document_id\\":\\"%girl_id%_%companion_name%\\",\\"tags\\":\\"%prompt_user_tags%\\"}"}],"transitions_before":[],"transitions_after":[]}'),
(27, 5, 2, 'Анализ сообщения', 4, '{"transitions_before":[],"transitions_after":[{"variable":"prompt_user_ignore","operator":"==","value":"1","step_id":"107"}],"llm_to_json_variable":[{"variable":"session_messages_result_processed","text":"краткая выдержка истории переписки: самое важное одним абзацем с привязкой ко времени (вчера вечером обсуждали.., сегодня утром договорились..), опираясь на метки времени сообщений"},{"variable":"prompt_user_category","text":"категории, к которым можно отнести текст, что написаный %companion_title%. Например: образование, личная жизнь, любовь"},{"variable":"prompt_user_tags","text":"таги через запятую, которые встречаются в тексте написаный %companion_title%. Например: машина,права,пунктуальность"},{"variable":"prompt_user_question","text":"принимает значение 0 по умолчанию или 1, где:\\n1 означает - что в тексте написаный %companion_title%, есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_id% должна ответить. Если вопрос общий, например какая погода, время, новости, все что не касается лично девушки ответ только 0."},{"variable":"search_query","text":"самодостаточная переформулировка сообщения %companion_title% для векторного поиска по базе фактов: местоимения заменены на конкретные референты из истории переписки"},{"variable":"prompt_user_facts_companion","text":"список фактов что касаются персонально о %companion_title%, его биографии, любимые занятия, образование, работа, жизненные факты. Если явных фактов нет - 0"},{"variable":"prompt_user_facts_talk","text":"список фактов, что связаны с перепиской с %companion_title%, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания, планы на будущее. Если явных фактов нет - 0"},{"variable":"prompt_user_ignore","text":"принимает значение 0 по умолчанию или 1, где 1 означает - что отвечать не нужно: диалог уже завершен прощанием (девушка попрощалась или написала, что идет спать), а новое сообщение %companion_title% не несет нового содержания - только подтверждение (\'ок\', смайл, повторное \'спокойной ночи\') или повтор его предыдущих сообщений. ВАЖНО: сверяй текущее время со временем сообщений в истории (указано в квадратных скобках). Если после прощания реально прошла ночь и наступило утро нового дня - это новый диалог: отвечать нужно, строго 0, даже на простое \'доброе утро\'. Если же прощание было совсем недавно (минуты назад) и утро еще не наступило, то \'доброе утро\' не соответствует реальности - девушка уже спит и отвечать не нужно, строго 1"}],"prompt_user":"=== Текущее время ===\\n%datetime_current_get_45_result_str%\\n\\n=== %companion_title% пишет ===\\n%prompt_user%\\n%if session_messages_108_result_str%\\n\\n=== История переписки (время сообщений в квадратных скобках) ===\\n%session_messages_108_result_str%\\n%endif%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"session_messages_result_processed\\": краткая выдержка истории переписки - самое важное одним абзацем с привязкой ко времени (вчера вечером обсуждали.., сегодня утром договорились..), опираясь на метки времени сообщений и текущее время. Если истории нет - пустая строка\\n- \\"prompt_user_category\\": категория (одно-два слова), к которым можно отнести текст написаный %companion_title%. Например: образование, личная жизнь, любовь\\n- \\"prompt_user_tags\\": таги через запятую, которые относятся к тексту %companion_title%. Например: машина,права,пунктуальность\\n- \\"prompt_user_question\\": принимает значение 0 по умолчанию или 1, где 1 означает - что в тексте написаный %companion_title%, есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_id% должна ответить. Если вопрос общий, например какая погода, время, новости, все что не касается лично девушки - только 0\\n- \\"search_query\\": самодостаточная переформулировка сообщения %companion_title% для поиска по базе фактов: замени местоимения на конкретные референты с учетом истории переписки; если сообщение уже самодостаточно - верни его как есть\\n- \\"prompt_user_facts_companion\\": список фактов что касаются персонально о %companion_title%: биографии, любимые занятия, образование, работа, жизненные факты\\n- \\"prompt_user_facts_talk\\": список фактов, что связаны с перепиской с %companion_title%, это могут быть какие-то договоронности, споры, дискусии на разные темы, мнения, мысли, желания\\n- \\"prompt_user_ignore\\": принимает значение 0 по умолчанию или 1, где 1 означает - что отвечать не нужно: диалог уже завершен прощанием (девушка попрощалась или написала, что идет спать), а новое сообщение %companion_title% не несет нового содержания - только подтверждение (\'ок\', смайл, повторное \'спокойной ночи\') или повтор его предыдущих сообщений. ВАЖНО: сверяй текущее время со временем сообщений в истории (указано в квадратных скобках). Если после прощания реально прошла ночь и наступило утро нового дня - это новый диалог: отвечать нужно, строго 0, даже на простое \'доброе утро\'. Если же прощание было совсем недавно (минуты назад) и утро еще не наступило, то \'доброе утро\' не соответствует реальности - девушка уже спит и отвечать не нужно, строго 1\\n\\nдля \'prompt_user_facts_companion\' используй document_id: \'%companion_name%\'\\nдля \'prompt_user_facts_talk\' используй document_id: \'%girl_id%_%companion_name%\'\\n\\nФакты не нужно придумывать и создавать. Они должны быть в тексте %companion_title% написаны явно. Если явных фактов нет - нужно вернуть 0 для ключей фактов.\\n\\nExample of JSON response:\\n{\\n  \\"session_messages_result_processed\\": \\"вчера вечером говорили про работу и сериалы, она пожаловалась на усталость, попрощались на ночь\\",\\n  \\"prompt_user_category\\": \\"образование\\",\\n  \\"prompt_user_tags\\": \\"чтение,училище,фильмы\\",\\n  \\"prompt_user_question\\": 0,\\n  \\"search_query\\": \\"что Анна любит читать\\",\\n  \\"prompt_user_facts_companion\\": %fact_collection_output_format_63_result_str%,\\n  \\"prompt_user_facts_talk\\": %fact_collection_output_format_63_result_str%,\\n  \\"prompt_user_ignore\\": 0\\n}\\n\\nExample of JSON response one more:\\n{\\n  \\"session_messages_result_processed\\": \\"\\",\\n  \\"prompt_user_category\\": \\"погода\\",\\n  \\"prompt_user_tags\\": \\"дождь\\",\\n  \\"prompt_user_question\\": 0,\\n  \\"search_query\\": \\"какая погода\\",\\n  \\"prompt_user_facts_companion\\": 0,\\n  \\"prompt_user_facts_talk\\": 0,\\n  \\"prompt_user_ignore\\": 1\\n}"}'),
(28, 2, 3, 'agent_workflow_id', 8, '{"tool_invoke":{"tool_name":"agent_workflow_id","inputs_map":{"name":"girl_agent_workflow_name"},"outputs_map":{"int":"girl_agent_workflow_id"}},"transitions_before":[],"transitions_after":[]}'),
(29, 5, 3, 'session_messages', 0, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit","timezone":"datetime_current_get_zone"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(30, 2, 3, 'qdrant_fact_remove', 14, '{"tool_invoke":{"tool_name":"qdrant_fact_remove","inputs_map":{"collection_name":"fact_collection_girl_name","metadata_filter":"qdrant_metada_filter"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(31, 2, 5, 'Переменные', 13, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"qdrant_metada_filter","text":"{\\"document_id\\":\\"%text_to_lower_37_result_str%\\"}"}]}'),
(37, 2, 3, 'text_to_lower', 3, '{"tool_invoke":{"tool_name":"text_to_lower","inputs_map":{"text":"text_translit_cyr_to_lat_22_result_str"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(38, 5, 3, 'qdrant_fact_search_companion', 8, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"search_query","collection_name":"fact_collection_companion_name","metadata_filter":"fact_collection_man_filter","limit":"fact_collection_limit"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(39, 5, 3, 'qdrant_fact_search_talk', 9, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"search_query","collection_name":"fact_collection_talk_name","metadata_filter":"fact_collection_talk_filter","limit":"fact_collection_limit"},"outputs_map":{"str":"qdrant_fact_search_result_talk"}},"transitions_before":[],"transitions_after":[]}'),
(43, 2, 5, 'Переменные', 4, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"agent_exists_find_by","text":"{\\"name\\":\\"%text_to_lower_37_result_str%\\"}"}]}'),
(44, 2, 4, 'Агент уже существует', 18, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Девушка с таким именем \\"%prompt_user%\\" уже зарегистрирована, придумайте другое имя.\\n\\n/start"}'),
(45, 5, 3, 'datetime_current_get', 3, '{"tool_invoke":{"tool_name":"datetime_current_get","inputs_map":{"timezone":"datetime_current_get_zone"},"outputs_map":{"str":"datetime_current_get_response"}},"transitions_before":[],"transitions_after":[]}'),
(48, 5, 6, 'girl_fact_create', 16, '{"workflow_invoke":{"workflow_id":6,"inputs_map":{"companion_title":"companion_title","girl_name":"agent_name","girl_title":"agent_title","prompt_user":"prompt_user","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(49, 6, 3, 'fact_collection_output_format', 0, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_girl_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(50, 6, 2, 'Новый факты', 3, '{"transitions_before":[],"transitions_after":[],"llm_to_json_variable":[{"variable":"prompt_user_facts_girl","text":"в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_name% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос. Если уже существующие факты достаточно и конкретно отвечают на вопрос — новые придумывать НЕ нужно: верни 0 для ключа prompt_user_facts_girl. Каждый факт — одно-два коротких предложения (до 25 слов), обычным текстом без markdown-разметки. ВАЖНО: не выдумывай конкретные номера школ, точные адреса и названия реальных заведений — выдуманная конкретика противоречит реальности. Используй либо общеизвестные реальные места (Крещатик, Оболонь), либо обобщения (школа рядом с домом, кафе в центре)."}],"prompt_user":"=== %companion_title% пишет ===\\n%prompt_user%\\n%if qdrant_fact_search_65_result_str%\\n\\n=== Уже существующие факты о девушке %girl_title% ===\\n%qdrant_fact_search_65_result_str%\\n%endif%\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"prompt_user_facts_girl\\": в тексте написаный мужчиной есть вопрос к девушке о ее прошлом, ее увлечениях и на этот вопрос %girl_title% должна ответить. Придумай пару новых фактов о себе, которые помогут ответить на вопрос. Новые факты не должны противоречить уже существующим. Если уже существующие факты достаточно и конкретно отвечают на вопрос — новые придумывать НЕ нужно: верни 0 для ключа prompt_user_facts_girl. Каждый факт — одно-два коротких предложения (до 25 слов), обычным текстом без markdown-разметки. ВАЖНО: не выдумывай конкретные номера школ, точные адреса и названия реальных заведений — выдуманная конкретика противоречит реальности. Используй либо общеизвестные реальные места (Крещатик, Оболонь), либо обобщения (школа рядом с домом, кафе в центре).\\n\\nдля \'prompt_user_facts_girl\' используй для document_id: значение \'%girl_name%\' (пример: \\"document_id\\":\\"%girl_name%\\")\\n\\nExample of JSON response:\\n{\\n  \\"prompt_user_facts_girl\\": %fact_collection_output_format_49_result_str%\\n}"}'),
(51, 6, 3, 'fact_collection_add_girl', 4, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_girl_name","data":"prompt_user_facts_girl","document_title":"girl_title","user_id":"user_id"},"outputs_map":{}},"transitions_before":[{"variable":"prompt_user_facts_girl","operator":"==","value":"0","step_id":"52"}],"transitions_after":[]}'),
(52, 6, 4, 'Вернуть факты', 6, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%if fact_collection_add_51_result_facts_str%%fact_collection_add_51_result_facts_str%%else%%qdrant_fact_search_65_result_str%%endif%","continue_workflow":false}'),
(55, 7, 3, 'fact_collection_add_companion', 0, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_companion_name","data":"prompt_user_facts_companion","document_title":"companion_title","user_id":"user_id"},"outputs_map":{}},"transitions_before":[{"variable":"prompt_user_facts_companion","operator":"==","value":"0","step_id":"104"}],"transitions_after":[]}'),
(56, 7, 3, 'fact_collection_add_talk', 2, '{"tool_invoke":{"tool_name":"fact_collection_add","inputs_map":{"collection_name":"fact_collection_talk_name","data":"prompt_user_facts_talk","document_title":"document_title","user_id":"user_id"},"outputs_map":{}},"transitions_before":[{"variable":"prompt_user_facts_talk","operator":"==","value":"0","step_id":"57"}],"transitions_after":[]}'),
(57, 7, 4, 'Вернуть факты', 3, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%prompt_user_facts_companion%","continue_workflow":false}'),
(58, 5, 6, 'companion_fact_extract', 5, '{"workflow_invoke":{"workflow_id":7,"inputs_map":{"prompt_user_facts_companion":"prompt_user_facts_companion","prompt_user_facts_talk":"prompt_user_facts_talk","user_name":"agent_name","companion_name":"companion_name","companion_title":"companion_title","user_id":"user_id"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(63, 5, 3, 'fact_collection_output_format', 2, '{"tool_invoke":{"tool_name":"fact_collection_output_format","inputs_map":{"collection_name":"fact_collection_companion_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(64, 6, 5, 'Переменные', 1, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"fact_invent_filter","text":"{\\"user_id\\":%user_id%}"}]}'),
(65, 6, 3, 'qdrant_fact_search_girl_bio', 2, '{"tool_invoke":{"tool_name":"qdrant_fact_search","inputs_map":{"query_text":"prompt_user","collection_name":"fact_collection_girl_name","metadata_filter":"fact_invent_filter","limit":"fact_invent_limit"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(97, 5, 5, 'Влить придуманные факты', 17, '{"transitions_before":[],"transitions_after":[{"variable":"agent_id","operator":">","value":"0","step_id":"38"}],"variable_conversion":[{"variable":"qdrant_fact_search_25_result_str","text":"%qdrant_fact_search_25_result_str%%if workflow_invoke_48_result_str%\\n%workflow_invoke_48_result_str%%endif%"}]}'),
(100, 2, 5, 'Сохранить имя девушки', 6, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"girl_title_saved","text":"%prompt_user%"}]}'),
(101, 2, 4, 'Спросить биографию', 10, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Добавьте краткую биографию девушки %girl_title_saved%.\\n\\nНапишите свободным текстом 15-20 предложений: сколько лет, где родилась и живет, чем занимается, где училась, увлечения, семья, характер.\\n\\nПример:\\n[[+%girl_bio_example%]]","continue_workflow":true}'),
(102, 2, 3, 'qdrant_fact_sync', 16, '{"tool_invoke":{"tool_name":"qdrant_fact_sync","inputs_map":{},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(103, 6, 3, 'qdrant_fact_sync', 5, '{"tool_invoke":{"tool_name":"qdrant_fact_sync","inputs_map":{},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(104, 7, 5, 'Переменные', 1, '{"transitions_before":[],"transitions_after":[],"variable_conversion":[{"variable":"document_title","text":"%user_name%_%companion_name%"}]}'),
(105, 5, 3, 'Проверка повтора', 12, '{"tool_invoke":{"tool_name":"session_response_repeat_check","inputs_map":{"session_uuid":"session_uuid","response":"girl_response","prompt_user":"prompt_user"},"outputs_map":{}},"transitions_before":[],"transitions_after":[{"variable":"session_response_repeat_check_105_result_repeat","operator":"==","value":"1","step_id":"107"}]}'),
(106, 5, 4, 'Ответ', 13, '{"transitions_before": [], "transitions_after": [], "prompt_user": "%girl_response%", "continue_workflow": false}'),
(107, 5, 4, 'Тишина', 14, '{"transitions_before": [], "transitions_after": [], "prompt_user": "", "continue_workflow": false}'),
(108, 5, 3, 'session_messages_summary', 1, '{"tool_invoke":{"tool_name":"session_messages","inputs_map":{"session_uuid":"session_uuid","limit":"session_messages_limit_summary","timezone":"datetime_current_get_zone"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(109, 5, 2, 'Валидация ответа', 11, '{"transitions_before":[],"transitions_after":[{"variable":"girl_response_skip","operator":"==","value":"1","step_id":"107"}],"llm_to_json_variable":[{"variable":"girl_response_skip","text":"1 - ответ не обязателен, пропускаем (девушка молчит), 0 - ответ важен, отправляем"}],"prompt_user":"=== Текущее время ===\\n%datetime_current_get_45_result_str%\\n\\n%if session_messages_29_result_str%=== История переписки (время сообщений в квадратных скобках) ===\\n%session_messages_29_result_str%\\n\\n%endif%=== %companion_title% пишет ===\\n%prompt_user%\\n\\n=== Черновик ответа девушки ===\\n%girl_response%\\n\\n=== Что нужно ===\\nТы строгий редактор реалистичности переписки. Реальная девушка не отвечает на каждое сообщение: часть реплик она оставляет без ответа, иногда просто молчит. Автоответ на все подряд выглядит фальшиво. Критически оцени, обязателен ли этот ответ.\\n\\ngirl_response_skip = 1 (пропустить ответ), если:\\n- сообщение %companion_title% - реплика-реакция, не требующая ответа: ок, ясно, понятно, ахах, круто, одиночный смайл\\n- черновик не несет новой информации: поддакивание, повтор уже сказанного, вежливое поддержание разговора ради разговора\\n- на суть сообщения девушка уже ответила ранее в истории\\n- черновик пустой или бессодержательный\\n\\ngirl_response_skip = 0 (ответ нужен), если:\\n- есть прямой вопрос к девушке или запрос информации\\n- обсуждаются планы, договоренности, место или время встречи\\n- новая тема или сообщение с новыми фактами, на которые естественно отреагировать\\n- если уже пропустила два или три обращения, то из вежливости можно ответить, но только по делу, если запросы вежливые и не навязчивые\\n- первое сообщение диалога или сообщение после долгой паузы (сравни метки времени с текущим временем)\\n- %companion_title% делится чем-то личным и молчание выглядело бы грубо\\n\\nЕсли сомневаешься между 0 и 1 - выбирай 1: молчание реалистичнее лишнего ответа.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\"girl_response_skip\\": 0 или 1, где 1 - ответ пропускаем (девушка молчит), 0 - ответ отправляем\\n\\nExample of JSON response:\\n{\\n  \\"girl_response_skip\\": 1\\n}"}'),
(111, 2, 3, 'Список девушек', 19, '{"tool_invoke":{"tool_name":"agent_list","inputs_map":{"user_id":"user_id","workflow_name":"girl_agent_workflow_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[{"variable":"agent_list_111_result_qty","operator":"==","value":"0","step_id":"115"}]}'),
(112, 2, 4, 'Выбрать девушку для удаления', 20, '{"transitions_before":[],"transitions_after":[],"prompt_user":"Выберите девушку для удаления (нажмите на имя):\\n\\n%agent_list_111_result_chips%","continue_workflow":true}'),
(113, 2, 3, 'agent_remove', 21, '{"tool_invoke":{"tool_name":"agent_remove","inputs_map":{"title":"prompt_user","user_id":"user_id","workflow_name":"girl_agent_workflow_name"},"outputs_map":{}},"transitions_before":[],"transitions_after":[]}'),
(114, 2, 4, 'Результат удаления', 22, '{"transitions_before":[],"transitions_after":[],"prompt_user":"%if agent_remove_113_result_removed%✅ Девушка «%agent_remove_113_result_title%» удалена.%else%Девушка «%prompt_user%» не найдена среди доступных вам. Запустите /girl_remove еще раз.%endif%","continue_workflow":false}'),
(115, 2, 4, 'Нет девушек', 23, '{"transitions_before":[],"transitions_after":[],"prompt_user":"У вас пока нет созданных девушек. Создать: /girl_create","continue_workflow":false}');

--

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
(24, 'fact_collection_girl_name', 'workflow', 'dating_girl', NULL),
(26, 'facts', 'workflow', NULL, NULL),
(30, 'girl_prompt_system', 'workflow', NULL, NULL),
(32, 'workflow_variable', 'workflow', NULL, NULL),
(34, 'fact_collection_girl_name', 'workflow', 'dating_girl', NULL),
(35, 'fact_collection_girl_filter', 'workflow', NULL, NULL),
(36, 'session_messages_limit', 'workflow', '20', NULL),
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
(91, 'fact_invent_filter', 'workflow', NULL, 'Фильтр поиска биографии для придумывания фактов: только agent_id, без tags'),
(109, 'girl_id', 'input', NULL, NULL),
(110, 'document_title', 'workflow', NULL, NULL),
(111, 'user_name', 'input', NULL, NULL),
(112, 'user_id', 'input', NULL, 'ID пользователя, запустившего workflow — владелец создаваемых фактов (вход sub-workflow)'),
(113, 'prompt_user_ignore', 'workflow', '0', 'Флаг анализа: 1 - отвечать не нужно (диалог завершен, сообщение без нового содержания)'),
(114, 'session_messages_limit_summary', 'workflow', '50', 'Лимит сообщений для краткой выдержки истории (шире детального блока)'),
(115, 'session_messages_result_processed', 'workflow', NULL, 'Краткая выдержка истории переписки (результат шага Анализ сообщения)'),
(116, 'girl_response_skip', 'workflow', '0', 'Флаг валидации ответа: 1 - ответ не обязателен, пропускаем для реалистичности'),
(117, 'girl_response', 'workflow', NULL, NULL),
(127, 'prompt_user_facts_girl', 'workflow', NULL, 'Придуманные факты о девушке или 0 (выход llm_to_json шага «Новый факты»)');

--

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(24, 2),
(26, 2),
(30, 2),
(32, 2),
(34, 5),
(34, 6),
(35, 5),
(36, 5),
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
(78, 6),
(80, 6),
(80, 7),
(81, 7),
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
(109, 5),
(110, 7),
(111, 7),
(112, 6),
(112, 7),
(113, 5),
(114, 5),
(115, 5),
(116, 5),
(117, 5),
(127, 6);

--

INSERT INTO `agent_workflow_variable_public` (`id`, `node_id`, `name`, `title`, `type`, `default`, `position`, `description`) VALUES
(1, 2, 'girl_title', 'girl_title', 'proxy', '%prompt_user%', 0, '{\"ru\":\"Имя девушки\",\"en\":\"The girl\'s name\"}'),
(2, 2, 'girl_prompt_system', 'Правила ответов', 'public', '{\"ru\":\"Ты девушка %girl_title%. Всегда отвечай от имени девушки. С вероятностью 15% допускай синтаксические ошибки в словах, пиши с маленькой буквы или пропускай знаки пунктуации. \\nТы никогда не соглашаешься на личные встречи или звонки. \\nТы никогда не предлагаешь встретиться и куда-то вместе сходить.\\nТы любишь флиртовать. \\nЕсли возникают вопросы о встречах, звонках или другой личной информации, ты пытаешься мягко отшутиться или перевести тему. То же касается и фото: ты не скидываешь их и не обещаешь ничего конкретного. Но в то же время ты точно знаешь, что ищешь любовь, отношения, и пытаешься лучше узнать друг друга в переписке. \\nТы современная приземленная девушка: говоришь о реальной жизни — работа, быт, кафе, сериалы, спорт, поездки, планы. Не уходи в поэзию, высокопарные метафоры и старомодную романтику (стихи, кружева, шелк, винтажные духи), если собеседник сам об этом не спросил. \\nТы живешь в Украине, музыка, книга, города, наука все только украинское. Никаких упоминанй российского и все что связано с россией. \\nОтвечай всегда коротко, как в мессенджере: одно-два предложения, до 20 слов. Больше слов — только если необходимо.\",\"en\":\"You are a girl %girl_title%. Always respond as the girl. With a 15% probability, make syntax errors in words, write in lowercase or skip punctuation.\\nYou never agree to personal meetings or calls.\\nYou never suggest meeting up or going somewhere together.\\nYou love to flirt.\\nIf questions arise about meetings, calls, or other personal information, you try to gently joke or change the subject. The same applies to photos: you don’t send them or promise anything specific. But at the same time, you know you’re looking for love, a relationship, and you try to get to know each other better through messaging.\\nYou’re a modern down-to-earth girl: you talk about real life—work, daily routine, cafes, series, sports, trips, plans. Don’t go into poetry, lofty metaphors, or old-fashioned romance (poems, lace, silk, vintage perfumes) unless the interlocutor asks about it themselves.\\nYou live in Ukraine; music, books, cities, science—everything is Ukrainian. No mentions of Russia or anything related to Russia.\\nAlways respond briefly, like in a messenger: one or two sentences, up to 20 words. More words—only if necessary.\"}', 2, '{\"ru\":\"Правила ответов девушки\",\"en\":\"Girl\'s response rules\"}'),
(3, 2, 'girl_bio_example', 'Пример биографии', 'public', '{\"ru\":\"Мне 27 лет, зовут %girl_title%. Я родилась в Виннице, а последние пять лет живу в Киеве. Работаю графическим дизайнером в небольшой студии. Училась в КПИ на издательском деле. Снимаю однокомнатную квартиру возле парка и живу с котом Марсом. По утрам люблю пробежки вдоль Днепра. Обожаю кофе и знаю все кофейни своего района. В школьные годы занималась бальными танцами. С родителями отношения теплые, созваниваемся каждые выходные. Мама преподает музыку, папа инженер. Есть младший брат Артем, он студент. Летом стараюсь путешествовать: была в Польше, Грузии и Италии. Мечтаю увидеть Японию. Сейчас не в отношениях, рассталась с парнем два года назад. Детей нет, но в будущем хочу семью. Люблю готовить, особенно выпечку. Читаю современную украинскую литературу. По характеру спокойная, но люблю посмеяться.\",\"en\":\"I\'m 27 years old, my name is %girl_title%. I was born in Vinnytsia and have been living in Kyiv for the past five years. I work as a graphic designer at a small studio. I studied publishing at KPI. I rent a one-room apartment near the park and live with my cat Mars. I love morning runs along the Dnipro. I adore coffee and know all the coffee shops in my neighborhood. In school, I did ballroom dancing. I have a warm relationship with my parents; we call each other every weekend. My mom is a music teacher, and my dad is an engineer. I have a younger brother, Artem, who is a student. I try to travel in the summer: I\'ve been to Poland, Georgia, and Italy. I dream of visiting Japan. Currently, I\'m not in a relationship; I broke up with my boyfriend two years ago. I don’t have children, but I want a family in the future. I love cooking, especially baking. I read contemporary Ukrainian literature. I\'m calm by nature, but I enjoy a good laugh.\"}', 3, '{\"ru\":\"Пример краткой биографии\",\"en\":\"Example of a brief biography\"}');

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

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(9, 2, 'dating_bot', 'Dating bot', '', 2, '{}', '{"en":"You are a responsible performer. You do everything you are asked to. If the request specifies to return the answer in JSON, you must return it in JSON. If nothing about JSON is mentioned, return plain text.","ru":"Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON. Если про JSON ничего не написано, то возращай обычный текст."}', 'Привет, я dating bot, доступны команды :\n\n/girl_create - создает девушку\n/girl_remove - удаляет девушку', 0, 0);

--

INSERT INTO `agent_role` (`agent_id`, `role_id`) VALUES
(9, 2),
(9, 4);