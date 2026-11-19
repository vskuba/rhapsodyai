-- Ответ в чате: исчерпанная тема — переводить на новую с мостиком (2026-11-20)
--
-- ЗАЧЕМ. Разбор Ladadate: агент либо ведёт одну тему до упора («unusual place
-- story» четыре раза, «biggest fear» дважды подряд), либо меняет её обрывом
-- («fair enough» → «bored out of my mind. got any good show recommendations?»).
-- Новых тем сам не предлагает с мостиком никогда.
--
-- ЧТО. Подпоток dating_talk_topic_shift — один шаг return_response_llm с GBNF
-- yes|no: «тема исчерпана?» (два токена ответа). В dating_talk — шаг «Тема
-- исчерпана?» сразу за «Жребием» (до коридора длины: при смене темы ответ на
-- его «ok» обязан вместить мостик), письма и инициативу пропускает. При yes:
-- жребий направления dice_chat_new_topic, блок «смени тему с мостиком» у
-- писателя, отказ судьи на старую тему и на обрыв без мостика, коридор 8-18,
-- и «Анализ сообщения» не вправе пометить реплику «не отвечать»: проба —
-- на «same» после четырёх обменов про погоду агент молчал, разговор гас.

SET @tw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SET @node = (SELECT `node_id` FROM `agent_workflow` WHERE `id` = @tw);

INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`, `subflow`)
SELECT @node, 'dating_talk_topic_shift', 'Чат: тема исчерпана?', 'Один вопрос с GBNF yes|no: пора ли переводить разговор на новую тему', 0, 1
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow` WHERE `name` = 'dating_talk_topic_shift');

SET @sub = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk_topic_shift');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub, 'talk_history_chat', 'input', '', NULL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @sub AND `name` = 'talk_history_chat');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub, 'prompt_user', 'input', '', NULL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @sub AND `name` = 'prompt_user');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub, 'girl_title', 'input', '', NULL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @sub AND `name` = 'girl_title');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub, 'companion_title', 'input', '', NULL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @sub AND `name` = 'companion_title');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @sub, 1, 'Тема исчерпана?', 0, CAST('{"prompt_user": "=== Chat between %girl_title% (she) and %companion_title% (he), oldest first ===\\n%talk_history_chat%\\n\\n=== His newest message ===\\n%prompt_user%\\n\\n=== Question ===\\nHas the current subject of this conversation run its course?\\n\\nAnswer \\"yes\\" if ANY of these is true:\\n1. his last two replies are each just one to three words of agreement or acknowledgement with no question — \\"ok\\", \\"yes\\", \\"yeah\\", \\"same\\", \\"haha\\", \\"haha yes\\", \\"cool\\", \\"nice\\", \\"fair enough\\", \\"true\\" — this alone is enough, he has nothing more to say on this subject,\\n2. she keeps coming back to the same question, or the same thought is being repeated,\\n3. the last four or more exchanges are about one and the same subject and nothing new has been added for a while.\\n\\nAnswer \\"no\\" if his newest message brings something new — a fact, a feeling, a story, a new subject or his own question — or the conversation has only just started, or it is an intimate exchange that is still heating up.\\n\\nAnswer with one word: yes or no.", "transitions_before": [], "transitions_after": [], "gbnf": {"on": true, "enum": ["yes", "no"]}, "to_next_step": true, "output_variable": "", "continue_workflow": false}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @sub);

UPDATE `agent_workflow_step` SET `metadata` = CAST('{"prompt_user": "=== Chat between %girl_title% (she) and %companion_title% (he), oldest first ===\\n%talk_history_chat%\\n\\n=== His newest message ===\\n%prompt_user%\\n\\n=== Question ===\\nHas the current subject of this conversation run its course?\\n\\nAnswer \\"yes\\" if ANY of these is true:\\n1. his last two replies are each just one to three words of agreement or acknowledgement with no question — \\"ok\\", \\"yes\\", \\"yeah\\", \\"same\\", \\"haha\\", \\"haha yes\\", \\"cool\\", \\"nice\\", \\"fair enough\\", \\"true\\" — this alone is enough, he has nothing more to say on this subject,\\n2. she keeps coming back to the same question, or the same thought is being repeated,\\n3. the last four or more exchanges are about one and the same subject and nothing new has been added for a while.\\n\\nAnswer \\"no\\" if his newest message brings something new — a fact, a feeling, a story, a new subject or his own question — or the conversation has only just started, or it is an intimate exchange that is still heating up.\\n\\nAnswer with one word: yes or no.", "transitions_before": [], "transitions_after": [], "gbnf": {"on": true, "enum": ["yes", "no"]}, "to_next_step": true, "output_variable": "", "continue_workflow": false}' AS JSON)
 WHERE `workflow_id` = @sub AND `title` = 'Тема исчерпана?' ;

UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON), '$.dice_chat_new_topic', CAST('{"something from his profile you have not talked about yet — a hobby, his job or his city": 20, "a small real moment from your day today": 15, "a light either-or question (sea or mountains, morning or night, cats or dogs)": 15, "dreams and travel — a place he would love to see": 12, "food — what he loves to cook or eat": 10, "music or a film he likes": 10, "plans for the weekend": 8, "a childhood memory": 5, "a specific compliment about something in his profile, then a question": 5}' AS JSON)) AS CHAR)
 WHERE `workflow_id` = @tw AND `name` = 'dice_talk_spec' ;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.outputs_map.dice_chat_new_topic', 'dice_chat_new_topic')
 WHERE `workflow_id` = @tw AND `title` = 'Жребий' ;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'dice_chat_new_topic', 'workflow', '', 'Куда переводить исчерпанную тему — жребий направления'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'dice_chat_new_topic');

SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Тема исчерпана?');

SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Жребий');

SET @next = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `position` = @pos);

UPDATE `agent_workflow_step` SET `position` = `position` + 1
 WHERE `workflow_id` = @tw AND `position` >= @pos AND @has = 0 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 6, 'Тема исчерпана?', @pos,
       CAST(REPLACE(REPLACE('{"workflow_invoke": {"workflow_id": "{{SUB}}", "inputs_map": {"talk_history_chat": "talk_history_chat", "prompt_user": "prompt_user", "girl_title": "girl_title", "companion_title": "companion_title"}, "outputs_map": {}}, "transitions_before": [{"variable": "mail_mode", "operator": "==", "value": "1", "step_id": "{{NEXT}}"}, {"variable": "make_initiative", "operator": "==", "value": "1", "step_id": "{{NEXT}}"}, {"variable": "prompt_user", "operator": "empty", "value": "", "step_id": "{{NEXT}}"}], "transitions_after": [], "to_next_step": true}', '"{{SUB}}"', @sub), '{{NEXT}}', @next) AS JSON)
 WHERE @has = 0;

