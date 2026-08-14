-- Быстрое планирование: меньше ходов менеджера (workflow #55)
--
-- Зачем вручную: правка данных (`agent_workflow_step`.`metadata`), а не схемы.
--
-- Что было: планирование задачи #462 (правка одной строки SQL) заняло 26 минут,
-- трейс #425 по шагам:
--   разведка 164с, план 122с, JSON плана 84с, судья 120с, JSON судьи 76с,
--   переделка плана 481с, JSON 38с, судья 82с, JSON 44с, цели 38с, JSON 32с,
--   судья целей 64с, JSON 32с, разбиение 34с, JSON 42с, судья 44с, JSON 54с.
-- Из них 402с (26%) — восемь ходов «Верни тот же ответ в машинном виде»: агент
-- уже всё написал, его просят переписать то же самое JSON-ом отдельным вызовом.
-- Ещё 645с (42%) — круг переделки плана, который судья забраковал за то, что
-- план «не назвал конкретных существующих паттернов»: правку `ORDER BY` это
-- лучше не сделало.
--
-- Отдельно: разведка ни разу не спросила, нужна ли работа вообще. По задаче #560
-- («проекты на странице Команда сортировать по position») разведка сама нашла, что
-- `team_project.py:67` уже сортирует по `position ASC`, и всё равно ушла планировать
-- правку. Первый вопрос разведки теперь — «а надо ли это делать»: описанное могло
-- быть уже сделано, и тогда весь конвейер отработает впустую.
--
-- Что делаем:
--   0. Разведка первым делом сверяет описание с кодом и отвечает `task_done`.
--      Уже сделано — план, цели и разбиение сводятся к подтверждению поведения,
--      судьи плана и разбиения пропускаются.
--   1. Машинный ответ просим сразу в основном ходе — блоком ```json в конце.
--      `claude_shell_call` вытаскивает JSON из текста (`_payload_parse`), так что
--      отдельный ход не нужен. Старые шаги «Промпт JSON: …» остаются на месте как
--      переспрос: не разобрали JSON — уходим на них, дальше всё как раньше.
--   2. Разведка оценивает размер работы (`task_size`). У точечной задачи
--      (small) судья плана и судья разбиения пропускаются: их придирки стоят
--      дороже, чем ловят. Судья целей работает всегда — по целям принимает QA.
--   3. Промпты просят краткость и запрещают судьям браковать за стиль:
--      `no` — только когда без правки план/цели/разбиение не выполнимы.
--
-- Ожидаемо: точечная задача — 5 ходов менеджера вместо 14.
--
-- Идемпотентность: текстовые правки ищут исходную формулировку и на повторном
-- прогоне ничего не находят; JSON-правки перезаписывают значение целиком.
--
-- На проде перед прогоном снять свежий бэкап через /admin/backup.

-- ─── До: строки, которые тронем ───────────────────────────────────────────────
SELECT `id`, `position`, `title`
FROM `agent_workflow_step`
WHERE `workflow_id` = 55
  AND `id` IN (422, 423, 405, 406, 409, 410, 412, 413, 416, 417, 424, 425, 428, 429,
               495, 499, 503)
ORDER BY `position`;


-- ══════════════════════════════════════════════════════════════════════════════
-- 1. Разведка: сначала «а надо ли делать», потом краткость и размер работы
-- ══════════════════════════════════════════════════════════════════════════════

-- Первым делом разведка должна ответить, нужна ли работа вообще: описанное может
-- быть уже реализовано, и тогда правки не нужны. Пункты перенумеровываем с конца —
-- иначе следующий REPLACE попал бы в номер, поставленный предыдущим.
UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(`metadata`,
    '4. Сформулируй вопросы, ответы на которые нужны',
    '5. Сформулируй вопросы, ответы на которые нужны')
WHERE `id` = 422;

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(`metadata`,
    '3. Найди в проекте похожие места',
    '4. Найди в проекте похожие места')
WHERE `id` = 422;

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(`metadata`,
    '2. По тегам определи тематику',
    '3. По тегам определи тематику')
WHERE `id` = 422;

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(`metadata`,
    'Что сделать:\\n1. Разбей описание на теги',
    'Что сделать:\\n1. Проверь, нужно ли вообще делать эту задачу. Описанное может быть уже\\n   сделано — тогда править нечего, и весь конвейер отработает впустую. Найди место,\\n   которое отвечает за нужное поведение, и сверь его с описанием. Путь к файлу и номер\\n   строки обязательны: «похоже, работает» — не ответ. Вышло, что уже сделано — так и\\n   напиши, остальные пункты тогда делай коротко.\\n2. Разбей описание на теги')
WHERE `id` = 422;

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    'Отвечай обычным текстом: тематика и теги, найденные в проекте паттерны\\nс путями к файлам, затем вопросы — по одному в строке. JSON сейчас не нужен.',
    'Отвечай обычным текстом и коротко: теги — одной строкой, тематика — 1-2 предложения,\\nпаттерны — до 5 пунктов с путями к файлам, вопросы — до 5, по одному в строке.\\nФайлов открывай не больше десяти: важнее точное попадание, чем полнота обзора.\\n\\nОтвет заверши вердиктом — блоком:\\n```json\\n{\\"task_done\\": \\"no\\", \\"task_size\\": \\"small\\"}\\n```\\ntask_done — yes, если нужное поведение уже реализовано и менять нечего.\\ntask_size — small при правке в одном-трёх файлах без изменений схемы БД и\\nконтракта API, иначе large. Сомневаешься — large.')
WHERE `id` = 422;

-- Вердикт разведки кладём в переменные: по ним ниже пропускаются лишние судьи.
UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.task_size', 'task_size',
                          '$.tool_invoke.outputs_map.task_done', 'task_done')
WHERE `id` = 423;


-- ══════════════════════════════════════════════════════════════════════════════
-- 2. План: JSON сразу, короче, и пропуск судьи для точечной задачи
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    '- plan_text: нумерованные шаги, 5-15 строк, конкретно — что делать и где (пути к файлам).\\n- Последний шаг — проверка результата.\\n- На подзадачи сейчас не дроби: разбиение — отдельный шаг после целей.\\n\\nОтвечай обычным текстом. JSON я попрошу отдельным шагом — сейчас его не пиши.',
    '- Нумерованные шаги, конкретно — что делать и где (пути к файлам).\\n- Шагов столько, сколько нужно: точечная правка — 3-5, крупная работа — до 12.\\n  Не добирай шаги ради объёма.\\n- Вопросы разведки остались без ответа: отвечать на них некому. Не переноси их\\n  в план шагами «проверить», «убедиться», «уточнить» — реши сам и пиши действие.\\n- Разведка нашла, что нужное поведение уже реализовано? Тогда план — один-два шага:\\n  подтвердить поведение на живом стенде и закрыть задачу. Кода не менять, работу\\n  не выдумывать.\\n- Последний шаг — проверка результата.\\n- На подзадачи сейчас не дроби: разбиение — отдельный шаг после целей.\\n\\nОтвет заверши тем же планом в машинном виде — блоком:\\n```json\\n{\\"task_plan_json\\": {\\"plan_text\\": \\"1. шаг\\\\n2. шаг\\"}}\\n```\\nplan_text — обычный текст, внутри него запрещены двойные кавычки и фрагменты\\nкода. Перед блоком ничего пересказывать не нужно: план целиком лежит внутри.')
WHERE `id` = 405;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.payload_json', 'task_plan_json',
                          '$.transitions_after', CAST('[
    {"variable": "manager_status",  "operator": "!=",    "value": "answered", "step_id": "420"},
    {"variable": "task_plan_json",  "operator": "empty", "value": "",         "step_id": "494"},
    {"variable": "task_done",       "operator": "==",    "value": "yes",      "step_id": "412"},
    {"variable": "task_size",       "operator": "==",    "value": "small",    "step_id": "412"},
    {"variable": "task_plan_json",  "operator": "!=",    "value": "",         "step_id": "407"}
]' AS JSON))
WHERE `id` = 406;

-- Переспрос JSON-ом тоже должен пропускать судью у точечной задачи.
UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.transitions_after', CAST('[
    {"variable": "manager_status", "operator": "!=",    "value": "answered", "step_id": "420"},
    {"variable": "task_plan_json", "operator": "empty", "value": "",         "step_id": "457"},
    {"variable": "task_done",      "operator": "==",    "value": "yes",      "step_id": "412"},
    {"variable": "task_size",      "operator": "==",    "value": "small",    "step_id": "412"}
]' AS JSON))
WHERE `id` = 495;


-- ══════════════════════════════════════════════════════════════════════════════
-- 3. Судья плана: JSON сразу, брак только по существу
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    'Не выполнен хотя бы один пункт — plan_ok=no. Замечания давай новыми находками и заданиями\\nна доработку, а не пересказом плана.\\n\\nОтвечай обычным текстом. JSON я попрошу отдельным шагом — сейчас его не пиши.',
    'plan_ok=no ставь только тогда, когда по плану работу не сделать: шаг ведёт не туда,\\nпропущено обязательное действие, порядок шагов неисполним. Пожелания «раскрыть\\nподробнее», «назвать больше паттернов», «добавить на всякий случай» — это plan_ok=yes\\nс замечанием: круг переделки стоит дороже, чем такая правка приносит.\\n\\nЗамечания давай находками и заданиями на доработку, а не пересказом плана,\\nи уложись в 10 строк.\\n\\nОтвет заверши блоком:\\n```json\\n{\\"plan_ok\\": \\"yes\\", \\"plan_critique_new\\": \\"замечания одним абзацем\\"}\\n```\\nplan_ok — только yes или no. plan_critique_new — обычный текст без двойных кавычек.')
WHERE `id` = 409;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.plan_ok', 'plan_ok',
                          '$.tool_invoke.outputs_map.plan_critique_new', 'plan_critique_new',
                          '$.transitions_after', CAST('[
    {"variable": "manager_status", "operator": "!=",    "value": "answered",                "step_id": "412"},
    {"variable": "plan_ok",        "operator": "empty", "value": "",                        "step_id": "496"},
    {"variable": "plan_ok",        "operator": "==",    "value": "yes",                     "step_id": "412"},
    {"variable": "plan_iteration", "operator": ">=",    "value": "%max_plan_iterations%",   "step_id": "412"},
    {"variable": "plan_ok",        "operator": "!=",    "value": "yes",                     "step_id": "411"}
]' AS JSON))
WHERE `id` = 410;


-- ══════════════════════════════════════════════════════════════════════════════
-- 4. Цели: JSON сразу, число целей по размеру работы
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    '- Обязательно минимум 1 цель, всего 2-7.',
    '- Целей столько, сколько нужно: точечная правка — 1-2, крупная работа — до 5.\\n  Пустой список недопустим, но и добирать цели до круглого числа не надо.\\n- Цель, которую задача не затрагивает («на других страницах ничего не сломалось»,\\n  «остальное работает как раньше»), не цель — такие не пиши.\\n- Цели — про то, что просил заказчик. Своих требований не добавляй: их никто не\\n  заказывал, а проверять и чинить их придётся наравне с настоящими.\\n- Две цели, которые проверяются одним и тем же действием, — это одна цель.\\n- Разведка нашла, что поведение уже реализовано? Тогда цель ровно одна: увидеть\\n  это поведение на живом стенде.')
WHERE `id` = 412;

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    'Отвечай обычным текстом. JSON я попрошу отдельным шагом — сейчас его не пиши.',
    'Ответ заверши тем же списком в машинном виде — блоком:\\n```json\\n{\\"task_goals_json\\": [\\"цель 1\\", \\"цель 2\\"]}\\n```\\nВсегда массив строк: одна цель — массив из одной строки. Пустой массив\\nнедопустим. Цели — обычный текст, без двойных кавычек.')
WHERE `id` = 412;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.payload_json', 'task_goals_json',
                          '$.transitions_after', CAST('[
    {"variable": "manager_status",   "operator": "!=",    "value": "answered", "step_id": "421"},
    {"variable": "task_goals_json",  "operator": "empty", "value": "",         "step_id": "498"},
    {"variable": "task_goals_json",  "operator": "==",    "value": "[]",       "step_id": "498"},
    {"variable": "task_goals_json",  "operator": "!=",    "value": "",         "step_id": "414"}
]' AS JSON))
WHERE `id` = 413;


-- ══════════════════════════════════════════════════════════════════════════════
-- 5. Судья целей: JSON сразу, брак только по существу
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    '1. Целей 2-7, каждая — одна строка без нумерации.',
    '1. Целей 1-5 — по размеру работы, каждая одна строка без нумерации.')
WHERE `id` = 416;

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    'Не выполнен хотя бы один пункт — goals_ok=no. Замечания давай новыми находками, а не\\nпересказом списка.\\n\\nОтвечай обычным текстом. JSON я попрошу отдельным шагом — сейчас его не пиши.',
    'goals_ok=no ставь, когда список нельзя принять как есть: пустой, есть дубль, цель\\nнепроверяема, потеряна цель заказчика. Пожелания «добавить ещё проверок на всякий\\nслучай» — это goals_ok=yes с замечанием.\\n\\nЗамечания давай находками, а не пересказом списка, и уложись в 10 строк.\\n\\nОтвет заверши блоком:\\n```json\\n{\\"goals_ok\\": \\"yes\\", \\"goals_critique_new\\": \\"замечания одним абзацем\\"}\\n```\\ngoals_ok — только yes или no. goals_critique_new — текст без двойных кавычек.')
WHERE `id` = 416;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.goals_ok', 'goals_ok',
                          '$.tool_invoke.outputs_map.goals_critique_new', 'goals_critique_new',
                          '$.transitions_after', CAST('[
    {"variable": "manager_status",  "operator": "!=",    "value": "answered",                "step_id": "424"},
    {"variable": "goals_ok",        "operator": "empty", "value": "",                        "step_id": "500"},
    {"variable": "goals_ok",        "operator": "==",    "value": "yes",                     "step_id": "424"},
    {"variable": "goals_iteration", "operator": ">=",    "value": "%max_goals_iterations%",  "step_id": "424"},
    {"variable": "goals_ok",        "operator": "!=",    "value": "yes",                     "step_id": "418"}
]' AS JSON))
WHERE `id` = 417;


-- ══════════════════════════════════════════════════════════════════════════════
-- 6. Разбиение: JSON сразу, пропуск судьи для точечной задачи
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    'Отвечай обычным текстом. JSON я попрошу отдельным шагом — сейчас его не пиши.',
    'Разведка нашла, что поведение уже реализовано? Тогда подзадача ровно одна —\\nподтвердить поведение и закрыть задачу.\\n\\nОтвет заверши тем же разбиением в машинном виде — блоком:\\n```json\\n{\\"task_subtasks_json\\": [{\\"title\\": \\"название\\", \\"description\\": \\"что сделать\\", \\"plan\\": \\"- шаг\\\\n- шаг\\", \\"goals\\": [\\"цель\\"]}]}\\n```\\nВсегда массив объектов: одна подзадача — массив из одного объекта. Пустой массив\\nнедопустим. У каждого объекта ровно четыре поля: title, description, plan, goals;\\ngoals — массив строк. Тексты без двойных кавычек и фрагментов кода.')
WHERE `id` = 424;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.payload_json', 'task_subtasks_json',
                          '$.transitions_after', CAST('[
    {"variable": "manager_status",     "operator": "!=",    "value": "answered", "step_id": "431"},
    {"variable": "task_subtasks_json", "operator": "empty", "value": "",         "step_id": "502"},
    {"variable": "task_subtasks_json", "operator": "==",    "value": "[]",       "step_id": "502"},
    {"variable": "task_done",          "operator": "==",    "value": "yes",      "step_id": "419"},
    {"variable": "task_size",          "operator": "==",    "value": "small",    "step_id": "419"},
    {"variable": "task_subtasks_json", "operator": "!=",    "value": "",         "step_id": "426"}
]' AS JSON))
WHERE `id` = 425;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.transitions_after', CAST('[
    {"variable": "manager_status",     "operator": "!=",    "value": "answered", "step_id": "431"},
    {"variable": "task_subtasks_json", "operator": "empty", "value": "",         "step_id": "463"},
    {"variable": "task_subtasks_json", "operator": "==",    "value": "[]",       "step_id": "463"},
    {"variable": "task_done",          "operator": "==",    "value": "yes",      "step_id": "419"},
    {"variable": "task_size",          "operator": "==",    "value": "small",    "step_id": "419"}
]' AS JSON))
WHERE `id` = 503;


-- ══════════════════════════════════════════════════════════════════════════════
-- 7. Судья разбиения: JSON сразу, брак только по существу
-- ══════════════════════════════════════════════════════════════════════════════

UPDATE `agent_workflow_step`
SET `metadata` = REPLACE(
    `metadata`,
    'Не выполнен хотя бы один пункт — split_ok=no. Замечания давай новыми находками и\\nзаданиями на доработку, а не пересказом списка.\\n\\nОтвечай обычным текстом. JSON я попрошу отдельным шагом — сейчас его не пиши.',
    'split_ok=no ставь, когда разбиение нельзя отдать в работу: пустой список, у подзадачи\\nнет плана или целей, кусок нельзя сдать отдельно, потерян кусок работы. Пожелания\\n«расписать подробнее» — это split_ok=yes с замечанием.\\n\\nЗамечания давай находками и заданиями на доработку, и уложись в 10 строк.\\n\\nОтвет заверши блоком:\\n```json\\n{\\"split_ok\\": \\"yes\\", \\"split_critique_new\\": \\"замечания одним абзацем\\"}\\n```\\nsplit_ok — только yes или no. split_critique_new — текст без двойных кавычек.')
WHERE `id` = 428;

UPDATE `agent_workflow_step`
SET `metadata` = JSON_SET(CAST(`metadata` AS JSON),
                          '$.tool_invoke.outputs_map.split_ok', 'split_ok',
                          '$.tool_invoke.outputs_map.split_critique_new', 'split_critique_new',
                          '$.transitions_after', CAST('[
    {"variable": "manager_status",  "operator": "!=",    "value": "answered",               "step_id": "419"},
    {"variable": "split_ok",        "operator": "empty", "value": "",                       "step_id": "504"},
    {"variable": "split_ok",        "operator": "==",    "value": "yes",                    "step_id": "419"},
    {"variable": "split_iteration", "operator": ">=",    "value": "%max_split_iterations%", "step_id": "419"},
    {"variable": "split_ok",        "operator": "!=",    "value": "yes",                    "step_id": "430"}
]' AS JSON))
WHERE `id` = 429;


-- ─── После: проверить, что правила и переходы на месте ────────────────────────
SELECT `id`,
       `metadata` LIKE '%нужно ли вообще делать эту задачу%' AS `has_need_check`,
       `metadata` LIKE '%task_size%'                       AS `has_size`,
       `metadata` LIKE '%Ответ заверши%'                   AS `has_json_inline`,
       `metadata` NOT LIKE '%JSON я попрошу отдельным шагом%' AS `no_old_tail`
FROM `agent_workflow_step`
WHERE `id` IN (422, 405, 409, 412, 416, 424, 428)
ORDER BY `id`;

SELECT `id`, JSON_LENGTH(CAST(`metadata` AS JSON), '$.transitions_after') AS `transitions`,
       JSON_LENGTH(CAST(`metadata` AS JSON), '$.tool_invoke.outputs_map') AS `outputs`
FROM `agent_workflow_step`
WHERE `id` IN (423, 406, 410, 413, 417, 425, 429, 495, 503)
ORDER BY `id`;
