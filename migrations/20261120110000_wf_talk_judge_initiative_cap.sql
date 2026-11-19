-- Судья: своя ветка у инициативы и предохранитель от бесконечных переписываний (2026-11-20)
--
-- ЗАЧЕМ. Прод за трое суток: инициатива — 608 прогонов, 6,3 черновика в среднем,
-- максимум 84, у 62% три и больше. Судья проверял её веткой обязательного ответа
-- («it answers exactly what he wrote»), а инициатива пишет первой, когда он
-- молчит: «simon has not written anything yet in this turn» — отказ за отказом.
-- Письма — 9,5 черновика и 45 с: писатель выдумывал «you mentioned…», судья
-- честно отвергал. Предела у круга не было никакого.
--
-- ЧТО.
--   1. Судье — ветка инициативы (make_initiative): не требует отвечать на его
--      реплику, проверяет повтор, упрёк, эскалацию, выдумку, встречу на словах.
--   2. Писателям писем — запрет ссылаться на его слова, которых нет в переписке.
--   3. Шаги «Сколько раз переписывали» и «Предохранитель: итог» за судьёй. В
--      счётчик ведут отказ судьи И провал проверки длины (она и была главным
--      кругом: инициатива в 17 слов против жребия «20-45» — без предела). До
--      четвёртого отказа — снова писать. На четвёртом: отказ судьи у инициативы
--      или письма — молчать, иначе черновик уходит, а проверка длины на этой
--      попытке пропускает любую. Принятый судьёй черновик идёт мимо счётчика.
--   4. Судье писем — правило мессенджера «до 20 слов» к письму не относится, и
--      история ЧАТА: писатель письма видит обе переписки, судья видел только письма
--      и отвергал как выдумку то, что он сам рассказал в чате («tiny fado bar»).

SET @tw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SET @judge = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа');

SET @write = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат');

SET @silence = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Разговор: записать тишину');

SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Сколько раз переписывали');

SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `id` = @judge);

SET @next = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `position` = @pos);

UPDATE `agent_workflow_step` SET `position` = `position` + 2
 WHERE `workflow_id` = @tw AND `position` >= @pos AND @has = 0 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 3, 'Сколько раз переписывали', @pos,
       CAST(REPLACE('{"tool_invoke": {"tool_name": "counter_increment", "inputs_map": {"value": "counter_increment_{{ME}}_result_int"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [{"variable": "counter_increment_{{ME}}_result_int", "operator": "<", "value": "4", "step_id": "{{WRITE}}"}], "to_next_step": true}', '{{WRITE}}', @write) AS JSON)
 WHERE @has = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 5, 'Предохранитель: итог', @pos + 1,
       CAST(REPLACE('{"variable_conversion": [{"variable": "cap_silence", "text": "[<if girl_response_accepted != 1 and make_initiative == 1 or girl_response_accepted != 1 and mail_mode == 1>]1[<endif>]"}], "transitions_before": [], "transitions_after": [{"variable": "cap_silence", "operator": "==", "value": "1", "step_id": "{{SILENCE}}"}], "to_next_step": true}', '{{SILENCE}}', @silence) AS JSON)
 WHERE @has = 0;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'cap_silence', 'workflow', '', 'Предохранитель сработал на отказе судьи у инициативы или письма — молчать'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'cap_silence');

SET @me = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Сколько раз переписывали');

UPDATE `agent_workflow_step`
   SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR), '{{ME}}', @me) AS JSON)
 WHERE `id` = @me;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, CONCAT('counter_increment_', @me, '_result_int'), 'workflow', '0', 'Сколько раз судья отверг черновик в этом прогоне'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw
                    AND CAST(`name` AS BINARY) = CAST(CONCAT('counter_increment_', @me, '_result_int') AS BINARY));

-- Отказ судьи — в счётчик, а не прямо на переписывание.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', CAST(REPLACE(
         CAST(JSON_EXTRACT(`metadata`, '$.transitions_after') AS CHAR),
         CONCAT('"step_id": "', @write, '", "operator": "!=", "variable": "girl_response_accepted"'),
         CONCAT('"step_id": "', @me, '", "operator": "!=", "variable": "girl_response_accepted"')) AS JSON))
 WHERE `id` = @judge;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_ARRAY_APPEND(`metadata`, '$.transitions_after',
         JSON_OBJECT('variable', 'girl_response_accepted', 'operator', '==', 'value', '1', 'step_id', CAST(@next AS CHAR)))
 WHERE `id` = @judge AND CAST(JSON_EXTRACT(`metadata`, '$.transitions_after') AS CHAR) NOT LIKE CONCAT('%"step_id": "', @next, '"%');

