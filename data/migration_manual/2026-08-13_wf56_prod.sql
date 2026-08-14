-- WF#56 «Task: Разработка подзадачи» и агент `task_dev_developer` — перенос на прод
--
-- Зачем вручную: это данные, а не схема. Workflow и агенты живут в таблицах
-- (`agent_workflow`, `agent_workflow_step`, `agent`), деплой их не везёт: он собирает
-- образ и поднимает контейнеры, базу не трогает. Локально WF#56 собран на странице
-- /admin/workflow, на прод его переносим этим скриптом.
--
-- Что везём (пять таблиц, порядок обязателен — FK):
--   1. agent_workflow_variable          — 259 task_shell_role, 260 task_shell_work_dir,
--                                          262 max_dev_iterations (на проде их нет, MAX(id) = 195)
--   2. agent_workflow                    — строка id = 56, node_id = 6 (Dashboard, на проде есть)
--   3. agent_workflow_step               — 12 шагов id 432..443, type_id 3/4/5 совпадают с прод
--   4. agent_workflow_variable_workflow  — три связи переменных с workflow 56
--   5. agent                             — id 113 `task_dev_developer`, workflow_id = 56
--
-- Явные id, а не автоинкремент: так номера окружений совпадают, и ссылка «WF#56» значит
-- на проде то же, что локально. Дыра в автоинкременте (прод стоит на 28) безвредна.
--
-- Идемпотентность: ON DUPLICATE KEY UPDATE переписывает строку целиком, повторный прогон
-- просто ещё раз выравнивает прод по локальной версии. REPLACE брать нельзя: он удаляет
-- строку, а `agent_workflow_step`.`workflow_id` висит на FK с ON DELETE SET NULL —
-- REPLACE в `agent_workflow` обнулил бы привязку всех шагов.
--
-- Инструменты шагов (`claude_shell_call`, `counter_increment`) на проде уже есть —
-- проверено перед выпуском, id 9598 и 9655.
--
-- Перед прогоном: снять свежий бэкап через /admin/backup.
--
-- ВАЖНО: сам конвейер задач на проде не заработает от одного этого скрипта — там код
-- ветки master (`src/project/task/task_agent.py` вместо task_agent_developer/qa) и нет
-- ни WF#55, ни WF#57. Скрипт кладёт определение WF#56 в базу заранее, чтобы после
-- деплоя ветки task/337 разработчик поднялся без ручной сборки workflow.

-- ─── До: что уже есть на проде ────────────────────────────────────────────────
SELECT (SELECT COUNT(*) FROM `agent_workflow` WHERE `id` = 56)             AS `wf56`,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = 56) AS `steps56`,
       (SELECT COUNT(*) FROM `agent` WHERE `name` = 'task_dev_developer')  AS `agent_dev`,
       (SELECT COUNT(*) FROM `node` WHERE `id` = 6)                        AS `node6`,
       (SELECT COUNT(*) FROM `tool` WHERE `name` IN ('claude_shell_call', 'counter_increment')) AS `tools`;

-- ─── 1. Переменные workflow ───────────────────────────────────────────────────
INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES (259,'task_shell_role','workflow','manager','Роль карточки команды, чья shell-оболочка выполняет шаги планирования')
    ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `type` = VALUES(`type`), `default` = VALUES(`default`), `description` = VALUES(`description`);

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES (260,'task_shell_work_dir','workflow','','Каталог проекта: адресует шаги планирования в оболочку своего проекта')
    ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `type` = VALUES(`type`), `default` = VALUES(`default`), `description` = VALUES(`description`);

INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES (262,'max_dev_iterations','workflow','1','Максимум кругов самопроверки разработчика (workflow task_dev_developer)')
    ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `type` = VALUES(`type`), `default` = VALUES(`default`), `description` = VALUES(`description`);

-- ─── 2. Сам workflow ──────────────────────────────────────────────────────────
INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `group_name`, `subflow`) VALUES (56,6,'task_dev_developer','Task: Разработка подзадачи','Выполняет одну подзадачу через оболочку разработчика с самопроверкой',0,'Проекты/Task',0)
    ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `subflow` = VALUES(`subflow`);

