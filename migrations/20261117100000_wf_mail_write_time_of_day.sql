-- Шаблон рассылки: время суток, заглушка вместо письма и обход проверок (2026-11-17)
--
-- ЗАЧЕМ.
--   1. ⚠⚠⚠ 17.11.2026 модель вернула вместо письма пример из промпта —
--      «text of the letter», — и два таких письма ушли живым людям (Elena →
--      Meep, Johannes). Пропустил их шаг «Переменные»: письмо БЕЗ ЕДИНОЙ метки
--      он отправлял прямо в «Что не так» с пустой причиной, то есть мимо всех
--      проверок и судьи прямо в «Готово». Переход снят: проверки идут всегда.
--      Пример ответа в промпте больше не несёт текста, который можно вернуть.
--   2. Шаблоны уходят в течение всего дня, а писатель писал «good evening»,
--      «tonight», «have a lovely evening»: промпт прямо разрешал «this evening»,
--      а подпоток дня говорил «письмо, которое ты напишешь вечером». Оба промпта
--      поправлены, и добавлен шаг «Время суток словами?» — регулярка
--      `text_regex_extract`, находка возвращает письмо на переписку с причиной.
--      Время ВНУТРИ рассказа («in the evening I walked home») законно и не ловится.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @dw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_day_invent');

-- 1. Шаг «Переменные» больше не перескакивает проверки при письме без меток.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY())
 WHERE `workflow_id` = @mw AND `title` = 'Переменные'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[0].variable'))
       = CONCAT('text_regex_unknown_', `id`, '_result_found_qty');

-- 2. Писатель: время суток запрещено, пример ответа без текста письма.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '- ⚠⚠ NEVER name a weekday, a month, a date or a clock time. «Today», «this evening», «this morning» are fine.', '- ⚠⚠ NEVER name a weekday, a month, a date or a clock time.
- ⚠⚠ the letter is sent at ANY hour, and you never know when he reads it: NO time of day for the moment of writing or reading — no «good morning», «good evening», «tonight», «this evening», «this morning», «have a lovely evening», «sleep well», «sweet dreams». What you tell happened earlier: «after work», «on my way home», «the other day» are fine.'),
                 'Return JSON: {"letter_draft": "text of the letter"}', 'Return JSON with one key letter_draft — the whole letter as a string. Never return the words of this instruction instead of a letter.'))
 WHERE `workflow_id` = @mw AND `title` = 'Письмо'
;

-- 3. Подпоток дня: рассказ прошедшим, без «вечером, когда пишу».
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 'so that a letter you write tonight has something real to tell', 'so that a letter has something real to tell'),
                 'Say «today», «this morning», «in the evening».', 'Tell it as already past: «today», «after work», «on my way home». ⚠ The letter with this story is sent at any hour: never «tonight», «this evening», «right now», «as I write this».'))
 WHERE `workflow_id` = @dw AND `title` = 'День'
;

-- 4. Шаг «Время суток словами?» перед «Своё имя словами?».
INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'mail_time_pattern', 'workflow', '(?im)(\\bgood\\s*(?:morning|afternoon|evening|night)\\b|\\bgoodnight\\b|\\btonight\\b|\\bthis\\s+(?:morning|afternoon|evening)\\b|\\b(?:have|having|enjoy|enjoying)\\s+(?:a|an|your)\\s+(?:\\w+\\s+){0,2}(?:morning|afternoon|evening|night)\\b|\\bsleep\\s+well\\b|\\bsweet\\s+dreams\\b|^[ \\t]*(?:morning|afternoon|evening|night)(?=\\s*[,.!]))',
       'Время суток момента чтения: good evening, tonight, this morning, have a lovely evening, sleep well. Время внутри рассказа не ловится'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'mail_time_pattern');

SET @has_time = (SELECT COUNT(*) FROM `agent_workflow_step`
                  WHERE `workflow_id` = @mw AND `title` = 'Время суток словами?');

SET @name_pos = (SELECT `position` FROM `agent_workflow_step`
                  WHERE `workflow_id` = @mw AND `title` = 'Своё имя словами?');

SET @why = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Что не так');

UPDATE `agent_workflow_step` SET `position` = `position` + 1
 WHERE `workflow_id` = @mw AND `position` >= @name_pos AND @has_time = 0
 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @mw, 3, 'Время суток словами?', @name_pos,
       CAST(REPLACE('{"tool_invoke": {"tool_name": "text_regex_extract", "inputs_map": {"text": "letter_draft", "pattern": "mail_time_pattern"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [{"variable": "text_regex_extract_{{ME}}_result_str", "operator": "not_empty", "value": "", "step_id": "{{WHY}}"}], "to_next_step": true}', '{{WHY}}', @why) AS JSON)
 WHERE @has_time = 0;

SET @me = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Время суток словами?');

UPDATE `agent_workflow_step`
   SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR), '{{ME}}', @me) AS JSON)
 WHERE `id` = @me;

-- ⚠ Объявлена с пустым умолчанием: условие «Что не так» на необъявленной
-- переменной не сворачивается, а остаётся в тексте.
INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, CONCAT('text_regex_extract_', @me, '_result_str'), 'workflow', '',
       'Найденное время суток момента чтения. Пусто — письмо годно'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `workflow_id` = @mw AND CAST(`name` AS BINARY) = CAST(CONCAT('text_regex_extract_', @me, '_result_str') AS BINARY));

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         CONCAT(REPLACE('[<if text_regex_extract_{{ME}}_result_str>]«%text_regex_extract_{{ME}}_result_str%» ties the letter to a time of day, but it is sent and read at any hour — remove every time of day of the moment of writing or reading (good evening, tonight, this morning, have a lovely evening, sleep well). What you tell happened earlier: «after work», «on my way home». [<endif>]

', '{{ME}}', @me),
                JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.variable_conversion[0].text'))))
 WHERE `id` = @why
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.variable_conversion[0].text')) NOT LIKE '%ties the letter to a time of day%'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`metadata`, '$.transitions_after') FROM `agent_workflow_step`
         WHERE `workflow_id` = @mw AND `title` = 'Переменные') AS обход_снят_0,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Письмо'
         AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%sent at ANY hour%'
         AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) NOT LIKE '%text of the letter%') AS писатель_1,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `title` = 'День'
         AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) NOT LIKE '%write tonight%') AS день_1,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @mw AND `position` >= 23) AS хвост
;