-- Провал длины — тоже в счётчик, а не прямо на переписывание.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after[0].step_id', CAST(@me AS CHAR))
 WHERE `workflow_id` = @tw AND `title` = 'Длина ответа соответствует?'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[0].step_id')) = CAST(@write AS CHAR);

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         CONCAT('[<if counter_increment_', @me, '_result_int >= 4>]1-1000[<else>]', '[<if mail_mode>]%dice_mail_word%[<else>][<if chat_word_check>]%chat_word_check%[<else>]%dice_chat_word%[<endif>][<endif>]', '[<endif>]'))
 WHERE `workflow_id` = @tw AND `title` = 'Требуемая длина ответа' AND `metadata` NOT LIKE '%1-1000%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '[<if mail_mode>]You are a strict editor.', '[<if mail_mode>]You are a strict editor. ⚠ This is a LETTER: the messenger rule about one or two sentences and 20 words from the system prompt does NOT apply here — never reject a letter for being long or having several paragraphs.'))
 WHERE `id` = @judge AND `metadata` NOT LIKE '%This is a LETTER: the messenger rule%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         CONCAT(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '[<if answer_anyway>]You are a strict editor. This answer is MANDATORY', CONCAT('[<if make_initiative == 1>]You are a strict editor of an initiative line: %companion_title% is silent, and %girl_title% writes to him first, after a pause. This is NOT an answer — never require it to answer his last message or to stay on his last topic.

        Check the draft:
        - it is written in language %user_language%,
        - it has content and sounds like a real person in a messenger, not an empty line or a single interjection,
        - it does not repeat what she has already said or asked in the history — the same question, the same idea or the same phrase is a REJECT,
        - no reproach or complaint about his silence, no "why don''t you answer", no apology for writing,
        - REJECT any sexual or intimate line unless his OWN latest messages in this chat are sexual — escalating to a silent man reads as spam,
        - it does not invent what he said, asked or promised, and states no invented facts about the world or his city ("did you know…"),
        - if it touches a meeting or a video call: a warm yes in words, without date, place or app — never a refusal,
        - it talks from the first person of %girl_title%.

        ⚠ Check ONLY these rules. The choice of topic, the style and the length are NOT reasons to reject. If you hesitate between 0 and 1, write 1.

        === Important information about final response ===
        Please return your response in JSON format. The JSON response must contain follow keys:
        - "girl_response_skip": always 0
        - "girl_response_accepted": 0 or 1, where 1 - the draft is acceptable, 0 - send it for a repeat pass
        - "girl_response_accepted_why": name the exact rule from the list above that was broken, one sentence. If accepted - an empty string

        Example of JSON response:
        {
        "girl_response_skip": 0,
        "girl_response_accepted": 1,
        "girl_response_accepted_why": ""
        }
    [<else>]', '[<if answer_anyway>]You are a strict editor. This answer is MANDATORY')), '\n[<endif>]'))
 WHERE `id` = @judge AND `metadata` NOT LIKE '%editor of an initiative line%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '4. ⚠ Do not retell the whole correspondence or quote it verbatim: one vivid detail that he will recognize is enough.', '4. ⚠ Do not retell the whole correspondence or quote it verbatim: one vivid detail that he will recognize is enough. ⚠⚠ Refer only to what is literally written in the correspondence above: never invent that he said, asked, mentioned or promised something ("you mentioned", "you asked me", "you told me"). Not sure the line is there — do not refer to it, tell something new instead.'))
 WHERE `workflow_id` = @tw AND `title` = 'Письмо фавориту' AND `metadata` NOT LIKE '%Refer only to what is literally written%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '5. ⚠ Do not paraphrase his letter in your own words and do not quote it verbatim: he knows what he wrote.', '5. ⚠ Do not paraphrase his letter in your own words and do not quote it verbatim: he knows what he wrote. ⚠⚠ Refer only to what is literally written in the correspondence above: never invent that he said, asked, mentioned or promised something ("you mentioned", "you asked me", "you told me"). Not sure the line is there — do not refer to it, tell something new instead.'))
 WHERE `workflow_id` = @tw AND `title` = 'Ответ на письмо' AND `metadata` NOT LIKE '%Refer only to what is literally written%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), REPLACE('[<if mail_mode>]
    [<if talk_history_mail>]=== Correspondence by letters with %companion_title% (time in square brackets{SEMI} “she” — you) ===
        %talk_history_mail%
    [<endif>]
[<else>]', '{SEMI}', CHAR(59)), REPLACE('[<if mail_mode>]
    [<if talk_history_chat>]=== Chat conversation with %companion_title% (time in square brackets{SEMI} “she” — she) — the same man, he remembers it ===
        %talk_history_chat%
    [<endif>]

    [<if talk_history_mail>]=== Correspondence by letters with %companion_title% (time in square brackets{SEMI} “she” — you) ===
        %talk_history_mail%
    [<endif>]
[<else>]', '{SEMI}', CHAR(59))))
 WHERE `id` = @judge AND `metadata` NOT LIKE '%the same man, he remembers it%'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `position` BETWEEN @pos - 1 AND @pos + 1) AS порядок,
       (SELECT CAST(JSON_EXTRACT(`metadata`, '$.transitions_after') AS CHAR) LIKE CONCAT('%', @me, '%girl_response_accepted%') FROM `agent_workflow_step` WHERE `id` = @judge) AS отказ_в_счётчик_1,
       (SELECT `metadata` LIKE '%editor of an initiative line%' FROM `agent_workflow_step` WHERE `id` = @judge) AS ветка_1,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` IN ('Письмо фавориту','Ответ на письмо') AND `metadata` LIKE '%Refer only to what is literally written%') AS письма_2,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[0].step_id')) = CAST(@me AS CHAR) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Длина ответа соответствует?') AS длина_в_счётчик_1,
       (SELECT `metadata` LIKE '%1-1000%' FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Требуемая длина ответа') AS предел_длины_1,
       (SELECT `metadata` LIKE '%This is a LETTER%' FROM `agent_workflow_step` WHERE `id` = @judge) AS судья_письма_1,
       (SELECT `metadata` LIKE '%the same man, he remembers it%' FROM `agent_workflow_step` WHERE `id` = @judge) AS судья_чат_1
;
