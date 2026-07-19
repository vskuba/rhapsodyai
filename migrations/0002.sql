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
(18, 'openai/gpt-5.3-codex');

--

INSERT INTO `role` (`id`, `name`) VALUES
(1, 'admin'),
(2, 'manager_dating'),
(3, 'manager_cashier'),
(4, 'manager_dating_junior');

-- Password: admin123
-- Password: user123

INSERT INTO `user` (`id`, `username`, `email`, `password_hash`, `role_id`, `created_at`) VALUES
(1, 'admin', 'admin@example.com', '$2b$12$HgW3UjBwpAX6vYk5M6JykOM73WQuAVDw/.zHu8DxEZ3p8H0/FySx.', 1, '2026-04-26 09:17:35'),
(2, 'lilia', 'lilia@example.com', '$2b$12$XG.UEUHZz3kkq73DpN52Z.7rqVMgrlCnsbyK2bR2tuXTLkBPhACDK', 2, '2026-04-26 09:17:35'),
(3, 'olga', 'olga@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 3, '2026-04-26 09:17:35'),
(4, 'alena', 'alena@example.com', '$2b$12$WXFmztot.T5tdQHhjCdRses4YaBeABOaA8DLVPFfly2z.UAlqJ0QS', 4, '2026-04-26 09:17:35');

--

INSERT INTO `user_access_token` (`id`, `user_id`, `token`) VALUES
(1, 2, '8fd15581-36ae-48ed-812f-3b3d11d427f0');

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

INSERT INTO `user_llm` (`user_id`, `llm_id`, `rate_limit_at`, `code_error`, `position`) VALUES
(1, 5, NULL, NULL, 1),
(1, 6, NULL, NULL, 4),
(1, 10, NULL, NULL, 5),
(1, 11, NULL, NULL, 0),
(1, 12, NULL, NULL, 3),
(1, 15, NULL, NULL, 2),
(1, 16, NULL, NULL, 6),
(2, 5, NULL, NULL, 2),
(2, 6, NULL, NULL, 5),
(2, 10, NULL, NULL, 6),
(2, 11, NULL, NULL, 1),
(2, 12, NULL, NULL, 4),
(2, 15, NULL, NULL, 3),
(2, 16, NULL, NULL, 7),
(4, 5, NULL, NULL, 2),
(4, 6, NULL, NULL, 5),
(4, 10, NULL, NULL, 6),
(4, 11, NULL, NULL, 1),
(4, 12, NULL, NULL, 4),
(4, 15, NULL, NULL, 3),
(4, 16, NULL, NULL, 7);

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

INSERT INTO `session` (`id`, `uuid`, `metadata`) VALUES
(1, 'dd532f75-574b-47bf-a63c-74caa6320198', '{"workflow_step_current_index": 0, "workflow_variables_saved": {}}'),
(2, 'cd46f14b-ec18-4e8b-b612-2dcb971eb795', '{"workflow_step_current_index": 0, "workflow_variables_saved": {}}');

--

INSERT INTO `tool_group` (`id`, `name`) VALUES
(1, 'Web'),
(2, 'Weather'),
(3, 'Session'),
(4, 'Qdrant'),
(5, 'Agent'),
(6, 'Text'),
(7, 'Detective'),
(8, 'Companion'),
(9, 'Dict'),
(10, 'Fact'),
(11, 'Github'),
(12, 'List'),
(13, 'Setting'),
(14, 'Counter'),
(15, 'Datetime_'),
(16, 'Mysql');

--

INSERT INTO `tool` (`id`, `name`, `group_id`, `path`, `description`, `args`) VALUES
(198, 'weather_get', 2, '/app/src/tool/weather/weather.py', 'Get the weather forecast for a city.\nArgs:\n    city: City name.\n    days_offset: 0 for today, 1 for tomorrow, 2 for the day after (max 6).', '{"input": {"city": {"type": "str", "default": "Required"}, "days_offset": {"type": "int", "default": "0"}}, "output": {"type": "str"}}'),
(199, 'list_render', 12, '/app/src/tool/list/list_.py', 'Форматирует список в строку: каждый элемент подставляется в template вместо %s,\nэлементы соединяются separator. Например template="[[%s]]" и separator=" "\nдают чипсы чата: [[a]] [[b]] [[c]].', '{"input": {"items": {"type": "list", "default": "Required"}, "template": {"type": "str", "default": "%s"}, "separator": {"type": "str", "default": ", "}}, "output": {"type": "str"}}'),
(200, 'list_shift', 12, '/app/src/tool/list/list_.py', 'Извлекает первый элемент JSON-массива объектов и возвращает его поля вместе\nс остатком списка в ключе \'rest\'. Предназначено для workflow_invoke с\nrepeat.until: outputs_map пишет \'rest\' обратно в ту же переменную, которую\nчитает inputs_map - каждая итерация забирает из очереди один элемент, пока\nuntil (rest empty) не остановит цикл.\n - items: JSON-массив объектов (или его JSON-строка)\nReturns:\n    dict: поля первого элемента + rest (list) - остаток списка без первого элемента.', '{"input": {"items": {"type": "list", "default": "Required"}}, "output": {"type": "dict"}}'),
(201, 'datetime_current_get', 15, '/app/src/tool/datetime_/datetime_.py', 'Возвращает текущую дату и время в текстовом формате на русском языке с учетом часового пояса.\n\nArgs:\n    timezone (str): Смещение часового пояса относительно UTC. Поддерживаются форматы: "+2", "-3", "UTC+2", "UTC-3", etc. Default "0".', '{"input": {"timezone": {"type": "str", "default": "0"}}, "output": {"type": "str"}}'),
(202, 'detective_case_seed_generate', 7, '/app/src/tool/detective/detective_.py', 'Выбирает случайные "якоря" для генерации дела ДО вызова LLM: тему места\nпреступления, тему орудия убийства и номер виновного подозреваемого (1-4).\nРешает две проблемы свободной LLM-генерации: повторяющиеся сеттинги\n(кабинет/кинжал/окно в каждом деле) и предсказуемость виновного (LLM\nпочти всегда делает виновным подозреваемого №1 с очевидным мотивом) -\nслучайный выбор навязывается программно, а не отдается на волю модели.\n - location_pool: список тем места преступления (workflow-переменная location_pool)\n - weapon_pool: список тем орудия убийства (workflow-переменная weapon_pool)\nReturns:\n    dict: Словарь с результатом, содержащий:\n        location_theme (str): случайно выбранная тема места преступления.\n        weapon_theme (str): случайно выбранная тема орудия убийства.\n        guilty_suspect_index (int): номер виновного подозреваемого (1-4).', '{"input": {"location_pool": {"type": "list", "default": "Required"}, "weapon_pool": {"type": "list", "default": "Required"}}, "output": {"type": "dict", "keys": {"location_theme": {"type": "str"}, "weapon_theme": {"type": "str"}, "guilty_suspect_index": {"type": "int"}}}}'),
(203, 'detective_case_create', 7, '/app/src/tool/detective/detective_.py', 'Сохраняет новое сгенерированное дело для сессии игрока. Игровое дело\nпривязано к session_uuid (одна игровая сессия = одно активное дело;\nповторный /new_case в той же сессии создает новую запись - актуальной\nсчитается последняя по id для этой сессии).\n - session_uuid: сессия игрока (workflow-переменная session_uuid)\n - user_id: активный пользователь (workflow-переменная user_id)\n - victim_name: имя жертвы\n - crime_description: краткое описание преступления для игрока\n - guilty_suspect_name: имя виновного подозреваемого (должно совпадать с title его агента)\n - solution_reveal: текст разгадки, показывается после /accuse\nReturns:\n    dict: Словарь с результатом сохранения, содержащий:\n        id (int): ID созданной записи дела.', '{"input": {"session_uuid": {"type": "str", "default": "Required"}, "user_id": {"type": "int", "default": "Required"}, "victim_name": {"type": "str", "default": "Required"}, "crime_description": {"type": "str", "default": "Required"}, "guilty_suspect_name": {"type": "str", "default": "Required"}, "solution_reveal": {"type": "str", "default": "Required"}}, "output": {"type": "dict", "keys": {"id": {"type": "int"}}}}'),
(204, 'detective_suspects_queue_build', 7, '/app/src/tool/detective/detective_.py', 'Собирает плоские suspect_N_* переменные (результат генерации дела через\nllm_to_json) в очередь агентов на создание - по одному элементу на\nподозреваемого, с именем агента по конвенции \'case_<session_uuid>_sN\'.\nОчередь скармливается в workflow_invoke с repeat.count=4 (list_shift +\ndetective_suspect_create), что заменяет 4 отдельных шага создания агента одним циклом.\n - session_uuid: сессия игрока (workflow-переменная session_uuid) - для имени агента\n - suspect_N_name/sheet/greeting: сгенерированные поля подозреваемого N (1-4)\n - suspect_N_interrogation: протокол предварительного допроса подозреваемого N полицией\n   (алиби кратко, род занятий, приметы, отношения с жертвой, семейное положение) -\n   добавляется к легенде, чтобы подозреваемый не противоречил уже данным показаниям\nReturns:\n    list: 4 объекта {agent_name, name, sheet, greeting, interrogation} в порядке подозреваемых.', '{"input": {"session_uuid": {"type": "str", "default": "Required"}, "suspect_1_name": {"type": "str", "default": "Required"}, "suspect_1_sheet": {"type": "str", "default": "Required"}, "suspect_1_greeting": {"type": "str", "default": "Required"}, "suspect_1_interrogation": {"type": "str", "default": "Required"}, "suspect_2_name": {"type": "str", "default": "Required"}, "suspect_2_sheet": {"type": "str", "default": "Required"}, "suspect_2_greeting": {"type": "str", "default": "Required"}, "suspect_2_interrogation": {"type": "str", "default": "Required"}, "suspect_3_name": {"type": "str", "default": "Required"}, "suspect_3_sheet": {"type": "str", "default": "Required"}, "suspect_3_greeting": {"type": "str", "default": "Required"}, "suspect_3_interrogation": {"type": "str", "default": "Required"}, "suspect_4_name": {"type": "str", "default": "Required"}, "suspect_4_sheet": {"type": "str", "default": "Required"}, "suspect_4_greeting": {"type": "str", "default": "Required"}, "suspect_4_interrogation": {"type": "str", "default": "Required"}}, "output": {"type": "list"}}'),
(205, 'detective_case_suspects_list', 7, '/app/src/tool/detective/detective_.py', 'Возвращает подозреваемых текущего (последнего) дела игровой сессии: агентов,\nчье имя соответствует конвенции \'case_<session_uuid>_*\' (создаются шагами\n\'Создать подозреваемого N\' workflow detective_bot), плюс краткие данные\nпоследнего дела сессии для отображения игроку.\n - session_uuid: сессия игрока (workflow-переменная session_uuid)\nReturns:\n    dict: Словарь с данными для допроса, содержащий:\n        chips (str): чипсы вида [[Имя1]] [[Имя2]] для выбора подозреваемого.\n        qty (int): количество подозреваемых.\n        victim_name (str): имя жертвы последнего дела сессии (пустая строка, если дела нет).\n        crime_description (str): описание преступления последнего дела сессии.', '{"input": {"session_uuid": {"type": "str", "default": "Required"}}, "output": {"type": "dict", "keys": {"chips": {"type": "str"}, "qty": {"type": "int"}, "victim_name": {"type": "str"}, "crime_description": {"type": "str"}}}}'),
(206, 'detective_case_verdict_check', 7, '/app/src/tool/detective/detective_.py', 'Проверяет обвинение игрока против последнего дела игровой сессии и помечает\nдело решенным (solved=1) независимо от исхода - обвинение финальное.\n - session_uuid: сессия игрока (workflow-переменная session_uuid)\n - accused_name: имя подозреваемого, которого назвал игрок (из чипса)\nReturns:\n    dict: Словарь с результатом вердикта, содержащий:\n        correct (int): 1 - обвинение верное, 0 - нет.\n        guilty_suspect_name (str): настоящее имя виновного.\n        solution_reveal (str): текст разгадки дела.', '{"input": {"session_uuid": {"type": "str", "default": "Required"}, "accused_name": {"type": "str", "default": "Required"}}, "output": {"type": "dict", "keys": {"correct": {"type": "int"}, "guilty_suspect_name": {"type": "str"}, "solution_reveal": {"type": "str"}}}}'),
(207, 'fact_verify_result_save', 10, '/app/src/tool/fact/fact_verify_.py', 'Сохраняет результат фактчека: помечает факт проверенным, при исправлении\nобновляет текст факта и сбрасывает qdrant_synced (пересинк подхватит крон).\n - fact_id: ID проверенного факта\n - verify_status: вердикт проверки: ok | corrected | unverifiable\n - document_corrected: исправленный текст факта (только для verify_status=corrected)\nReturns:\n    dict: Словарь с результатом сохранения, содержащий:\n        saved (int): 1 - сохранено, 0 - факт не найден или неизвестный статус.', '{"input": {"fact_id": {"type": "int", "default": "Required"}, "verify_status": {"type": "str", "default": "Required"}, "document_corrected": {"type": "str", "default": ""}}, "output": {"type": "dict", "keys": {"saved": {"type": "int"}}}}'),
(208, 'fact_collection_output_format', 10, '/app/src/tool/fact/fact_collection_.py', 'Возвращает JSON в виде текстовой строки.\nВнутри JSON описаны поля таблицы fact, которые имеют комментарий с тегом "extract".', '{"input": {"collection_name": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(209, 'fact_collection_add', 10, '/app/src/tool/fact/fact_collection_.py', 'Добавляет данные напрямую в базовую таблицу фактов \'fact\'.\n - collection_name: имя коллекции для поиска ее ID и разрешенных полей в базе\n - data: список словарей с данными или валидная JSON-строка-массив\n - document_title: заголовок документа (title сущности агента) — проставляется\n   всем добавляемым фактам, если передан\n - user_id: ID пользователя, запустившего workflow — проставляется всем добавляемым\n   фактам, если передан (владелец фактов: только он и админ их видят)\nВозвращает текстовую строку со всеми добавленными фактами.\n\nExample:\n    collection_name: dating_talk\n    data: [{"document_id": "alla_user1", "language": "ru", "document": "Мы обсуждали его привычки в тренировках.", "tags": "тренажерный зал, физическая активность"}]\n    document_title: Анна\n    user_id: 1\n\nReturns:\n    facts_qty (int): количество добавленных фактов\n    facts_str (str): текстовая строка со всеми добавленными фактами', '{"input": {"collection_name": {"type": "str", "default": "Required"}, "data": {"type": "list", "default": "Required"}, "document_title": {"type": "str", "default": ""}, "user_id": {"type": "int", "default": "0"}}, "output": {"type": "dict", "keys": {"facts_qty": {"type": "int"}, "facts_str": {"type": "str"}}}}'),
(210, 'fact_collection_remove_by', 10, '/app/src/tool/fact/fact_collection_.py', 'Удаляет факты из таблицы \'fact\' по переданным критериям.\nВсе переданные критерии объединяются через логическое \'И\' (AND).\n\n:param collection_name: Имя коллекции фактов\n:param criteria: Словарь с фильтрами для удаления (например, {"document_id": "dasha"})\n:return: Количество удаленных записей\n:raises ValueError: Если коллекция не найдена или критерии пусты', '{"input": {"collection_name": {"type": "str", "default": "Required"}, "criteria": {"type": "dict", "default": "Required"}}, "output": {"type": "int"}}'),
(211, 'web_read_page', 1, '/app/src/tool/web/web_.py', 'Opens a URL and returns the text content of the page.\nUse this to get information from the internet.', '{"input": {"url": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(212, 'web_search', 1, '/app/src/tool/web/web_.py', 'Ищет поисковую фразу в интернете (DuckDuckGo) в реальном времени.\nИспользуй для проверки фактов и поиска актуальной информации.\n - query: поисковая фраза\n - limit: количество результатов\n - region: регион поиска: \'ua-uk\' (Украина), \'ru-ru\', \'wt-wt\' (весь мир)\nReturns:\n    dict: Словарь с результатами поиска, содержащий:\n        results (str): нумерованный список результатов (заголовок, ссылка, фрагмент).\n        qty (int): количество найденных результатов.', '{"input": {"query": {"type": "str", "default": "Required"}, "limit": {"type": "int", "default": "5"}, "region": {"type": "str", "default": "ua-uk"}}, "output": {"type": "dict", "keys": {"results": {"type": "str"}, "qty": {"type": "int"}}}}'),
(213, 'counter_increment', 14, '/app/src/tool/counter/counter_.py', 'Увеличивает счетчик на step и возвращает новое значение.\nИнструмент для циклов в workflow: результат сохраняется в переменную,\nа переход с оператором < / >= по лимиту решает, повторять ли цикл.', '{"input": {"value": {"type": "int", "default": "0"}, "step": {"type": "int", "default": "1"}}, "output": {"type": "int"}}'),
(214, 'setting_value_get', 13, '/app/src/tool/setting/setting_.py', 'Возвращает значение настройки по названию (ключу).\nПорядок поиска: сначала настройка конкретной ноды (если передан node_id),\nзатем общая настройка (без ноды), затем default.\n - name: название (ключ) настройки, например \'timezone\'\n - node_id: ID ноды; 0 или пусто — искать только общую настройку\n - default: значение, которое вернется, если настройка не найдена\nReturns:\n    dict: Словарь со значением настройки, содержащий:\n        value (str): значение настройки — нодовое, иначе общее, иначе default.', '{"input": {"name": {"type": "str", "default": "Required"}, "node_id": {"type": "int", "default": "0"}, "default": {"type": "str", "default": ""}}, "output": {"type": "dict", "keys": {"value": {"type": "str"}}}}'),
(215, 'github_repository_list', 11, '/app/src/tool/github/github_.py', 'The function returns a list of the user\'s GitHub repositories as an array of names.\nIf this is an organization, the argument specifies the organization name.\nArguments \'org\' - organization name', '{"input": {"org": {"type": "str | None", "default": "None"}}, "output": {"type": "List"}}'),
(216, 'github_search_branch_with_last_commit', 11, '/app/src/tool/github/github_.py', 'The function returns the name of the branch containing the latest commit.\nThe \'repo_full_name\' argument is the full name of the repository.', '{"input": {"repo_full_name": {"type": "str", "default": "Required"}}, "output": {"type": "str | None"}}'),
(217, 'github_search_repo_by_last_commit', 11, '/app/src/tool/github/github_.py', 'This function returns the full name of the repository.\nIt identifies the repository based on its most recent active commits.\nThe name of the repository with the most recent commits is returned.\nThis function does not accept any arguments. The authorized user is used.', '{"input": {}, "output": {"type": "str | None"}}'),
(218, 'github_get_branch_last_commit', 11, '/app/src/tool/github/github_.py', 'The function returns the latest commit in a branch. The function arguments are the full repository name and the branch name.\nThe arguments \'repo_full_name\' are the full repository name, and \'branch_name\' is the name of the branch being merged.', '{"input": {"repo_full_name": {"type": "str", "default": "Required"}, "branch_name": {"type": "str", "default": "Required"}}, "output": {"type": "github.Commit.Commit | None"}}'),
(219, 'github_check_and_merge_url_get', 11, '/app/src/tool/github/github_.py', 'The function makes a merge request for two branches in a repository.\nArguments:\n\'repo_full_name\' - the full name of the repository\n\'branch_head\' - the name of the branch being merged\n\'branch_base\' - the name of the branch being merged\nIf the merge request is not possible due to a conflict,\nthe function returns a link for manual conflict resolution.\nIf the merge request is possible, it makes the merge request and notifies of a successful result.', '{"input": {"repo_full_name": {"type": "str", "default": "Required"}, "branch_head": {"type": "str", "default": "Required"}, "branch_base": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(220, 'github_check_and_merge', 11, '/app/src/tool/github/github_.py', 'The function makes a merge request for two branches in a repository.\nArguments:\n\'repo_full_name\' - the full name of the repository\n\'branch_head\' - the name of the branch being merged\n\'branch_base\' - the name of the branch being merged.\nIf the merge request is not possible due to a conflict, the function returns a link for\nmanual conflict resolution. If the merge request is possible, it makes the merge request and notifies of a successful\nresult.', '{"input": {"repo_full_name": {"type": "str", "default": "Required"}, "branch_head": {"type": "str", "default": "Required"}, "branch_base": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(221, 'github_user_info', 11, '/app/src/tool/github/github_.py', 'This function returns the full name of the repository.\nIt identifies the repository based on its most recent active commits.\nThe name of the repository with the most recent commits is returned.\nReturns:\n    A dictionary containing the user\'s GitHub login, name, and email.\n    login (str): The GitHub username of the authenticated user.\n    name (str): The full name of the authenticated user.\n    email (str): The email address associated with the authenticated user\'s GitHub account.', '{"input": {"random": {"type": "int", "default": "2"}}, "output": {"type": "dict", "keys": {"login": {"type": "str"}, "name": {"type": "str"}, "email": {"type": "str"}}}}'),
(222, 'qdrant_fact_sync', 4, '/app/src/tool/qdrant/qdrant.py', 'Немедленно синхронизирует несинхронизированные факты (qdrant_synced = 0)\nиз базы данных в Qdrant, не дожидаясь фоновой синхронизации по расписанию.\nОбрабатывает пачками по 50 до полной синхронизации (максимум 20 пачек за\nвызов); останавливается, если пачка не дает прогресса (ошибки синка).\nReturns:\n    A dictionary with the sync report.\n    synced_qty (int): Количество синхронизированных фактов за вызов.\n    report_str (str): Отчет последней пачки синхронизации.', '{"input": {}, "output": {"type": "dict", "keys": {"synced_qty": {"type": "int"}, "report_str": {"type": "str"}}}}'),
(223, 'qdrant_fact_search', 4, '/app/src/tool/qdrant/qdrant.py', 'Высокоуровневая обёртка для поиска.\nАвтоматически подтягивает метаданные и возвращает только список текстовых фактов.', '{"input": {"query_text": {"type": "str", "default": "Required"}, "collection_name": {"type": "str", "default": "Required"}, "metadata_filter": {"type": "str", "default": "Required"}, "limit": {"type": "int", "default": "5"}}, "output": {"type": "str"}}'),
(224, 'qdrant_fact_remove', 4, '/app/src/tool/qdrant/qdrant.py', 'Удаляет факты из коллекции Qdrant на основе фильтра метаданных.', '{"input": {"collection_name": {"type": "str", "default": "Required"}, "metadata_filter": {"type": "str", "default": "Required"}}, "output": {"type": "int"}}'),
(225, 'mysql_export_to_migration', 16, '/app/src/tool/mysql/export_.py', 'Экспортирует указанные таблицы из базы данных в файл миграции ЦЕЛИКОМ (без\nфильтрации по ноде/подпроекту) - находит соответствующие INSERT-блоки и\nзаменяет их актуальными данными. Порядок блоков в файле сохраняется (важно\nдля FK). Для таблиц, общих для всех подпроектов (node, role, user, tool и\nт.п.). Для экспорта данных ОДНОГО подпроекта используйте\nmysql_export_node_to_migration - иначе экспорт смешает строки всех нод\nв одном файле.\ntables — имена таблиц через запятую (например: \'agent_workflow, agent_workflow_step\');\nmigration_file — путь к файлу миграции относительно корня проекта.\nReturns:\n    A dictionary with the export report.\n    tables_qty (int): Количество экспортированных таблиц.\n    rows_qty (int): Суммарное количество экспортированных строк.\n    report_str (str): Отчет: обновленные таблицы и причины пропусков.', '{"input": {"tables": {"type": "str", "default": "Required"}, "migration_file": {"type": "str", "default": "migrations/0002.sql"}}, "output": {"type": "dict", "keys": {"tables_qty": {"type": "int"}, "rows_qty": {"type": "int"}, "report_str": {"type": "str"}}}}'),
(226, 'mysql_export_node_to_migration', 16, '/app/src/tool/mysql/export_.py', 'Экспортирует данные ОДНОЙ НОДЫ (подпроекта) - её workflow, шаги, переменные,\nагентов, публичные переменные, факт-коллекции и роли - в собственный файл\nмиграции подпроекта, без смешивания с данными других нод. Если для таблицы\nв файле еще нет INSERT-блока (новый подпроект/файл миграции) - блок\nдописывается в конец файла.\n\nЕсли у ноды выставлен node.is_catchall=1 (ровно одна такая нода, например\nDashboard) - экспортируется ВСЕ, что НЕ относится ни к одной ДРУГОЙ ноде со\nсвоим migration_file (включая записи с node_id IS NULL), плюс полностью\nглобальные таблицы без node_id вообще (llm, user, role, tool и т.п.).\nТак подпроекты, у которых еще нет своего файла миграции, продолжают\nпопадать в общий файл, пока для них не заведут отдельный.\n - node_id: ID ноды-подпроекта (см. таблицу node)\n - migration_file: путь к файлу миграции; если не передан - берется\n   из node.migration_file (задается на странице Node в админке)\nReturns:\n    dict: отчет экспорта - tables_qty, rows_qty, report_str (как у mysql_export_to_migration).', '{"input": {"node_id": {"type": "int", "default": "Required"}, "migration_file": {"type": "str", "default": ""}}, "output": {"type": "dict"}}'),
(227, 'mysql_find_by', 16, '/app/src/tool/mysql/mysql_.py', 'Универсальный поиск записей в таблице по критериям равенства.\ncriteria — словарь {колонка: значение}; значение-список превращается в IN (...),\nNone — в IS NULL, пустой словарь возвращает все записи (не более limit).\nReturns:\n    Список словарей-записей таблицы (колонка: значение).', '{"input": {"table_name": {"type": "str", "default": "Required"}, "criteria": {"type": "dict", "default": "Required"}, "limit": {"type": "int", "default": "100"}}, "output": {"type": "list"}}'),
(228, 'mysql_find_one_by', 16, '/app/src/tool/mysql/mysql_.py', 'Универсальный поиск одной записи в таблице по критериям равенства.\nЕсли запись не найдена — ошибка (workflow останавливается с понятным сообщением).\nReturns:\n    Словарь-запись таблицы: каждая колонка становится переменной\n    {tool}_{step_id}_result_{column}.', '{"input": {"table_name": {"type": "str", "default": "Required"}, "criteria": {"type": "dict", "default": "Required"}}, "output": {"type": "dict"}}'),
(229, 'mysql_tables_find', 16, '/app/src/tool/mysql/tables_.py', 'Проверяет существование таблиц базы данных по точным именам (массив имен,\nнапример из text_split). Одиночная строка вместо массива тоже принимается.\nРезультат без дублей и подходит для передачи в другие инструменты,\nнапример mysql_export_to_migration.\nReturns:\n    A dictionary with the found database tables.\n    tables_str (str): Имена найденных таблиц через запятую.\n    tables_qty (int): Количество найденных таблиц.', '{"input": {"tables": {"type": "list", "default": "Required"}}, "output": {"type": "dict", "keys": {"tables_str": {"type": "str"}, "tables_qty": {"type": "int"}}}}'),
(230, 'session_messages', 3, '/app/src/tool/session/session_.py', 'Возвращает список сообщений в ввиде текстовой строки.\nСообщения фильтруются по типу (\'user-prompt\', \'response-final\') и сортируются по дате создания в порядке убывания.\nЕсли количество сообщений нечетное, последнее сообщение будет удалено из списка.\n - timezone: смещение часового пояса для времени сообщений ("+3", "-2", "0" — не конвертировать);\n   created_at хранится во времени БД (UTC), конвертация приводит его к поясу пользователя', '{"input": {"session_uuid": {"type": "str", "default": "Required"}, "limit": {"type": "int", "default": "10"}, "timezone": {"type": "str", "default": "0"}}, "output": {"type": "str"}}'),
(231, 'session_response_repeat_check', 3, '/app/src/tool/session/session_.py', 'Проверяет, является ли сгенерированный ответ зацикливанием (анти-луп: "сплю уже"\nна каждое "ок"). Зацикливание — это когда ОБА условия выполнены: ответ повторяет\nодин из последних ответов агента И входящее сообщение повторяет одно из последних\nсообщений собеседника (не несет новизны). Легитимные повторы ("да"/"нет" на серию\nРАЗНЫХ вопросов) не гасятся: новое входящее сообщение -> repeat всегда 0.\nСравнение по нормализованному тексту: точное совпадение или сходство выше порога 0.85.\n - session_uuid: сессия переписки\n - response: сгенерированный ответ до отправки\n - prompt_user: входящее сообщение собеседника (без него проверяется только ответ)\n - limit: сколько последних сообщений каждой стороны сравнивать\nReturns:\n    A dictionary with the check result.\n    repeat (int): 1 — зацикливание (и ответ, и входящее сообщение — повторы), 0 — отвечать можно.', '{"input": {"session_uuid": {"type": "str", "default": "Required"}, "response": {"type": "str", "default": "Required"}, "prompt_user": {"type": "str", "default": ""}, "limit": {"type": "int", "default": "5"}}, "output": {"type": "dict", "keys": {"repeat": {"type": "int"}}}}'),
(232, 'session_uuid_create', 3, '/app/src/tool/session/session_.py', 'Автоматически импортированная функция session_uuid_create', '{"input": {}, "output": {"type": "str"}}'),
(233, 'session_message_add', 3, '/app/src/tool/session/session_.py', 'Записывает в сессию пару сообщений диалога: user-prompt (сообщение собеседника)\nи response-final (ответ агента) под одним request_uuid. Нужен workflow-оберткам,\nкоторые ведут диалог с целевым workflow: его session_messages видит эту переписку\nкак обычную историю. agent_id задает, чьим именем подписывается ответ.', '{"input": {"session_uuid": {"type": "str", "default": "Required"}, "user_message": {"type": "str", "default": "Required"}, "agent_response": {"type": "str", "default": "Required"}, "agent_id": {"type": "int", "default": "0"}, "user_id": {"type": "int", "default": "0"}, "companion_id": {"type": "int", "default": "0"}}, "output": {"type": "str"}}'),
(234, 'companion_create', 8, '/app/src/tool/companion/companion.py', 'Автоматически импортированная функция companion_create', '{"input": {"name": {"type": "str", "default": "Required"}, "title": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(235, 'companion_id', 8, '/app/src/tool/companion/companion.py', 'Автоматически импортированная функция companion_id', '{"input": {"name": {"type": "str", "default": "Required"}}, "output": {"type": "int"}}'),
(236, 'companion_title', 8, '/app/src/tool/companion/companion.py', 'Автоматически импортированная функция companion_title', '{"input": {"name": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(237, 'text_regex_extract', 6, '/app/src/tool/text/text_.py', 'Извлекает из текста первую группу регулярного выражения.\nЕсли групп в выражении нет — возвращает все совпадение целиком.\nЕсли совпадения нет или выражение некорректно — значение default.\nПример:\n    text = "User: John Doe, Age: 30"\n    pattern = r"Age: (\\d+)"\n    result = await text_regex_extract(text, pattern, default="N/A")\n    # result будет "30"', '{"input": {"text": {"type": "str", "default": "Required"}, "pattern": {"type": "str", "default": "Required"}, "default": {"type": "str", "default": ""}}, "output": {"type": "str"}}'),
(238, 'text_split', 6, '/app/src/tool/text/text_.py', 'Разбивает текст по разделителю в массив строк.\nПробелы по краям элементов обрезаются, пустые элементы отбрасываются.\nПример:\n    text = "node, user, companion"\n    result = await text_split(text, separator=",")\n    # result будет {"list": ["node", "user", "companion"], "qty": 3}\nReturns:\n    A dictionary with the split result.\n    list (list): Массив строк.\n    qty (int): Количество элементов.', '{"input": {"text": {"type": "str", "default": "Required"}, "separator": {"type": "str", "default": ","}}, "output": {"type": "dict", "keys": {"list": {"type": "list"}, "qty": {"type": "int"}}}}'),
(239, 'text_translit_cyr_to_lat', 6, '/app/src/tool/text/text_.py', 'Трансформация кириллицы в латиницу', '{"input": {"text": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(240, 'text_to_lower', 6, '/app/src/tool/text/text_.py', 'Автоматически импортированная функция text_to_lower', '{"input": {"text": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(241, 'text_to_upper', 6, '/app/src/tool/text/text_.py', 'Автоматически импортированная функция text_to_upper', '{"input": {"text": {"type": "str", "default": "Required"}}, "output": {"type": "str"}}'),
(242, 'dict_column', 9, '/app/src/tool/dict/dict_.py', 'Возвращает значения по ключу column_name из данных.\ndata — список словарей (вернется список значений по ключу из каждой записи),\nсловарь (вернется значение ключа) или JSON-строка одного из этих видов.\nПустые/невалидные данные — пустая строка.', '{"input": {"data": {"type": "list", "default": "Required"}, "column_name": {"type": "str", "default": "Required"}}, "output": {"type": "Any"}}'),
(243, 'agent_create_or_update', 5, '/app/src/tool/agent/agent_.py', 'Создает или обновляет агента по системному имени.\nuser_id — активный пользователь (workflow-переменная user_id из сессии):\nагент получает те же роли, что и пользователь (agent_role).\nВсегда проставляет agent.dynamic=1 - это единственная точка создания\nагентов в рантайме (девушки в dating, подозреваемые/сержант в detective\nи т.п.), в отличие от статичных ботов, которые заводятся только через\nINSERT в миграциях. Флаг нужен mysql_export_node_to_migration, чтобы не\nзапекать реальные игровые данные в seed-экспорт подпроекта.', '{"input": {"name": {"type": "str", "default": "Required"}, "title": {"type": "str", "default": "Required"}, "node_id": {"type": "int | None", "default": "None"}, "workflow_id": {"type": "int | None", "default": "None"}, "workflow_variable": {"type": "str | None", "default": "None"}, "prompt_system": {"type": "str", "default": ""}, "description": {"type": "str", "default": ""}, "greeting": {"type": "str", "default": ""}, "user_id": {"type": "int | None", "default": "None"}}, "output": {"type": "int"}}'),
(244, 'agent_exists', 5, '/app/src/tool/agent/agent_.py', 'Автоматически импортированная функция agent_exists', '{"input": {"find_by": {"type": "dict", "default": "Required"}}, "output": {"type": "bool"}}'),
(245, 'agent_list', 5, '/app/src/tool/agent/agent_.py', 'Возвращает список агентов, доступных пользователю: агенты, роли которых\nпересекаются с ролью пользователя (agent_role), опционально отфильтрованные\nпо workflow. Админ видит ВСЕ агенты независимо от роли создателя.\n - user_id: активный пользователь (workflow-переменная user_id)\n - workflow_name: системное имя workflow для фильтра; пустая строка - все агенты\nReturns:\n    dict: Словарь со списком агентов, содержащий:\n        chips (str): чипсы вида [[Название1]] [[Название2]] для выбора в чате.\n        qty (int): количество найденных агентов.', '{"input": {"user_id": {"type": "int", "default": "Required"}, "workflow_name": {"type": "str", "default": ""}}, "output": {"type": "dict", "keys": {"chips": {"type": "str"}, "qty": {"type": "int"}}}}'),
(246, 'agent_remove', 5, '/app/src/tool/agent/agent_.py', 'Удаляет агента по названию (title или name), если он доступен пользователю:\nроли агента пересекаются с ролью пользователя (agent_role), опциональный\nфильтр по workflow. Админ может удалить ЛЮБОЙ агент независимо от роли\nсоздателя. Связи agent_role удаляются каскадом, agent_session отвязывается\n(SET NULL) — история переписок сохраняется.\n - title: название агента из чипса (сравнивается с agent.title и agent.name)\n - user_id: активный пользователь (workflow-переменная user_id)\n - workflow_name: системное имя workflow для фильтра; пустая строка - без фильтра\nReturns:\n    dict: Словарь с результатом удаления, содержащий:\n        removed (int): 1 - агент удален, 0 - не найден среди доступных.\n        title (str): название удаленного агента (пустая строка, если не найден).', '{"input": {"title": {"type": "str", "default": "Required"}, "user_id": {"type": "int", "default": "Required"}, "workflow_name": {"type": "str", "default": ""}}, "output": {"type": "dict", "keys": {"removed": {"type": "int"}, "title": {"type": "str"}}}}'),
(247, 'agent_workflow_id', 5, '/app/src/tool/agent/agent_workflow_.py', 'Возвращает ID workflow по его имени.', '{"input": {"name": {"type": "str", "default": "Required"}}, "output": {"type": "int"}}');

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
(3, 'user_admin', 'admin');

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
(12, 4, 4, 'return_response_text', 4, '{"prompt_user":"Команда /go найдена","transitions_after":[]}'),
(61, 8, 4, 'Подсказка', 5, '{"prompt_user": "Привет! Я Dev bot.\\n\\nДоступные команды:\\n\\n[[Экспорт ноды Dashboard]]\\n\\n[[Экспорт ноды Dating]]\\n\\n[[Экспорт ноды Detective]]", "continue_workflow": false, "transitions_after": [], "transitions_before": []}'),
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
(145, 8, 3, 'Извлечь имя ноды', 0, '{"transitions_before": [], "transitions_after": [{"variable": "text_regex_extract_145_result_str", "operator": "empty", "value": "", "step_id": "61"}], "tool_invoke": {"tool_name": "text_regex_extract", "inputs_map": {"text": "prompt_user", "pattern": "export_node_regex"}, "outputs_map": {}}}'),
(146, 8, 5, 'Критерии поиска ноды', 1, '{"transitions_before": [], "transitions_after": [], "variable_conversion": [{"variable": "export_node_find_table", "text": "node"}, {"variable": "export_node_find_criteria", "text": "{\\"name\\": \\"%text_regex_extract_145_result_str%\\"}"}]}'),
(147, 8, 3, 'Найти ноду', 2, '{"transitions_before": [], "transitions_after": [], "tool_invoke": {"tool_name": "mysql_find_one_by", "inputs_map": {"table_name": "export_node_find_table", "criteria": "export_node_find_criteria"}, "outputs_map": {}}}'),
(148, 8, 3, 'mysql_export_node_to_migration', 3, '{"transitions_before": [], "transitions_after": [], "tool_invoke": {"tool_name": "mysql_export_node_to_migration", "inputs_map": {"node_id": "mysql_find_one_by_147_result_id", "migration_file": "export_node_migration_file_empty"}, "outputs_map": {}}}'),
(149, 8, 4, 'Отчет экспорта ноды', 4, '{"transitions_before": [], "transitions_after": [], "prompt_user": "✅ Экспорт ноды «%mysql_find_one_by_147_result_name%» завершен.\\n\\nФайл: %mysql_find_one_by_147_result_migration_file%\\nТаблиц: %mysql_export_node_to_migration_148_result_tables_qty%, строк: %mysql_export_node_to_migration_148_result_rows_qty%.\\nОбновлены: %mysql_export_node_to_migration_148_result_report_str%", "continue_workflow": false}');

--

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
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
(183, 'export_node_regex', 'workflow', 'Экспорт\\s+ноды\\s+(.+)', 'Регулярка команды экспорта ноды: группа 1 - имя ноды'),
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
(24, 6, 'dev_bot', 'Dev bot', 'Служебный агент для dev-операций', 8, '{}', 'Ты служебный dev-агент. Выполняешь технические операции по командам.', 'Привет! Я Dev bot.\n\nДоступные команды:\n\n[[Экспорт ноды Dashboard]]\n\n[[Экспорт ноды Dating]]\n\n[[Экспорт ноды Detective]]', 0, 0),
(25, 6, 'workflow_tester', 'Workflow tester', 'Тестовый прогон workflow: LLM-собеседник ведет диалог с целевым workflow в цикле', 9, '{}', 'Ты отвественный исполнитель. Выполняешь все, что тебе пишут. Если в запросе написано вернуть ответ в JSON обязательно верни в JSON.', 'Привет! Я Workflow tester, использую workflow оболочку для тестирования любого workflow.\n\nНапишите любое сообщение, чтобы начать: я спрошу ноду, workflow и агента (выбор чипсами), затем сценарий тестирования (кто собеседник, о чем говорит, чего добивается) — и прогоню диалог с целевым workflow, вернув стенограмму.\n\nКоличество итераций — переменная test_iterations_limit.\n\n/start', 0, 0),
(27, NULL, 'translator', 'Переводчик', 'Служебный агент автоперевода', 10, NULL, 'Ты профессиональный переводчик. Переводишь текст точно, сохраняя смысл, стиль и тон. Возвращаешь только перевод без пояснений.', '', 0, 0),
(29, NULL, 'fact_verifier', 'Фактчекер', 'Служебный агент проверки фактов веб-поиском (крон fact_verify)', 11, NULL, 'Ты дотошный фактчекер. Проверяешь утверждения по результатам веб-поиска и исправляешь противоречия минимальной правкой.', '', 0, 0);