-- Шаблон рассылки: зачины, невозможные в первом письме, и пример заметок дня (2026-11-17)
--
-- ЗАЧЕМ. Проба восьми анкет на проде после 20261117150000:
--   1. В жребии зачинов `dice_mail_greeting` 17% веток противоречат самому
--      письму — первому, незнакомцу, в любой час: цитата «его последних слов»
--      («You once said…» — он ещё ничего не писал), «давно не виделись» и «пишу
--      снова» (две ветки и ещё одна), приветствие по времени суток и «Evening»
--      вместо «Good evening» — последние две гнали письмо в круг переписываний
--      шагом «Время суток словами?». Ветки сняты, их доля роздана остальным
--      пропорционально, сумма ровно сто. Точка с запятой в ветке «NO GREETINGS»
--      собирается CHAR(59): запускатель миграций режет файл по ней.
--   2. Один прогон из двенадцати вернул пример заметок из промпта дня дословно.
--      Пример заменён на явно чужой, с запретом брать его содержимое.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @dw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_day_invent');

UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON), '$.dice_mail_greeting',
         CAST(REPLACE('{"a short greeting without a name, on its own line": 5, "start with his name alone, no greeting word at all": 2, "an ordinary greeting with his name, on its own line": 5, "open mid-thought, as if you had been talking already": 4, "greet him in lower case, carelessly, as in a messenger": 4, "start with one word, then a full stop — then the letter": 2, "skip the greeting and start with what you were doing just now": 4, "start with his name and a question mark, nothing else in that line": 4, "a greeting and a question in the same breath, no pause between them": 2, "greet warmly but without his name — he will feel it is for him anyway": 2, "open with where you are writing from — the kitchen, the train, the bed": 4, "open with an interjection or a call — the way you hail someone you know": 5, "put the greeting at the very end of the first paragraph, not at its start": 4, "greet with a question instead of a greeting word — «how is it going there?»": 3, "greet him right where you name him: the greeting and the name are one first phrase": 5, "open with a quiet apology for writing out of nowhere — one phrase, no grovelling": 3, "open with a thought out loud, weave the greeting into the middle of the first phrase": 5, "open with a filler — «so», «well», «right» — as people do when they start talking": 3, "begin with «listen» or «look» — as if continuing a conversation he did not hear the start of": 10, "open with an interjection or a call — the way you hail someone you know — and name him at once": 7, "NO GREETINGS. No “Hi,” “Hello,” “Hey” — not with a name, not without{SEMI} not on its own line, not within a sentence": 17}', '{SEMI}', CHAR(59)) AS JSON)) AS CHAR)
 WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '(example: «new desk by the window · moved files and pens · pastry and tea in the corner café · golden leaves on the pavement · felt calmer»)', '(the shape, about someone else — never reuse its content: «missed my bus · walked instead · a dog followed me two streets · bought chestnuts · laughed at myself»)'))
 WHERE `workflow_id` = @dw AND `title` = 'День'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(CAST(`default` AS JSON), '$.dice_mail_greeting') FROM `agent_workflow_variable`
         WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec') AS веток_21,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec'
         AND `default` LIKE '%quoting his own last words%') AS цитата_0,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `title` = 'День'
         AND `metadata` LIKE '%missed my bus%') AS пример_1
;
