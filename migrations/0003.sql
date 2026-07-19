-- Детективная игра (нода Detective): генератор дел, допрос подозреваемых-агентов, вердикт.
-- Таблица detective_case + workflow detective_bot/detective_talk (агент, шаги, переменные).
-- Все вставки INSERT IGNORE: миграция безопасна и на уже засеянной вручную базе.

CREATE TABLE IF NOT EXISTS `detective_case` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_uuid` CHAR(36) NOT NULL,
    `user_id` INT NULL,
    `victim_name` CHAR(100) NOT NULL,
    `crime_description` TEXT NOT NULL,
    `guilty_suspect_name` CHAR(100) NOT NULL,
    `solution_reveal` TEXT NOT NULL,
    `solved` TINYINT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_detective_case_session` (`session_uuid`),
    CONSTRAINT `fk_detective_case_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

--

INSERT IGNORE INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(12, 4, 'detective_bot', 'Детектив-бот', 'Мастер игры: генерирует дело, создает подозреваемых-агентов, принимает финальное обвинение', 0, 0),
(13, 4, 'detective_talk', 'Допрос подозреваемого', 'Диалог с подозреваемым: отвечает в характере, опираясь на свою легенду (prompt_system)', 1, 0),
(14, 4, 'detective_suspect_create', 'Создание подозреваемого', 'Извлекает одного подозреваемого из очереди (list_shift) и создает его агента; вызывается циклом (repeat.count=4) из detective_bot', 2, 1);

INSERT IGNORE INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`) VALUES
(30, 4, 'detective_bot', 'Детектив-бот', 'Мастер детективной игры: создает дела и подозреваемых', 12, NULL, 'Ты ведущий детективной игры. Выполняешь команды буквально и возвращаешь ответ в JSON, если об этом просят.', 'Добро пожаловать в детективное агентство!\n\nДоступные команды:\n\n/new_case - начать новое дело\n/accuse - обвинить подозреваемого', 0);

INSERT IGNORE INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
(128, 'victim_name', 'workflow', NULL, 'Имя жертвы текущего дела'),
(129, 'crime_description', 'workflow', NULL, 'Описание преступления для игрока'),
(130, 'guilty_suspect_name', 'workflow', NULL, 'Имя виновного подозреваемого'),
(131, 'solution_reveal', 'workflow', NULL, 'Текст разгадки дела'),
(132, 'suspect_1_name', 'workflow', NULL, NULL),
(133, 'suspect_1_sheet', 'workflow', NULL, NULL),
(134, 'suspect_1_greeting', 'workflow', NULL, NULL),
(135, 'suspect_2_name', 'workflow', NULL, NULL),
(136, 'suspect_2_sheet', 'workflow', NULL, NULL),
(137, 'suspect_2_greeting', 'workflow', NULL, NULL),
(138, 'suspect_3_name', 'workflow', NULL, NULL),
(139, 'suspect_3_sheet', 'workflow', NULL, NULL),
(140, 'suspect_3_greeting', 'workflow', NULL, NULL),
(141, 'suspect_4_name', 'workflow', NULL, NULL),
(142, 'suspect_4_sheet', 'workflow', NULL, NULL),
(143, 'suspect_4_greeting', 'workflow', NULL, NULL),
(152, 'detective_talk_workflow_name', 'workflow', 'detective_talk', 'Имя workflow допроса для agent_workflow_id'),
(153, 'session_messages_limit', 'workflow', '20', 'Лимит истории допроса для session_messages'),
(154, 'suspects_queue', 'input', '[]', 'Очередь подозреваемых на создание (JSON-массив)'),
(155, 'node_id', 'input', NULL, 'Нода агентов-подозреваемых'),
(156, 'talk_workflow_id', 'input', NULL, 'Workflow допроса (detective_talk)'),
(157, 'victim_name', 'input', NULL, 'Имя жертвы (для системного промпта)'),
(158, 'companion_title', 'input', NULL, 'Отображаемое имя детектива-игрока'),
(159, 'user_id', 'input', NULL, 'Активный пользователь');

INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(128, 12),
(129, 12),
(130, 12),
(131, 12),
(132, 12),
(133, 12),
(134, 12),
(135, 12),
(136, 12),
(137, 12),
(138, 12),
(139, 12),
(140, 12),
(141, 12),
(142, 12),
(143, 12),
(152, 12),
(153, 13),
(154, 14),
(155, 14),
(156, 14),
(157, 14),
(158, 14),
(159, 14);

INSERT IGNORE INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(121, 12, 4, 'Вернуть список команд', 0, '{\"transitions_before\": [{\"variable\": \"prompt_user\", \"operator\": \"==\", \"value\": \"/new_case\", \"step_id\": \"122\"}, {\"variable\": \"prompt_user\", \"operator\": \"==\", \"value\": \"/accuse\", \"step_id\": \"131\"}], \"transitions_after\": [], \"prompt_user\": \"%agent_greeting%\", \"continue_workflow\": false}'),
(122, 12, 2, 'Сгенерировать дело', 1, '{\"transitions_before\": [], \"transitions_after\": [], \"llm_to_json_variable\": [{\"variable\": \"victim_name\", \"text\": \"имя жертвы\"}, {\"variable\": \"crime_description\", \"text\": \"описание преступления для игрока, без намека на виновного\"}, {\"variable\": \"guilty_suspect_name\", \"text\": \"имя виновного подозреваемого\"}, {\"variable\": \"solution_reveal\", \"text\": \"финальная разгадка дела\"}, {\"variable\": \"suspect_1_name\", \"text\": \"имя подозреваемого 1\"}, {\"variable\": \"suspect_1_sheet\", \"text\": \"легенда подозреваемого 1\"}, {\"variable\": \"suspect_1_greeting\", \"text\": \"приветствие подозреваемого 1\"}, {\"variable\": \"suspect_2_name\", \"text\": \"имя подозреваемого 2\"}, {\"variable\": \"suspect_2_sheet\", \"text\": \"легенда подозреваемого 2\"}, {\"variable\": \"suspect_2_greeting\", \"text\": \"приветствие подозреваемого 2\"}, {\"variable\": \"suspect_3_name\", \"text\": \"имя подозреваемого 3\"}, {\"variable\": \"suspect_3_sheet\", \"text\": \"легенда подозреваемого 3\"}, {\"variable\": \"suspect_3_greeting\", \"text\": \"приветствие подозреваемого 3\"}, {\"variable\": \"suspect_4_name\", \"text\": \"имя подозреваемого 4\"}, {\"variable\": \"suspect_4_sheet\", \"text\": \"легенда подозреваемого 4\"}, {\"variable\": \"suspect_4_greeting\", \"text\": \"приветствие подозреваемого 4\"}], \"prompt_user\": \"Придумай честное, разрешимое детективное дело в жанре классического детектива (как Агата Кристи). Правила:\\n\\n1. Ровно 4 подозреваемых с разными именами.\\n2. Ровно один из них виновен в убийстве.\\n3. У каждого подозреваемого есть алиби, личность, отношение к жертве и мотив (или его отсутствие).\\n4. Алиби невиновных подозреваемых логически непротиворечивы и не имеют дыр.\\n5. Алиби виновного имеет ОДНУ подходящую, но не самоочевидную нестыковку (например, упоминает деталь, которая противоречит времени/месту/показаниям другого подозреваемого) - ее можно найти, если задать точные уточняющие вопросы, но виновный сам никогда не признается напрямую.\\n6. Все подозреваемые знают общие факты дела (время, место, орудие) одинаково - не противоречь себе между персонажами.\\n7. Пиши строго на языке: %user_language%.\\n\\n=== Что нужно вернуть ===\\n- victim_name: имя жертвы\\n- crime_description: 2-4 предложения для игрока: кто жертва, где и как произошло убийство, орудие, примерное время - БЕЗ намека на виновного\\n- guilty_suspect_name: имя виновного (должно точно совпадать с одним из suspect_N_name)\\n- solution_reveal: финальная разгадка на 3-5 предложений, которая будет показана игроку ПОСЛЕ обвинения - объясняет мотив виновного и в чем именно была нестыковка в его алиби\\n- suspect_1_name, suspect_2_name, suspect_3_name, suspect_4_name: имена подозреваемых\\n- suspect_1_sheet, suspect_2_sheet, suspect_3_sheet, suspect_4_sheet: полная легенда персонажа текстом (5-8 предложений): кто он жертве, где был во время убийства (алиби), характер, как себя ведет на допросе. Для виновного - явно опиши его мотив и ОСТОРОЖНО впиши нестыковку в алиби, но не пиши прямо \'он виновен\'\\n- suspect_1_greeting, suspect_2_greeting, suspect_3_greeting, suspect_4_greeting: короткая фраза (1 предложение) в характере, которой подозреваемый встречает детектива на допросе\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format with exactly these keys: victim_name, crime_description, guilty_suspect_name, solution_reveal, suspect_1_name, suspect_1_sheet, suspect_1_greeting, suspect_2_name, suspect_2_sheet, suspect_2_greeting, suspect_3_name, suspect_3_sheet, suspect_3_greeting, suspect_4_name, suspect_4_sheet, suspect_4_greeting.\"}'),
(123, 12, 3, 'agent_workflow_id_talk', 2, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"agent_workflow_id\", \"inputs_map\": {\"name\": \"detective_talk_workflow_name\"}, \"outputs_map\": {}}}'),
(124, 12, 3, 'Собрать очередь подозреваемых', 3, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"detective_suspects_queue_build\", \"inputs_map\": {\"session_uuid\": \"session_uuid\", \"suspect_1_name\": \"suspect_1_name\", \"suspect_1_sheet\": \"suspect_1_sheet\", \"suspect_1_greeting\": \"suspect_1_greeting\", \"suspect_2_name\": \"suspect_2_name\", \"suspect_2_sheet\": \"suspect_2_sheet\", \"suspect_2_greeting\": \"suspect_2_greeting\", \"suspect_3_name\": \"suspect_3_name\", \"suspect_3_sheet\": \"suspect_3_sheet\", \"suspect_3_greeting\": \"suspect_3_greeting\", \"suspect_4_name\": \"suspect_4_name\", \"suspect_4_sheet\": \"suspect_4_sheet\", \"suspect_4_greeting\": \"suspect_4_greeting\"}, \"outputs_map\": {}}}'),
(140, 12, 6, 'Создать подозреваемых (цикл)', 4, '{\"transitions_before\": [], \"transitions_after\": [], \"workflow_invoke\": {\"workflow_id\": 14, \"inputs_map\": {\"suspects_queue\": \"detective_suspects_queue_build_124_result_list\", \"node_id\": \"node_id\", \"talk_workflow_id\": \"agent_workflow_id_123_result_int\", \"victim_name\": \"victim_name\", \"companion_title\": \"companion_title\", \"user_id\": \"user_id\"}, \"outputs_map\": {\"list_shift_137_result_rest\": \"detective_suspects_queue_build_124_result_list\"}, \"repeat\": {\"count\": 4}}}'),
(129, 12, 3, 'Сохранить дело', 8, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"detective_case_create\", \"inputs_map\": {\"session_uuid\": \"session_uuid\", \"user_id\": \"user_id\", \"victim_name\": \"victim_name\", \"crime_description\": \"crime_description\", \"guilty_suspect_name\": \"guilty_suspect_name\", \"solution_reveal\": \"solution_reveal\"}, \"outputs_map\": {}}}'),
(130, 12, 4, 'Дело открыто', 9, '{\"transitions_before\": [], \"transitions_after\": [], \"prompt_user\": \"🕵️ Открыто новое дело\\n\\nЖертва: %victim_name%\\n\\n%crime_description%\\n\\nПодозреваемые:\\n[[%suspect_1_name%]] [[%suspect_2_name%]] [[%suspect_3_name%]] [[%suspect_4_name%]]\\n\\nВыбери подозреваемого в списке слева и начни допрос. Когда будешь готов назвать виновного, напиши /accuse.\", \"continue_workflow\": false}'),
(131, 12, 3, 'Список подозреваемых дела', 10, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"detective_case_suspects_list\", \"inputs_map\": {\"session_uuid\": \"session_uuid\"}, \"outputs_map\": {}}}'),
(132, 12, 4, 'Спросить кого обвиняем', 11, '{\"transitions_before\": [], \"transitions_after\": [], \"prompt_user\": \"Кого ты обвиняешь в убийстве %detective_case_suspects_list_131_result_victim_name%?\\n\\n%detective_case_suspects_list_131_result_chips%\", \"continue_workflow\": true}'),
(133, 12, 3, 'Проверить вердикт', 12, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"detective_case_verdict_check\", \"inputs_map\": {\"session_uuid\": \"session_uuid\", \"accused_name\": \"prompt_user\"}, \"outputs_map\": {}}}'),
(134, 12, 4, 'Вердикт', 13, '{\"transitions_before\": [], \"transitions_after\": [], \"prompt_user\": \"%if detective_case_verdict_check_133_result_correct%✅ Верно! Убийца — %detective_case_verdict_check_133_result_guilty_suspect_name%.\\n\\n%detective_case_verdict_check_133_result_solution_reveal%%else%❌ Мимо. Настоящий убийца — %detective_case_verdict_check_133_result_guilty_suspect_name%.\\n\\n%detective_case_verdict_check_133_result_solution_reveal%%endif%\\n\\nЧтобы начать новое дело, напиши /new_case.\", \"continue_workflow\": false}'),
(135, 13, 3, 'session_messages', 0, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"session_messages\", \"inputs_map\": {\"session_uuid\": \"session_uuid\", \"limit\": \"session_messages_limit\"}, \"outputs_map\": {}}}'),
(136, 13, 1, 'Ответ подозреваемого', 1, '{\"transitions_before\": [], \"transitions_after\": [], \"prompt_user\": \"%if session_messages_135_result_str%=== История допроса ===\\n%session_messages_135_result_str%\\n\\n%endif%=== %companion_title% спрашивает ===\\n%prompt_user%\\n\\nОтветь коротко (1-3 предложения), от первого лица, оставаясь в характере. Отвечай на языке: %user_language%.\"}'),
(137, 14, 3, 'Извлечь из очереди', 0, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"list_shift\", \"inputs_map\": {\"items\": \"suspects_queue\"}, \"outputs_map\": {}}}'),
(138, 14, 5, 'Собрать системный промпт', 1, '{\"transitions_before\": [], \"transitions_after\": [], \"variable_conversion\": [{\"variable\": \"current_suspect_prompt_system\", \"text\": \"Ты подозреваемый по имени %list_shift_137_result_name% в деле об убийстве %victim_name%. Тебя допрашивает детектив (%companion_title%). Отвечай от первого лица, коротко и естественно, как в живом разговоре при допросе (1-3 предложения). Никогда не выходи из роли и не признавайся, что ты вымышленный персонаж. Если невиновен - говоришь правду, можешь немного нервничать от неприятных вопросов. Если виновен - отрицаешь причастность и не признаешься напрямую, но при точных уточняющих вопросах об алиби можешь путаться в деталях. Никогда сам не заявляешь \'я не виновен\' без повода - отвечай строго по существу заданного вопроса. Отвечай на языке: %user_language%.\\n\\n=== Твоя легенда ===\\n%list_shift_137_result_sheet%\"}]}'),
(139, 14, 3, 'Создать агента', 2, '{\"transitions_before\": [], \"transitions_after\": [], \"tool_invoke\": {\"tool_name\": \"agent_create_or_update\", \"inputs_map\": {\"name\": \"list_shift_137_result_agent_name\", \"title\": \"list_shift_137_result_name\", \"node_id\": \"node_id\", \"workflow_id\": \"talk_workflow_id\", \"prompt_system\": \"current_suspect_prompt_system\", \"greeting\": \"list_shift_137_result_greeting\", \"user_id\": \"user_id\"}, \"outputs_map\": {}}}');
