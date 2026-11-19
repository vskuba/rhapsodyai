-- Ответ в чате: длина от его реплики, а не от жребия вслепую (2026-11-19)
--
-- ЗАЧЕМ. Замер прода за 30 дней (Ladadate и Step2Love, 237 ответов агента):
-- наш ответ держится около 19 слов при любой его реплике. На 1–4 его слова —
-- 19,0 наших в среднем, втрое длиннее в 94% случаев («hello» → вопрос про
-- историю улыбки). Причина: промпт просил «%dice_chat_word% words», жребий в
-- 75% давал «1-20», и модель писала у верхней границы.
--
-- ЧТО. Шаг «Длина его реплики» меряет его текст в словах (`prompt_user`),
-- шаг «Коридор длины чата» выбирает коридор по ней. Отступление оставлено
-- жребием `dice_chat_scale` (решение владельца: правила «всегда как он» быть
-- не может): как он — 85%, короче — 7%, длиннее — 5%, намного длиннее — 3%.
-- В промпте узкий коридор (`chat_word_range`), в проверке — шире
-- (`chat_word_check`): круга переписываний у проверки длины ничто не держит,
-- и узкий коридор крутил бы его до таймаута. Инициатива и письма — по-прежнему.

SET @tw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON), '$.dice_chat_scale', CAST('{"mirror": 85, "shorter": 7, "longer": 5, "much_longer": 3}' AS JSON)) AS CHAR)
 WHERE `workflow_id` = @tw AND `name` = 'dice_talk_spec'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.outputs_map.dice_chat_scale', 'dice_chat_scale')
 WHERE `workflow_id` = @tw AND `title` = 'Жребий'
;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'dice_chat_scale', 'workflow', 'mirror', 'Длина ответа в чате относительно его реплики: mirror / shorter / longer / much_longer'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'dice_chat_scale')
;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'chat_his_measure_range', 'workflow', '0-1000000', 'Вилка-заглушка для замера его реплики: нужна длина, а не вердикт'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'chat_his_measure_range')
;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'chat_word_range', 'workflow', '', 'Коридор слов ответа в чате для промпта — от длины его реплики'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'chat_word_range')
;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'chat_word_check', 'workflow', '', 'Коридор слов для проверки длины — шире промпта, чтобы не крутить переписывания'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'chat_word_check')
;

SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Длина его реплики');

SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Жребий');

UPDATE `agent_workflow_step` SET `position` = `position` + 2
 WHERE `workflow_id` = @tw AND `position` >= @pos AND @has = 0
 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 3, 'Длина его реплики', @pos, CAST('{"tool_invoke": {"tool_name": "text_length_range_check", "inputs_map": {"text": "prompt_user", "length_range": "chat_his_measure_range"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE @has = 0;

SET @me = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Длина его реплики');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 5, 'Коридор длины чата', @pos + 1,
       CAST(REPLACE('{"transitions_before": [], "transitions_after": [], "variable_conversion": [{"variable": "chat_word_range", "text": "[<if make_initiative or text_length_range_check_{{ME}}_result_length == 0>]%dice_chat_word%[<else>][<if dice_chat_scale == ''shorter''>][<if text_length_range_check_{{ME}}_result_length <= 3>]1-2[<else>][<if text_length_range_check_{{ME}}_result_length <= 6>]1-3[<else>][<if text_length_range_check_{{ME}}_result_length <= 12>]2-5[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]3-10[<else>]5-18[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''longer''>][<if text_length_range_check_{{ME}}_result_length <= 3>]6-14[<else>][<if text_length_range_check_{{ME}}_result_length <= 6>]9-20[<else>][<if text_length_range_check_{{ME}}_result_length <= 12>]14-30[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]25-45[<else>]35-70[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''much_longer''>][<if text_length_range_check_{{ME}}_result_length <= 12>]18-40[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]35-70[<else>]50-100[<endif>][<endif>][<else>][<if text_length_range_check_{{ME}}_result_length <= 3>]1-6[<else>][<if text_length_range_check_{{ME}}_result_length <= 6>]2-10[<else>][<if text_length_range_check_{{ME}}_result_length <= 12>]4-16[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]6-28[<else>]10-45[<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>]"}, {"variable": "chat_word_check", "text": "[<if make_initiative or text_length_range_check_{{ME}}_result_length == 0>]%dice_chat_word%[<else>][<if dice_chat_scale == ''shorter''>][<if text_length_range_check_{{ME}}_result_length <= 3>]1-4[<else>][<if text_length_range_check_{{ME}}_result_length <= 6>]1-5[<else>][<if text_length_range_check_{{ME}}_result_length <= 12>]1-8[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]2-14[<else>]3-24[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''longer''>][<if text_length_range_check_{{ME}}_result_length <= 3>]4-20[<else>][<if text_length_range_check_{{ME}}_result_length <= 6>]6-26[<else>][<if text_length_range_check_{{ME}}_result_length <= 12>]10-38[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]18-55[<else>]25-85[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''much_longer''>][<if text_length_range_check_{{ME}}_result_length <= 12>]12-55[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]25-90[<else>]35-130[<endif>][<endif>][<else>][<if text_length_range_check_{{ME}}_result_length <= 3>]1-10[<else>][<if text_length_range_check_{{ME}}_result_length <= 6>]1-14[<else>][<if text_length_range_check_{{ME}}_result_length <= 12>]2-22[<else>][<if text_length_range_check_{{ME}}_result_length <= 25>]4-35[<else>]6-55[<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>]"}], "to_next_step": true}', '{{ME}}', @me) AS JSON)
 WHERE @has = 0;

-- ⚠ Объявлена с умолчанием: условие на необъявленной переменной не сворачивается.
INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, CONCAT('text_length_range_check_', @me, '_result_length'), 'workflow', '0',
       'Сколько слов в его реплике'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw
                    AND CAST(`name` AS BINARY) = CAST(CONCAT('text_length_range_check_', @me, '_result_length') AS BINARY));

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         '[<if mail_mode>]%dice_mail_word%[<else>][<if chat_word_check>]%chat_word_check%[<else>]%dice_chat_word%[<endif>][<endif>]')
 WHERE `workflow_id` = @tw AND `title` = 'Требуемая длина ответа'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '1. Return the answer: %dice_chat_word% words, as in a messenger.',
                 REPLACE('1. Return the answer: %chat_word_range% words, as in a messenger.[<if text_length_range_check_{{ME}}_result_length > 0>] He wrote %text_length_range_check_{{ME}}_result_length% words — a short line gets a short answer back, not a paragraph.[<endif>]', '{{ME}}', @me)))
 WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @tw AND `position` BETWEEN @pos - 1 AND @pos + 2) AS порядок,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат'
         AND `metadata` LIKE '%chat_word_range% words%' AND `metadata` NOT LIKE '%dice_chat_word% words%') AS промпт_1,
       (SELECT JSON_EXTRACT(CAST(`default` AS JSON), '$.dice_chat_scale') FROM `agent_workflow_variable`
         WHERE `workflow_id` = @tw AND `name` = 'dice_talk_spec') AS жребий,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Требуемая длина ответа'
         AND `metadata` LIKE '%chat_word_check%') AS проверка_1
;