SET @me = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Тема исчерпана?');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, CONCAT('workflow_invoke_', @me, '_result_str'), 'workflow', '', 'Тема исчерпана? yes | no (подпоток с GBNF); пусто — не спрашивали'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw
                    AND CAST(`name` AS BINARY) = CAST(CONCAT('workflow_invoke_', @me, '_result_str') AS BINARY));

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion',
         CAST(REPLACE('[{"variable": "chat_word_range", "text": "[<if workflow_invoke_{{ME}}_result_str == ''yes'' and !make_initiative and text_length_range_check_9225_result_length <= 12>]8-18[<else>][<if make_initiative or text_length_range_check_9225_result_length == 0>]%dice_chat_word%[<else>][<if dice_chat_scale == ''shorter''>][<if text_length_range_check_9225_result_length <= 3>]1-2[<else>][<if text_length_range_check_9225_result_length <= 6>]1-3[<else>][<if text_length_range_check_9225_result_length <= 12>]2-5[<else>][<if text_length_range_check_9225_result_length <= 25>]3-10[<else>]5-18[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''longer''>][<if text_length_range_check_9225_result_length <= 3>]6-14[<else>][<if text_length_range_check_9225_result_length <= 6>]9-20[<else>][<if text_length_range_check_9225_result_length <= 12>]14-30[<else>][<if text_length_range_check_9225_result_length <= 25>]25-45[<else>]35-70[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''much_longer''>][<if text_length_range_check_9225_result_length <= 12>]18-40[<else>][<if text_length_range_check_9225_result_length <= 25>]35-70[<else>]50-100[<endif>][<endif>][<else>][<if text_length_range_check_9225_result_length <= 3>]1-6[<else>][<if text_length_range_check_9225_result_length <= 6>]2-10[<else>][<if text_length_range_check_9225_result_length <= 12>]4-16[<else>][<if text_length_range_check_9225_result_length <= 25>]6-28[<else>]10-45[<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>]"}, {"variable": "chat_word_check", "text": "[<if workflow_invoke_{{ME}}_result_str == ''yes'' and !make_initiative and text_length_range_check_9225_result_length <= 12>]5-24[<else>][<if make_initiative or text_length_range_check_9225_result_length == 0>]%dice_chat_word%[<else>][<if dice_chat_scale == ''shorter''>][<if text_length_range_check_9225_result_length <= 3>]1-4[<else>][<if text_length_range_check_9225_result_length <= 6>]1-5[<else>][<if text_length_range_check_9225_result_length <= 12>]1-8[<else>][<if text_length_range_check_9225_result_length <= 25>]2-14[<else>]3-24[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''longer''>][<if text_length_range_check_9225_result_length <= 3>]4-20[<else>][<if text_length_range_check_9225_result_length <= 6>]6-26[<else>][<if text_length_range_check_9225_result_length <= 12>]10-38[<else>][<if text_length_range_check_9225_result_length <= 25>]18-55[<else>]25-85[<endif>][<endif>][<endif>][<endif>][<else>][<if dice_chat_scale == ''much_longer''>][<if text_length_range_check_9225_result_length <= 12>]12-55[<else>][<if text_length_range_check_9225_result_length <= 25>]25-90[<else>]35-130[<endif>][<endif>][<else>][<if text_length_range_check_9225_result_length <= 3>]1-10[<else>][<if text_length_range_check_9225_result_length <= 6>]1-14[<else>][<if text_length_range_check_9225_result_length <= 12>]2-22[<else>][<if text_length_range_check_9225_result_length <= 25>]4-35[<else>]6-55[<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>][<endif>]"}]', '{{ME}}', @me) AS JSON))
 WHERE `workflow_id` = @tw AND `title` = 'Коридор длины чата' AND `metadata` NOT LIKE '%8-18%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '=== What you need ===',
                 CONCAT(REPLACE('[<if workflow_invoke_{{ME}}_result_str == ''yes''>]=== Change the subject ===
The current subject has run its course — nothing new is left to say about it. In this reply:
- if his newest message has a question, answer it first, in a few words,
- then move to a new subject: %dice_chat_new_topic%. Pick something that is not in the history yet,
- build a bridge from what was just said ("by the way…", "that reminds me…", "speaking of…") — never jump abruptly,
- end with one light question about the new subject.

[<endif>]', '{{ME}}', @me), '=== What you need ===')))
 WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат' AND `metadata` NOT LIKE '%=== Change the subject ===%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '          * it ignores his last message or action (a photo, "sent", a goodbye) and jumps to an unrelated story.
',
                 CONCAT('          * it ignores his last message or action (a photo, "sent", a goodbye) and jumps to an unrelated story.
', REPLACE('[<if workflow_invoke_{{ME}}_result_str == ''yes''>]          * the current subject has run its course: REJECT a draft that stays on the old subject, and a draft that changes it abruptly without a bridge from what was said (a change with a bridge is exactly what is needed here),
[<endif>]', '{{ME}}', @me))))
 WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа' AND `metadata` NOT LIKE '%subject has run its course: REJECT%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '        girl_response_skip = 0 also when he says goodbye, gets upset or seems to be leaving — a reply that warmly keeps him is needed, silence lets the conversation die.
',
                 CONCAT('        girl_response_skip = 0 also when he says goodbye, gets upset or seems to be leaving — a reply that warmly keeps him is needed, silence lets the conversation die.
', REPLACE('[<if workflow_invoke_{{ME}}_result_str == ''yes''>]        girl_response_skip = 0 ALWAYS here: the current subject has run its course, and the draft moves the conversation to a new subject — silence after his short "ok" would let the conversation die.
[<endif>]', '{{ME}}', @me))))
 WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа' AND `metadata` NOT LIKE '%girl_response_skip = 0 ALWAYS here%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '"prompt_user_ignore": [<if answer_anyway == 1 >]takes the value 0 always',
                 REPLACE('"prompt_user_ignore": [<if answer_anyway == 1 or workflow_invoke_{{ME}}_result_str == ''yes''>]takes the value 0 always', '{{ME}}', @me)))
 WHERE `workflow_id` = @tw AND `title` = 'Анализ сообщения' AND `metadata` NOT LIKE '%_result_str == ''yes''>]takes the value 0 always%'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @tw AND `position` BETWEEN @pos - 1 AND @pos + 3) AS порядок,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.workflow_id') = @sub FROM `agent_workflow_step` WHERE `id` = @me) AS вызов_1,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат' AND `metadata` LIKE '%Change the subject%') AS писатель_1,
       (SELECT (LENGTH(`metadata`) - LENGTH(REPLACE(`metadata`, 'run its course: REJECT', ''))) / 22 FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа') AS судья_2,
       (SELECT `metadata` LIKE '%8-18%' FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Коридор длины чата') AS коридор_1
;
