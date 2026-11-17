-- Шаблон рассылки: день девушки заметками и без сверхдлинных писем (2026-11-17)
--
-- ЗАЧЕМ. Проба шести анкет на проде после 20261117140000:
--   1. Подпоток отдавал день готовой прозой (90–150 слов), и писатель вставлял её
--      абзацем почти дословно (STELA, Natalia) — письмо выходило из двух текстов.
--      Теперь день приезжает 4–6 заметками через « · »: пересказать их придётся
--      своими словами. Факты дня (`girl_day_facts`) это не трогает.
--   2. Ветка длины «420–810 words» (15%): маленькая модель заполняет такой объём
--      повторами — 651 слово у Nadezhda, «I am bad at…» десятком раз. Ветка
--      урезана до 300–450 слов и 10%, отнятые 5% ушли среднему письму.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @dw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_day_invent');

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '"girl_day": what happened, as a short first-person story, 90–150 words, English, plain text without markdown.', '"girl_day": what happened, as 4–6 short NOTES separated by « · » — fragments of 3–8 words each, NOT sentences and NOT a story, in order (example: «new desk by the window · moved files and pens · pastry and tea in the corner café · golden leaves on the pavement · felt calmer»), English, plain text.'))
 WHERE `workflow_id` = @dw AND `title` = 'День'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 'This really happened to me. It is the material of the letter: tell it in your own words', 'These are my notes of what really happened — notes, not a text. They are the material of the letter: turn them into my own story in my own words, choose what matters and in which order'), 'Do not copy the sentences above.', 'Do not list the notes one after another.'))
 WHERE `workflow_id` = @mw AND `title` = 'Письмо'
;

UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON), '$.dice_mail_length',
         CAST('{"1-2 paragraphs, short — 75–105 words, bold and warm": 15, "2-4 paragraphs, no more than 105–200 words": 55, "3-5 paragraphs, 200–420 words": 20, "4-5 paragraphs, 300–450 words": 10}' AS JSON)) AS CHAR)
 WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `title` = 'День'
         AND `metadata` LIKE '%4–6 short NOTES%') AS день_заметками_1,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Письмо'
         AND `metadata` LIKE '%notes, not a text%' AND `metadata` LIKE '%list the notes one after another%') AS писатель_1,
       (SELECT JSON_EXTRACT(CAST(`default` AS JSON), '$.dice_mail_length') FROM `agent_workflow_variable`
         WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec') AS длина
;