-- ─── 3. Шаги workflow (12 штук, position 0..11) ───────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (432,56,5,'Инициализация',0,'{\"variable_conversion\": [{\"variable\": \"dev_critique\", \"text\": \"\"}, {\"variable\": \"dev_critique_new\", \"text\": \"\"}, {\"variable\": \"dev_iteration\", \"text\": \"0\"}, {\"variable\": \"dev_recon\", \"text\": \"\"}, {\"variable\": \"dev_plan\", \"text\": \"\"}, {\"variable\": \"dev_report_json\", \"text\": \"\"}, {\"variable\": \"dev_ok\", \"text\": \"\"}, {\"variable\": \"dev_status\", \"text\": \"\"}, {\"variable\": \"dev_error\", \"text\": \"\"}], \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (433,56,5,'Промпт: разбор подзадачи',1,'{\"variable_conversion\": [{\"variable\": \"developer_prompt\", \"text\": \"Ты разработчик в этом проекте. Тебе поручена одна подзадача из плана.\\nСейчас только разбор: код НЕ меняй, файлы не правь, коммитов не делай.\\n\\n=== ЗАДАЧА ЦЕЛИКОМ ===\\nНазвание: %task_title%\\n\\nОписание:\\n%task_description%\\n\\n=== ПЛАН ЗАДАЧИ ===\\n%if task_plan_current%%task_plan_current%%else%не задан%endif%\\n\\n=== ЦЕЛИ ЗАДАЧИ ===\\n%if task_goals%%task_goals%%else%не заданы%endif%\\n\\n=== ТВОЯ ПОДЗАДАЧА (только она) ===\\n#%subtask_id% %subtask_title%\\n\\n%subtask_description%\\n\\n%if subtask_plan%=== ПЛАН ТВОЕЙ ПОДЗАДАЧИ ===\\n%subtask_plan%\\n\\n%endif%%if subtask_goals%=== ЦЕЛИ ТВОЕЙ ПОДЗАДАЧИ (по ним её примут) ===\\n%subtask_goals%\\n\\n%endif%%if task_last_error%=== ПРЕДЫДУЩАЯ ПОПЫТКА НЕ ПРОШЛА ПРОВЕРКУ QA ===\\n%task_last_error%\\n\\nРазбирайся с этой ошибкой, а не начинай подзадачу заново: рабочее уже сделано.\\n\\n%endif%Что сделать:\\n1. Найди места, которых подзадача касается, — конкретные пути к файлам и функции,\\n   а не общие слова. Посмотри, как рядом решены похожие задачи.\\n2. Прочитай правила проекта, которые тут действуют: CLAUDE.md и нужные файлы\\n   .claude/docs/ и .claude/docs-common/ (именование, размещение кода, схема БД,\\n   API, фронтенд). Назови те правила, что относятся к этой подзадаче.\\n3. Наметь минимальное изменение: какие файлы меняешь, что в них добавляешь,\\n   чем проверишь результат.\\n4. Отдельно назови, что в подзадачу НЕ входит и чего ты трогать не будешь.\\n\\nОтветь ОДНИМ JSON-объектом, без markdown и без текста вокруг:\\n{\\\"dev_recon\\\": \\\"файлы, паттерны и правила проекта, на которые опираешься\\\", \\\"dev_plan\\\": \\\"ход работы по шагам: файл — что меняю — чем проверю\\\"}\"}], \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (434,56,3,'Разработчик: разбор',2,'{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"developer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_600\"}, \"outputs_map\": {\"error\": \"dev_error\", \"status\": \"dev_status\", \"dev_recon\": \"dev_recon\", \"dev_plan\": \"dev_plan\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"dev_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"443\"}]}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (435,56,5,'Промпт: реализация',3,'{\"variable_conversion\": [{\"variable\": \"developer_prompt\", \"text\": \"Ты разработчик в этом проекте. Выполни свою подзадачу целиком.\\n\\n=== ЗАДАЧА ЦЕЛИКОМ ===\\nНазвание: %task_title%\\n\\nОписание:\\n%task_description%\\n\\n=== ПЛАН ЗАДАЧИ ===\\n%if task_plan_current%%task_plan_current%%else%не задан%endif%\\n\\n=== ЦЕЛИ ЗАДАЧИ ===\\n%if task_goals%%task_goals%%else%не заданы%endif%\\n\\n=== ТВОЯ ПОДЗАДАЧА (только она) ===\\n#%subtask_id% %subtask_title%\\n\\n%subtask_description%\\n\\n%if subtask_plan%=== ПЛАН ТВОЕЙ ПОДЗАДАЧИ ===\\n%subtask_plan%\\n\\n%endif%%if subtask_goals%=== ЦЕЛИ ТВОЕЙ ПОДЗАДАЧИ (по ним её примут) ===\\n%subtask_goals%\\n\\n%endif%=== ТВОЙ РАЗБОР ===\\n%dev_recon%\\n\\n=== НАМЕЧЕННЫЙ ХОД РАБОТЫ ===\\n%dev_plan%\\n\\n%if task_last_error%=== ЧТО НЕ ПРОШЛО QA В ПРОШЛЫЙ РАЗ ===\\n%task_last_error%\\n\\n%endif%%if dev_critique%=== ЗАМЕЧАНИЯ САМОПРОВЕРКИ, ИХ НУЖНО ЗАКРЫТЬ ===\\n%dev_critique%\\n\\nДоделай начатое по этим замечаниям, а не переписывай всё заново.\\n\\n%endif%Правила работы, они не обсуждаются:\\n- Делаешь только свою подзадачу. Соседние подзадачи плана не трогаешь: их делают\\n  в своих кругах, и чужие правки сорвут проверку QA.\\n- Код пишешь по правилам проекта из CLAUDE.md и .claude/docs/: именование с\\n  префиксом модуля, приватные функции внизу файла, файлы небольшие.\\n- Схема БД меняется только в migrations/0001.sql. Данные — через Seed UI или\\n  скрипт в data/migration_manual/. Прод и общие системы не трогаешь.\\n- Работаешь ТОЛЬКО в своей ветке %subtask_branch%: git checkout -b %subtask_branch%\\n  (или git checkout %subtask_branch%, если она уже есть). В master не коммитишь и\\n  master не мержишь: слияние делает человек, приняв merge request.\\n- После правки .py перезапусти uvicorn (docker compose restart uvicorn), иначе QA\\n  проверит старый код. Правки шаблонов, JS и CSS перезапуска не требуют.\\n- Проверь сделанное сам: синтаксис изменённых файлов, grep по старым ссылкам,\\n  прогон нужных тестов. Полный набор тестов гоняет QA после тебя.\\n\\nРабота не закончена, пока её негде посмотреть. Проверив себя, доведи её до merge request:\\n1. git add по изменённым файлам и git commit; первая строка сообщения —\\n   «task/%subtask_id%: что сделано».\\n2. git push -u origin %subtask_branch%.\\n3. Открой merge request в master:\\n   gh pr create --base master --head %subtask_branch% --title \\\"task/%subtask_id%: кратко о сделанном\\\" --body \\\"что сделано и чем проверял\\\"\\n   Если merge request на эту ветку уже открыт (доработка после QA), второй не заводи —\\n   хватит новых коммитов в ту же ветку, адрес возьми командой\\n   gh pr view %subtask_branch% --json url -q .url\\n4. Полный адрес merge request верни полем mr_url. По нему человек смотрит работу со\\n   страницы задач; пустое поле — работа считается недоделанной.\\n\\nОтветь ОДНИМ JSON-объектом, без markdown и без текста вокруг:\\n{\\\"dev_report_json\\\": {\\\"ok\\\": true, \\\"summary\\\": \\\"что сделано, по шагам\\\", \\\"files\\\": [\\\"путь/к/файлу\\\"], \\\"branch\\\": \\\"%subtask_branch%\\\", \\\"mr_url\\\": \\\"полный адрес merge request\\\", \\\"checks\\\": \\\"чем проверял и с каким результатом\\\", \\\"error\\\": \\\"почему не сделано, если ok=false\\\"}}\\nok=false ставь только если подзадачу выполнить не удалось; тогда в error — причина.\"}], \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (436,56,3,'Разработчик: реализация',4,'{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"developer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_1800\"}, \"outputs_map\": {\"error\": \"dev_error\", \"status\": \"dev_status\", \"payload_json\": \"dev_report_json\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"dev_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"443\"}, {\"variable\": \"dev_report_json\", \"operator\": \"empty\", \"value\": \"\", \"step_id\": \"443\"}]}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (437,56,3,'Счётчик кругов самопроверки',5,'{\"tool_invoke\": {\"tool_name\": \"counter_increment\", \"inputs_map\": {\"value\": \"dev_iteration\"}, \"outputs_map\": {}}, \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (438,56,5,'Обновить счётчик самопроверки',6,'{\"variable_conversion\": [{\"variable\": \"dev_iteration\", \"text\": \"%counter_increment_437_result_int%\"}], \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (439,56,5,'Промпт: самопроверка',7,'{\"variable_conversion\": [{\"variable\": \"dev_ok\", \"text\": \"yes\"}, {\"variable\": \"dev_critique_new\", \"text\": \"\"}, {\"variable\": \"developer_prompt\", \"text\": \"Теперь проверь собственную работу как строгий рецензент. Правки ты только что\\nсделал — не пересказывай их, а ищи, что с ними не так. Новый код сейчас не пиши.\\n\\nКруг самопроверки %dev_iteration% из %max_dev_iterations%.\\n\\nФормальные требования: подзадача выполнена целиком, а не наполовину; изменения\\nзакоммичены в ветку %subtask_branch% и запушены; merge request в master открыт и его\\nадрес попал в отчёт полем mr_url; ничего лишнего за пределами подзадачи не задето.\\n\\nДальше посмотри на изменение с другого ракурса:\\n1. Соответствие: закрывает ли сделанное описание подзадачи и те цели задачи,\\n   которые к ней относятся? Чего не хватает?\\n2. Регрессии: кто ещё зовёт изменённые функции и шаблоны, что сломается рядом?\\n   Найди эти места в коде и проверь.\\n3. Правила проекта: именование, размещение файлов, схема БД, контракт API,\\n   фронтенд — что нарушено?\\n4. Проверяемость: чем результат подтверждается и пройдут ли существующие тесты\\n   (tests/) — их будет гонять QA.\\n%if task_last_error%5. Прошлая ошибка QA закрыта: %task_last_error%\\n%endif%\\nНе выполнен хотя бы один пункт — dev_ok=no. В замечаниях пиши задания на\\nдоработку, а не пересказ сделанного.\\n\\nОтветь ОДНИМ JSON-объектом, без markdown и без текста вокруг:\\n{\\\"dev_ok\\\": \\\"yes\\\", \\\"dev_score\\\": 7, \\\"dev_critique_new\\\": \\\"замечания, пустая строка если всё хорошо\\\"}\\ndev_ok — строго yes или no, dev_score — число от 1 до 10.\"}], \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (440,56,3,'Разработчик: самопроверка',8,'{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"developer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_600\"}, \"outputs_map\": {\"error\": \"dev_error\", \"status\": \"dev_status\", \"dev_ok\": \"dev_ok\", \"dev_critique_new\": \"dev_critique_new\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"dev_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"442\"}, {\"variable\": \"dev_ok\", \"operator\": \"==\", \"value\": \"yes\", \"step_id\": \"442\"}, {\"variable\": \"dev_iteration\", \"operator\": \">=\", \"value\": \"%max_dev_iterations%\", \"step_id\": \"442\"}, {\"variable\": \"dev_ok\", \"operator\": \"!=\", \"value\": \"yes\", \"step_id\": \"441\"}]}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (441,56,5,'Замечания на доработку',9,'{\"variable_conversion\": [{\"variable\": \"dev_critique\", \"text\": \"%dev_critique_new%\"}], \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"dev_critique\", \"operator\": \"exists\", \"value\": \"\", \"step_id\": \"435\"}]}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (442,56,4,'Вернуть результат',10,'{\"prompt_user\": \"json:{\\\"ok\\\": true, \\\"report\\\": %dev_report_json%, \\\"error\\\": \\\"\\\"}\", \"continue_workflow\": false, \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (443,56,4,'Разработчик недоступен',11,'{\"prompt_user\": \"json:{\\\"ok\\\": false, \\\"report\\\": {}, \\\"error\\\": \\\"Разработчик не ответил. Статус: %dev_status%. Ошибка: %dev_error%\\\"}\", \"continue_workflow\": false, \"transitions_before\": [], \"transitions_after\": []}')
    ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

-- ─── 4. Связи переменных с workflow ───────────────────────────────────────────
INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (259,56);

INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (260,56);

INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (262,56);

-- ─── 5. Агент разработчика ────────────────────────────────────────────────────
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (113,6,'task_dev_developer','Task Developer','Разработчик конвейера задач: выполняет одну подзадачу плана',56,'{}','Ты аккуратный разработчик. Делаешь ровно одну подзадачу из плана, по правилам проекта, минимальными изменениями и в своей ветке. Всегда отвечаешь строго в JSON формате.','',0,'Проекты/Task',0)
    ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);

-- ─── После: сверка ────────────────────────────────────────────────────────────
SELECT (SELECT COUNT(*) FROM `agent_workflow` WHERE `id` = 56)                AS `wf56`,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = 56)   AS `steps56`,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `id` IN (259, 260, 262)) AS `vars`,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` WHERE `workflow_id` = 56) AS `var_links`,
       (SELECT `workflow_id` FROM `agent` WHERE `name` = 'task_dev_developer') AS `agent_wf`;
