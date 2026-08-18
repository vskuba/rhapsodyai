-- Агент и workflow багфиксера → на прод
--
-- Зачем вручную: агенты и workflow — данные, деплой их не трогает, а `data/seeds/`
-- закрыт `.gitignore` и на сервер не едет. Тот же путь, каким приехали агенты
-- планирования (`2026-08-18_planning_agents_prod.sql`).
--
-- ЧТО ПЕРЕНОСИТСЯ (снято с локальной установки 2026-08-18):
--
--     workflow 59  task_bug_fixer  «Task: Фикс бага»   13 шагов (553…565)
--     agent    222 task_bug_fixer  «Task Bugfixer»     → workflow 59
--     связи переменных 259 (task_shell_role) и 260 (task_shell_work_dir) → workflow 59
--
-- Через него работает роль `bugfixer`: захват бага (`task_claim_task_bug`) находит
-- агента по имени `task_bug_fixer`, поэтому без этих строк конвейер багов на проде
-- сорвётся на первом же прогоне с «агент не найден».
--
-- ПРОВЕРЕНО НА ПРОДЕ ПЕРЕД ВЫПУСКОМ:
--   * номера 59 (workflow), 222 (агент) и 553–565 (шаги) свободны;
--   * нумерация идёт следом за прод-максимумами: workflow 58, шаг 552;
--   * узел 6 на проде — тот же `Dashboard`, что локально;
--   * переменные 259 и 260 на проде есть под теми же именами;
--   * тип задачи `bug` на проде — id 2, как локально.
--
-- ⚠️ ID сохраняются: workflow и агент адресуются по номеру из панели и из ссылок
--   вида `/admin/agent?agent_id=222`. Переназначение сбило бы соответствие с
--   локальной установкой, по которой файл и собран.
--
-- ⚠️ ПОРЯДОК: сперва `2026-08-18_task_pipeline_state_bugfixing.sql` (значение ENUM),
--   потом этот файл. Наоборот тоже не сломает, но агент без состояния бесполезен.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup`.
--
-- Повторный прогон безопасен: все вставки идут через INSERT IGNORE, существующие
-- строки не трогаются.

USE `project`;

SET NAMES utf8mb4;

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM agent_workflow WHERE id = 59) AS workflow_59,
       (SELECT COUNT(*) FROM agent_workflow_step WHERE workflow_id = 59) AS шагов,
       (SELECT COUNT(*) FROM agent WHERE id = 222) AS agent_222;

INSERT IGNORE INTO `agent_workflow` (`id`,`node_id`,`name`,`title`,`description`,`position`,`group_name`,`subflow`) VALUES
  (59, 6, 'task_bug_fixer', 'Task: Фикс бага', 'Багфиксер: разбор, воспроизведение, починка, самопроверка, вердикт', 0, 'Проекты/Task', 0);

INSERT IGNORE INTO `agent_workflow_step` (`id`,`workflow_id`,`type_id`,`title`,`position`,`metadata`) VALUES
  (553, 59, 5, 'Инициализация', 0, '{\"variable_conversion\": [{\"variable\": \"env_ok\", \"text\": \"yes\"}, {\"variable\": \"env_error\", \"text\": \"\"}, {\"variable\": \"bug_recon\", \"text\": \"\"}, {\"variable\": \"bug_fix\", \"text\": \"\"}, {\"variable\": \"bug_check\", \"text\": \"\"}, {\"variable\": \"bug_report_json\", \"text\": \"\"}, {\"variable\": \"bug_status\", \"text\": \"\"}, {\"variable\": \"bug_error\", \"text\": \"\"}], \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"task_work_dir\", \"operator\": \"empty\", \"value\": \"\", \"step_id\": \"555\"}]}'),
  (554, 59, 3, 'Проверка среды', 1, '{\"tool_invoke\": {\"tool_name\": \"task_server_check\", \"inputs_map\": {\"subtask_id\": \"task_id\", \"work_dir\": \"task_shell_work_dir\"}, \"outputs_map\": {\"env_ok\": \"env_ok\", \"env_error\": \"env_error\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"env_ok\", \"operator\": \"==\", \"value\": \"no\", \"step_id\": \"565\"}]}'),
  (555, 59, 5, 'Промпт: разбор бага', 2, '{\"variable_conversion\": [{\"variable\": \"bugfixer_prompt\", \"text\": \"Ты чинишь баг в этом проекте. Сейчас только разбор: код НЕ меняй,\\nфайлы не правь, коммитов не делай.\\n%if task_work_dir%\\nРаботай в каталоге %task_work_dir% — это отдельная выкладка репозитория, ветка бага\\nв ней уже выкачена. Начни с перехода в этот каталог.\\n%endif%\\n\\n=== БАГ ===\\n#%task_id% %task_title%\\n\\n%task_description%\\n\\n%if task_trace_meta%=== СЛЕД ИЗ ЖУРНАЛА ВЫПОЛНЕНИЯ ===\\n%task_trace_meta%\\n\\n%endif%%if task_goals%=== ЦЕЛИ ===\\n%task_goals%\\n\\n%endif%Что сделать:\\n1. Пойми, о чём баг: какой код за него отвечает, конкретные пути к файлам и функции.\\n2. Попробуй воспроизвести. Скажи прямо, воспроизвёлся он или нет и чем ты проверял.\\n3. Если воспроизвёлся — назови причину: строку, условие, состояние данных.\\n4. Прочитай правила проекта, которые тут действуют: CLAUDE.md и нужные файлы\\n   .claude/docs/ и .claude/docs-common/.\\n5. Наметь минимальную правку: какие файлы меняешь и чем проверишь результат.\\n\\nОтвечай обычным текстом, не длиннее 15 строк, строка на мысль. Без заголовков и\\nтаблиц — этот ответ целиком уходит в следующий промпт. JSON сейчас не нужен.\"}], \"transitions_before\": [], \"transitions_after\": []}'),
  (556, 59, 3, 'Багфиксер: разбор', 3, '{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"bugfixer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_1200\"}, \"outputs_map\": {\"error\": \"bug_error\", \"status\": \"bug_status\", \"response\": \"bug_recon\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"bug_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"564\"}, {\"variable\": \"bug_recon\", \"operator\": \"empty\", \"value\": \"\", \"step_id\": \"564\"}]}'),
  (557, 59, 5, 'Промпт: починка', 4, '{\"variable_conversion\": [{\"variable\": \"bugfixer_prompt\", \"text\": \"Теперь почини баг по своему же разбору.\\n\\n%if task_work_dir%Работай в каталоге %task_work_dir%, ветка %task_branch% уже выкачена —\\nпереключать её не нужно.\\n%endif%\\nПравила:\\n- правка минимальная: чинишь причину, а не переписываешь модуль;\\n- ничего постороннего в тех же файлах не трогаешь;\\n- следуешь правилам проекта из CLAUDE.md и .claude/docs/;\\n- изменения коммитишь в свою ветку.\\n\\nЕсли по ходу выяснилось, что починить нельзя — не выдумывай правку. Скажи прямо, что\\nименно мешает: не воспроизводится, причина вне проекта, нужен доступ, которого нет.\\n\\nОтвечай обычным текстом: что изменил, в каких файлах, каким коммитом. Не длиннее\\n15 строк.\"}], \"transitions_before\": [], \"transitions_after\": []}'),
  (558, 59, 3, 'Багфиксер: починка', 5, '{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"bugfixer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_1200\"}, \"outputs_map\": {\"error\": \"bug_error\", \"status\": \"bug_status\", \"response\": \"bug_fix\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"bug_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"564\"}, {\"variable\": \"bug_fix\", \"operator\": \"empty\", \"value\": \"\", \"step_id\": \"564\"}]}'),
  (559, 59, 5, 'Промпт: самопроверка', 6, '{\"variable_conversion\": [{\"variable\": \"bugfixer_prompt\", \"text\": \"Проверь свой фикс.\\n\\n%if task_server_url%Сервер этого проекта: %task_server_url% — проверяй на нём.\\n%endif%%if task_work_dir%Каталог: %task_work_dir%.\\n%endif%\\nЧто сделать:\\n1. Прогони существующие тесты проекта, которые задевает правка.\\n2. Воспроизведи исходный сценарий бага заново и убедись, что он больше не повторяется.\\n3. Проверь, что рядом ничего не сломалось.\\n\\nНовых тестов ради галочки не пиши. Если проверить нечем — скажи об этом прямо, а не\\nвыдавай непроверенное за проверенное.\\n\\nОтвечай обычным текстом: что прогнал и с каким результатом. Не длиннее 10 строк.\"}], \"transitions_before\": [], \"transitions_after\": []}'),
  (560, 59, 3, 'Багфиксер: самопроверка', 7, '{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"bugfixer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_1200\"}, \"outputs_map\": {\"error\": \"bug_error\", \"status\": \"bug_status\", \"response\": \"bug_check\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"bug_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"564\"}, {\"variable\": \"bug_check\", \"operator\": \"empty\", \"value\": \"\", \"step_id\": \"564\"}]}'),
  (561, 59, 5, 'Промпт JSON: вердикт', 8, '{\"variable_conversion\": [{\"variable\": \"bug_report_json\", \"text\": \"\"}, {\"variable\": \"bugfixer_prompt\", \"text\": \"Верни тот же самый ответ в машинном виде. Ничего заново не придумывай\\nи не переделывай — это ровно то, что ты только что сделал.\\n\\nОтветь ОДНИМ JSON-объектом, без markdown, без ограды из обратных кавычек и без текста\\nвокруг:\\n{\\\"bug_report_json\\\": {\\\"ok\\\": true, \\\"summary\\\": \\\"что сделано\\\", \\\"cause\\\": \\\"причина бага\\\", \\\"files\\\": [\\\"путь/к/файлу\\\"], \\\"branch\\\": \\\"%task_branch%\\\", \\\"checks\\\": \\\"чем проверял и с каким результатом\\\", \\\"error\\\": \\\"почему не починено, если ok=false\\\"}}\\n\\n- bug_report_json — ВСЕГДА объект, поля ровно те, что перечислены.\\n- files — массив строк, ok — true или false.\\n- ok=false ставь, если баг починить не удалось: не воспроизвёлся, причина вне проекта,\\n  не хватило доступа. Тогда в error — причина одной фразой.\\n- summary, cause, checks и error — обычный текст, без двойных кавычек и фрагментов JSON.\"}], \"transitions_before\": [], \"transitions_after\": []}'),
  (562, 59, 3, 'Ответ JSON: вердикт', 9, '{\"tool_invoke\": {\"tool_name\": \"claude_shell_call\", \"inputs_map\": {\"role\": \"task_shell_role\", \"prompt\": \"bugfixer_prompt\", \"work_dir\": \"task_shell_work_dir\", \"timeout\": \"_const_1200\"}, \"outputs_map\": {\"error\": \"bug_error\", \"status\": \"bug_status\", \"payload_json\": \"bug_report_json\"}}, \"transitions_before\": [], \"transitions_after\": [{\"variable\": \"bug_status\", \"operator\": \"!=\", \"value\": \"answered\", \"step_id\": \"564\"}, {\"variable\": \"bug_report_json\", \"operator\": \"empty\", \"value\": \"\", \"step_id\": \"564\"}]}'),
  (563, 59, 4, 'Вернуть результат', 10, '{\"prompt_user\": \"json:{\\\"ok\\\": true, \\\"report\\\": %bug_report_json%, \\\"error\\\": \\\"\\\"}\", \"continue_workflow\": false, \"transitions_before\": [], \"transitions_after\": []}'),
  (564, 59, 4, 'Оболочка недоступна', 11, '{\"prompt_user\": \"json:{\\\"ok\\\": false, \\\"report\\\": {}, \\\"error\\\": \\\"Багфиксер не ответил: %bug_error%\\\"}\", \"continue_workflow\": false, \"transitions_before\": [], \"transitions_after\": []}'),
  (565, 59, 4, 'Среда не готова', 98, '{\"prompt_user\": \"json:{\\\"ok\\\": false, \\\"env_ok\\\": false, \\\"report\\\": {}, \\\"error\\\": \\\"Среда не готова: %env_error%\\\"}\", \"continue_workflow\": false, \"transitions_before\": [], \"transitions_after\": []}');

INSERT IGNORE INTO `agent` (`id`,`node_id`,`name`,`title`,`description`,`workflow_id`,`workflow_variable`,`prompt_system`,`greeting`,`position`,`group_name`,`dynamic`) VALUES
  (222, 6, 'task_bug_fixer', 'Task Bugfixer', 'Чинит баг целиком: разбор, воспроизведение, фикс, самопроверка', 59, NULL, '', '', 0, 'Проекты/Task', 0);

INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`,`workflow_id`) VALUES (259, 59), (260, 59);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM agent_workflow WHERE id = 59) AS workflow_59,
       (SELECT COUNT(*) FROM agent_workflow_step WHERE workflow_id = 59) AS шагов,
       (SELECT COUNT(*) FROM agent WHERE id = 222) AS agent_222,
       (SELECT COUNT(*) FROM agent_workflow_variable_workflow WHERE workflow_id = 59) AS переменных;

-- Ожидается: workflow_59 = 1, шагов = 13, agent_222 = 1, переменных = 2.
