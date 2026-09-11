-- Workflow `dating_mail_vars`: агент заполняет переменные писем (2026-09-06)
--
-- ЗАЧЕМ. В DatingAi у писем рассылки есть переменные: человек заводит имена
-- (`girl_name`, `first_name`, …), а значения проставляются у каждой анкеты. До
-- сих пор их вписывали руками — по десятку полей на анкету, при сорока анкетах
-- на сайте.
--
-- Теперь их заполняет агент: DatingAi отдаёт сведения об анкете и список имён,
-- которые надо вернуть, и получает JSON «имя → значение».
--
-- ⚠ ПОЧЕМУ ОДИН ШАГ `return_response_llm`, А НЕ `llm_to_json`.
-- `llm_to_json` требует **заранее известных ключей**: они перечислены в
-- `llm_to_json_variable` метаданных шага и проверяются движком
-- (`missing_keys`). Здесь ключи известны только в момент запроса — их заводит
-- человек в панели DatingAi, и у каждого сайта свои. Записать их в metadata
-- нечем.
--
-- Поэтому шаг один и отдаёт ответ LLM как есть, а разбирает JSON вызывающая
-- сторона: у неё же лежит реестр имён, по которому надо сверить ответ. Разбор
-- там всё равно нужен — принимать от LLM только ожидаемые имена и молча
-- отбрасывать выдуманные.
--
-- ⚠ ПОЧЕМУ ПЕРЕМЕННЫЕ ТИПА `workflow`, А НЕ `input`. `input` движок проверяет и
-- отвергает запрос, в котором их нет (HTTP 400). Здесь обе переменные приходят
-- из запроса `POST /chat/ask` в поле `variables`, и умолчания нужны на случай,
-- когда вызывающий их не передал: тогда агент честно ответит пустым объектом, а
-- не уронит разговор.
--
-- ⚠ ПРО ФОРМАТ ОТВЕТА. Просим «только JSON и ничего больше», но полагаться на
-- это нельзя: LLM любит обрамить ответ пояснением или ```json. Вызывающая
-- сторона вырезает JSON из текста — так же, как это делает `_json_str_clean`
-- движка для `llm_to_json`.
--
-- Идемпотентность: всё вставляется по условию отсутствия.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow` WHERE `name` = 'dating_mail_vars') AS workflow_есть,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('mail_vars', 'girl_card')) AS переменных;

-- ------------------------------------------- Сам workflow
INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`, `subflow`)
SELECT 2, 'dating_mail_vars', 'Переменные писем',
       'Заполняет переменные писем по сведениям об анкете: на входе список имён, на выходе JSON «имя → значение»',
       0, 0
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow` WHERE `name` = 'dating_mail_vars');

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_vars');

-- ------------------------------------------- Единственный шаг
--
-- Промпт собран так, чтобы ответ годился машине:
--   * перечень имён приходит переменной — их знает только вызывающий;
--   * сведения об анкете тоже: у каждого сайта свой набор полей;
--   * «не знаешь — пропусти» важнее полноты: выдуманное имя девушки уедет живому
--     человеку в письме и будет выглядеть ровно тем, чем является.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 1, 'Ответ JSON', 0,
       JSON_OBJECT(
         'transitions_after', JSON_ARRAY(),
         'prompt_user',
         CONCAT(
           'Ты заполняешь карточку анкеты для рассылки писем на сайте знакомств.\n\n',
           '=== Что известно об анкете ===\n%girl_card%\n\n',
           '=== Какие поля нужны ===\n%mail_vars%\n\n',
           'Правила:\n',
           '1. Верни JSON-объект: ключ — имя поля из списка выше, значение — строка.\n',
           '2. Бери значения из сведений об анкете. Чего там нет — не выдумывай: ',
           'пропусти ключ совсем. Выдуманное уедет живому человеку в письме.\n',
           '3. Ключи — ровно те, что в списке. Других не добавляй.\n',
           '4. Значения короткие: имя, город, род занятий — не предложения.\n',
           '5. Ответ — только JSON, без пояснений и без markdown.\n\n',
           'Пример ответа:\n{"girl_name": "Diana", "girl_city": "Kyiv"}'
         ))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 0);

-- ------------------------------------------- Переменные и привязка
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_vars', 'workflow', '(список полей не передан)',
       'Какие поля вернуть: имя и подпись, по строке на поле'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_vars');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'girl_card', 'workflow', '(сведений об анкете не передано)',
       'Что известно об анкете: имя, возраст, город, о себе'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'girl_card');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_vars', 'girl_card')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_vars') AS workflow_id,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;
