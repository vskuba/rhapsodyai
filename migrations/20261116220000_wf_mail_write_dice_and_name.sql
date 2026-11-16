-- Шаблон рассылки: доли новых осей до сотни и проверка «своё имя словами» (2026-11-16)
--
-- ЗАЧЕМ. Живая проба миграции 20261116200000 на проде (четыре шаблона Solomia):
--
--   1. У инструмента `dice` доли — ПРОЦЕНТЫ, и недобор до ста значит «иногда не
--      выпадает ничего». У новых осей сумма вышла 28–70: при виде `feel` ось
--      `dice_mail_feel` приходила пустой, и письмо писалось без эмоции, ради
--      которой вид и выпал. Доли пересчитаны пропорционально до ровной сотни.
--   2. Модель пишет СВОЁ имя словами — «I'm Solomia» в тексте, «Solomia» в
--      подписи вместо [[girl_name]]. Проверки на это не было: прежние счёты
--      ищут слово «girl_name», а не само имя. Теперь имя у workflow есть
--      (`girl_title` от панели), и шаг `substr_count` возвращает такое письмо
--      на переписку. Пустой `girl_title` (старая панель, кнопка без анкеты) —
--      шаг пропускается.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON),
         '$.dice_mail_day', CAST('{"a slow walk along the river embankment, and one small thing that caught your eye": 7, "coffee with a girlfriend and a walk afterwards": 7, "the way home after work, and what you noticed on it": 7, "a trip to the market for something simple, and a little scene there": 6, "an errand that went a little wrong, and how the evening turned out cozy anyway": 5, "a sudden change of weather that caught you outside": 5, "a lunch break outside the office, ten quiet minutes in the fresh air": 5, "cooking something new in the evening, and how it turned out": 5, "an evening walk in the park near home, alone with your thoughts": 5, "a small kindness from a stranger today": 4, "a busy, tiring day at work and the first quiet moment after it": 7, "a lazy morning that refused to start, and how the day finally got going": 4, "taking photos of ordinary things on the way and one picture you liked": 4, "a bookshop or a little shop you wandered into without a plan": 4, "music you heard on the street or in a café, and the mood it brought": 4, "an evening at home: tea, a blanket, the window, and thoughts before sleep": 5, "a short trip out of the centre on a bus or a tram, looking out of the window": 4, "a girlfriend''s small problem you helped with today": 4, "the first cold morning that made you look for warm clothes": 4, "a café where you sat longer than planned, watching people": 4}' AS JSON),
         '$.dice_mail_feel', CAST('{"life has been tiring lately — work, routine, the same days — and she wants to complain a little to someone who will understand": 6, "a bad day: everything went wrong, and she wishes for someone to tell her it was not her fault": 5, "tired after a long day: the shoulders ache, she wishes someone would knead them — and catches herself imagining his hands": 7, "cold outside, cold fingers: she wants someone to warm her hands in his — and wonders what his hands are like": 6, "a quiet, slightly lonely evening: everything is fine, but there is no one to tell about the day — so she tells him": 7, "a good mood she cannot keep to herself: she wants to share it with someone who would smile back": 6, "sleepy and soft at the end of the day: she wishes for a calm voice to fall asleep to": 5, "a little restless: she wants to walk somewhere together without a plan, just talking": 4, "she cooked or baked something and wishes there were someone to taste it and say it is good": 4, "a long week behind: she dreams of a lazy morning with no alarm, coffee in bed, someone next to her": 6, "she misses simple touch — a hug from behind, a hand on her back — and admits it a little shyly": 6, "curiosity about him that would not let her go today: she keeps guessing what kind of man he is": 4, "a light sadness after the day: she does not want advice, just someone to listen": 4, "a small victory today and no one to celebrate it with — a wish to share it with him": 4, "she felt pretty today and secretly wished someone had noticed": 4, "stress and a heavy head: she wishes someone would just say «it is okay, come here»": 4, "playful: she wants to tease him a little and see if he can play along": 4, "she wants to be taken care of for once — someone to bring her tea and cover her with a blanket": 6, "the day reminded her how much she wants someone to come home to": 4, "she laughed at something silly today and wishes he had been there to laugh with her": 4}' AS JSON),
         '$.dice_mail_news', CAST('{"she finally started something she had been putting off for months": 11, "a small change at work — new tasks, a new project, a new desk": 11, "she bought something small for herself and is happier about it than she expected": 11, "she signed up for something new: a class, a course, a dance or a language": 11, "she rearranged her room and it feels like a new home": 7, "she got good news from a close girlfriend and is still smiling": 7, "she made a decision about her life she is proud of": 7, "she found an old photo or a letter of hers that brought back memories": 7, "she tried a new recipe and it became her new favourite": 7, "the first real cold (or the first warm days) arrived and changed her routine": 7, "she had a funny small adventure on the way somewhere": 7, "she finished a book or a series and cannot stop thinking about the ending": 7}' AS JSON),
         '$.dice_mail_dream', CAST('{"the sea: a quiet morning on a beach somewhere warm, nobody in a hurry": 11, "a little house of her own with a garden, a porch and evenings outside": 11, "to travel far, to a country she has only seen in pictures": 11, "a slow Sunday together with someone — breakfast, a walk, no phones": 11, "to dance with someone who leads well, in a place where nobody knows her": 7, "to learn something she always wanted but never dared to": 7, "a road trip with music, stops in small towns and no plan": 7, "to wake up next to someone who is genuinely glad she is there": 11, "a big family dinner at a long table, with laughter and too much food": 7, "to see snow in the mountains, or the northern lights, at least once": 7, "simple things: to be someone''s priority, not an option": 10}' AS JSON)) AS CHAR)
 WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec'
