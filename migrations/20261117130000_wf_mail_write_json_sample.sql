-- Шаблон рассылки: писателю возвращён образец JSON (2026-11-17)
--
-- ЗАЧЕМ. 20261117100000 заменила образец ответа {"letter_draft": "text of the
-- letter"} словами — модель вернула его однажды вместо письма. Без образца она
-- стала отвечать голым текстом: «В ответе LLM отсутствуют обязательные ключи
-- воркфлоу: ['letter_draft']», повтор за повтором, и прогон упирался в 240 с —
-- четыре из шести проб на проде легли по таймауту. Образец вернулся, вместо
-- текста письма в нём многоточие: вернуть его как письмо модели незачем, а
-- вернёт — панель не запишет заготовку короче 40 слов.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), 'Return JSON with one key letter_draft — the whole letter as a string. Never return the words of this instruction instead of a letter.', 'Return strictly one JSON object and nothing before or after it: {"letter_draft": "..."} — the whole letter goes inside the string in place of the dots, paragraphs separated by \\n.'))
 WHERE `workflow_id` = @mw AND `title` = 'Письмо'
;

SELECT 'ПОСЛЕ' AS этап, COUNT(*) AS образец_1 FROM `agent_workflow_step`
 WHERE `workflow_id` = @mw AND `title` = 'Письмо'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%{"letter_draft": "..."}%'
;
