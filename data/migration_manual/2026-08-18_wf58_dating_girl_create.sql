-- Workflow #58 `dating_girl_create` → на прод
--
-- Зачем вручную: seed применяется только к пустой базе, а прод заполнен. Workflow,
-- заведённый локально, на проде не появится ни при деплое, ни при рестарте.
--
-- Что делает этот workflow: заводит агента анкеты — промпт из шаблона узла Dating,
-- факты из переданной биографии, привязка к `dating_talk`. Его зовёт DatingAi через
-- `POST /agent/create`, поэтому без него панель анкет на проде не сможет завести ни
-- одного агента: `dating_girl_create` — единственный путь к фактам из биографии.
--
-- ЧТО ПЕРЕНОСИТСЯ (снято с локальной базы 2026-08-18):
--   agent_workflow                     1 строка  — сам #58, «Создание девушки»
--   agent_workflow_variable            1 строка  — `girl_bio` (id 265), тип `input`
--   agent_workflow_variable_workflow  10 строк   — связи переменных с #58
--   agent_workflow_step               10 строк   — шаги 543…552
--
-- ПРОВЕРЕНО НА ПРОДЕ ПЕРЕД ВЫПУСКОМ:
--   * `agent_workflow` id 58 свободен;
--   * шаги 543–552 свободны (максимум на проде — 540);
--   * переменная 265 свободна (максимум — 264);
--   * девять остальных переменных (24, 26, 30, 32, 40, 41, 42, 43, 62) на проде уже
--     есть под теми же номерами и именами — переносить их не нужно, только связи;
--   * `dating_talk` (#5) и подпотоки #6, #7 на проде есть — #58 привязывает агента к #5;
--   * все семь инструментов шагов на проде есть (`agent_exists`, `agent_workflow_id`,
--     `agent_create_or_update`, `fact_collection_output_format`, `qdrant_fact_remove`,
--     `fact_collection_add`, `qdrant_fact_sync`) — они синхронизируются из кода.
--
-- ⚠️ ID ШАГОВ ПЕРЕНОСЯТСЯ КАК ЕСТЬ, и здесь причина не в переходах: у #58 они пустые,
--   шаги идут по порядку. Причина в **именах результатов**: шаг складывает свой итог в
--   переменную `<инструмент>_<id шага>_result_<тип>`, и соседи читают её по этому имени.
--   В метаданных #58 таких ссылок три — `_544_result_bool` (есть ли уже такой агент),
--   `_545_result_int` (номер workflow общения) и `_547_result_str` (формат фактов).
--   Переназначить id при вставке — оставить эти ссылки смотреть в пустоту: workflow
--   пройдёт все шаги и заведёт агента без промпта и без фактов, не сказав ни слова.
--
-- ⚠️ Переменные узла Dating (`girl_title`, `girl_prompt_system`, `girl_bio_example`)
--   живут в `node_variable` и на проде уже есть — 3 строки, перенесены предыдущей
--   миграцией переименования. Без них промпт девушки собрался бы пустым.
--
-- Служебный агент `dating_girl_create_runner` здесь не переносится: его заводит сама
-- точка `/agent/create` при первом вызове, если его нет.
--
-- Порядок таблиц по внешним ключам: workflow → переменная → связи → шаги.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup`.

USE `project`;

SET NAMES utf8mb4;

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM agent_workflow WHERE id = 58)                        AS есть_workflow,
       (SELECT COUNT(*) FROM agent_workflow_step WHERE workflow_id = 58)          AS шагов,
       (SELECT COUNT(*) FROM agent_workflow_variable WHERE id = 265)              AS есть_girl_bio,
       (SELECT COUNT(*) FROM agent_workflow_variable_workflow WHERE workflow_id = 58) AS связей,
       (SELECT COUNT(*) FROM agent_workflow WHERE id = 5)                         AS есть_dating_talk,
       (SELECT COUNT(*) FROM node_variable)                                       AS переменных_узлов;

-- 1. Сам workflow (1 строк)
INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `group_name`, `subflow`) VALUES (58,2,'dating_girl_create','Создание девушки','Заводит агента девушки по имени и биографии: системный промпт из шаблона ноды, факты из биографии',0,NULL,0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `subflow` = VALUES(`subflow`);

-- 2. Новая переменная — обязательное поле `girl_bio` (1 строк)
INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES (265,'girl_bio','input',NULL,'Краткая биография: из неё LLM соберёт факты')
  ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `type` = VALUES(`type`), `default` = VALUES(`default`), `description` = VALUES(`description`);

-- 3. Связи переменных с workflow (10 строк)
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (24,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (26,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (30,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (32,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (40,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (41,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (42,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (43,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (62,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES (265,58)
  ON DUPLICATE KEY UPDATE `variable_id` = VALUES(`variable_id`), `workflow_id` = VALUES(`workflow_id`);

-- 4. Шаги. ID сохраняются — по ним ссылаются переходы (10 строк)
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (543,58,5,'Переменные агента',0,'{\"variable_conversion\": [{\"variable\": \"agent_exists_find_by\", \"text\": \"{\\\"name\\\":\\\"%agent_name%\\\"}\"}, {\"variable\": \"workflow_variable\", \"text\": \"{\\\"girl_id\\\":\\\"%agent_name%\\\"}\"}, {\"variable\": \"girl_agent_workflow_name\", \"text\": \"dating_talk\"}, {\"variable\": \"girl_description\", \"text\": \"Анкета %girl_title%\"}, {\"variable\": \"girl_greeting\", \"text\": \"Hi, I am %girl_title%\"}, {\"variable\": \"qdrant_metada_filter\", \"text\": \"{\\\"document_id\\\":\\\"%agent_name%\\\"}\"}], \"transitions_before\": [], \"transitions_after\": []}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (544,58,3,'Есть ли такой агент',1,'{\"tool_invoke\": {\"tool_name\": \"agent_exists\", \"inputs_map\": {\"find_by\": \"agent_exists_find_by\"}, \"outputs_map\": {\"bool\": \"agent_exists_544_result_bool\"}}, \"transitions_before\": [], \"transitions_after\": []}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (545,58,3,'Workflow общения',2,'{\"tool_invoke\": {\"tool_name\": \"agent_workflow_id\", \"inputs_map\": {\"name\": \"girl_agent_workflow_name\"}, \"outputs_map\": {\"int\": \"agent_workflow_id_545_result_int\"}}, \"transitions_before\": [], \"transitions_after\": []}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (546,58,3,'Создать агента',3,'{\"tool_invoke\": {\"tool_name\": \"agent_create_or_update\", \"inputs_map\": {\"name\": \"agent_name\", \"title\": \"girl_title\", \"node_id\": \"node_id\", \"workflow_id\": \"agent_workflow_id_545_result_int\", \"workflow_variable\": \"workflow_variable\", \"prompt_system\": \"girl_prompt_system\", \"description\": \"girl_description\", \"greeting\": \"girl_greeting\", \"user_id\": \"user_id\"}, \"outputs_map\": {\"int\": \"girl_agent_id\"}}, \"transitions_before\": [], \"transitions_after\": []}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (547,58,3,'fact_collection_output_format',4,'{\"tool_invoke\":{\"tool_name\":\"fact_collection_output_format\",\"inputs_map\":{\"collection_name\":\"fact_collection_girl_name\"},\"outputs_map\":{\"str\":\"fact_collection_output_format_response\"}},\"transitions_before\":[],\"transitions_after\":[]}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (548,58,2,'LLM -> JSON',5,'{\"transitions_before\":[],\"transitions_after\":[],\"llm_to_json_variable\":[{\"variable\":\"facts\",\"text\":\"список фактов\"}],\"prompt_user\":\"Ниже приведена краткая биография девушки %girl_title%, написанная пользователем. Составь на её основе структурированный список фактов.\\n\\n=== Биография ===\\n%girl_bio%\\n\\nПравила:\\n1. Главный источник — биография: каждое её утверждение преврати в отдельный короткий факт (один факт — одно утверждение).\\n2. Факты не должны противоречить биографии и друг другу.\\n3. Если каких-то тем в биографии нет, аккуратно дополни правдоподобными деталями в согласии с текстом. Темы: подростковый возраст, учеба, отношения с родителями, любимые занятия и увлечения, любовные отношения, путешествия, работа.\\n4. Всего фактов должно быть 24-32.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys: \\n- \\\"facts\\\": список фактов\\n\\ndocument_id всегда \'%agent_name%\'\\n\\nExample of JSON response:\\n{\\n  \\\"facts\\\": %fact_collection_output_format_547_result_str%\\n}\"}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (549,58,3,'qdrant_fact_remove',6,'{\"tool_invoke\":{\"tool_name\":\"qdrant_fact_remove\",\"inputs_map\":{\"collection_name\":\"fact_collection_girl_name\",\"metadata_filter\":\"qdrant_metada_filter\"},\"outputs_map\":{}},\"transitions_before\":[],\"transitions_after\":[]}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (550,58,3,'fact_collection_add',7,'{\"tool_invoke\":{\"tool_name\":\"fact_collection_add\",\"inputs_map\":{\"collection_name\":\"fact_collection_girl_name\",\"data\":\"facts\",\"document_title\":\"girl_title\",\"user_id\":\"user_id\"},\"outputs_map\":{\"facts_qty\":\"facts_qty\"}},\"transitions_before\":[],\"transitions_after\":[]}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (551,58,3,'qdrant_fact_sync',8,'{\"tool_invoke\":{\"tool_name\":\"qdrant_fact_sync\",\"inputs_map\":{},\"outputs_map\":{}},\"transitions_before\":[],\"transitions_after\":[]}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES (552,58,4,'Итог',9,'{\"transitions_before\": [], \"transitions_after\": [], \"text\": \"Агент %agent_name% создан (#%girl_agent_id%), фактов: %facts_qty%\"}')
  ON DUPLICATE KEY UPDATE `workflow_id` = VALUES(`workflow_id`), `type_id` = VALUES(`type_id`), `title` = VALUES(`title`), `position` = VALUES(`position`), `metadata` = VALUES(`metadata`);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM agent_workflow WHERE id = 58)                            AS есть_workflow,
       (SELECT COUNT(*) FROM agent_workflow_step WHERE workflow_id = 58)              AS шагов,
       (SELECT COUNT(*) FROM agent_workflow_variable_workflow WHERE workflow_id = 58) AS связей;

-- Шаги по порядку — сверить с локальными по названиям.
SELECT id, position, title FROM agent_workflow_step WHERE workflow_id = 58 ORDER BY position;

-- Целостность переходов: каждый `step_id` из `transitions_after` должен существовать.
SELECT s.id AS шаг, jt.step_id AS ведёт_на,
       IF(t.id IS NULL, 'ШАГА НЕТ', t.title) AS куда
  FROM agent_workflow_step s
  JOIN JSON_TABLE(COALESCE(JSON_EXTRACT(s.metadata, '$.transitions_after'), '[]'),
                  '$[*]' COLUMNS (step_id INT PATH '$.step_id')) jt
  LEFT JOIN agent_workflow_step t ON t.id = jt.step_id
 WHERE s.workflow_id = 58 AND jt.step_id IS NOT NULL
 ORDER BY s.position;

-- Обязательные поля workflow: их проверяет `/agent/create` до прогона.
SELECT v.id, v.name, v.type
  FROM agent_workflow_variable v
  JOIN agent_workflow_variable_workflow vw ON vw.variable_id = v.id
 WHERE vw.workflow_id = 58 AND v.type = 'input';