;

SET @has_name = (SELECT COUNT(*) FROM `agent_workflow_step`
                  WHERE `workflow_id` = @mw AND `title` = 'Своё имя словами?');

SET @para = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @mw AND `title` = 'Вопрос отдельным абзацем?');

SET @para_pos = (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @para);

SET @why = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @mw AND `title` = 'Что не так');

UPDATE `agent_workflow_step` SET `position` = `position` + 1
 WHERE `workflow_id` = @mw AND `position` >= @para_pos AND @has_name = 0
 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @mw, 3, 'Своё имя словами?', @para_pos,
       CAST(REPLACE(REPLACE('{"tool_invoke": {"tool_name": "substr_count", "inputs_map": {"haystack": "letter_draft", "needle": "girl_title"}, "outputs_map": {}}, "transitions_before": [{"variable": "girl_title", "operator": "empty", "value": "", "step_id": "{{PARA}}"}], "transitions_after": [{"variable": "substr_count_{{ME}}_result_qty", "operator": "!=", "value": "0", "step_id": "{{WHY}}"}], "to_next_step": true}', '{{PARA}}', @para), '{{WHY}}', @why) AS JSON)
 WHERE @has_name = 0;

SET @me = (SELECT `id` FROM `agent_workflow_step`
             WHERE `workflow_id` = @mw AND `title` = 'Своё имя словами?');

UPDATE `agent_workflow_step`
   SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR), '{{ME}}', @me) AS JSON)
 WHERE `id` = @me;

-- ⚠ Счёт объявлен с умолчанием «0»: шаг бывает пропущен, а условие «Что не так»
-- на необъявленной переменной не сворачивается, а остаётся в тексте.
INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, CONCAT('substr_count_', @me, '_result_qty'), 'workflow', '0',
       'Сколько раз её имя стоит в письме словами. Ноль — шаг пропущен или имени нет'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `workflow_id` = @mw AND CAST(`name` AS BINARY) = CAST(CONCAT('substr_count_', @me, '_result_qty') AS BINARY));

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         CONCAT(REPLACE('[<if substr_count_{{ME}}_result_qty != ''0''>]your own name %girl_title% is written as a plain word — never write it: about yourself only «I», and [[girl_name]] stands only on the last line as the signature. [<endif>]

', '{{ME}}', @me),
                JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.variable_conversion[0].text'))))
 WHERE `id` = @why
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.variable_conversion[0].text')) NOT LIKE '%your own name%'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @mw AND `position` >= 23) AS хвост,
       (SELECT `default` FROM `agent_workflow_variable`
         WHERE `workflow_id` = @mw AND CAST(`name` AS BINARY) = CAST(CONCAT('substr_count_', @me, '_result_qty') AS BINARY)) AS счёт
;
