-- Шаблон рассылки: метки и своё имя без учёта регистра, «hope your evening» (2026-11-17)
--
-- ЗАЧЕМ. Ревизия 89 живых шаблонов прода после 20261117100000:
--   1. Шаблон начинался «Companion_name,» — метка словом, с заглавной. Счёт
--      голых меток (`substr_count`) учитывал регистр и её не видел. Теперь все
--      счета «Счёт: …» и «Своё имя словами?» идут с `ignore_case`.
--   2. Прощание «I hope your evening is soft» регулярка времени суток не ловила —
--      добавлена ветка «hope/wish your (own) … evening». Ветка «your … evening»
--      вообще не годится: «what does your ideal morning look like» — законный
--      вопрос о мечте.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

UPDATE `agent_workflow_variable` SET `default` = '(?im)(\\bgood\\s*(?:morning|afternoon|evening|night)\\b|\\bgoodnight\\b|\\btonight\\b|\\bthis\\s+(?:morning|afternoon|evening)\\b|\\b(?:have|having|enjoy|enjoying)\\s+(?:a|an|your)\\s+(?:\\w+\\s+){0,2}(?:morning|afternoon|evening|night)\\b|\\b(?:hope|wish)\\s+(?:that\\s+)?your\\s+(?:own\\s+)?(?:\\w+\\s+){0,1}(?:morning|afternoon|evening|night)\\b|\\bsleep\\s+well\\b|\\bsweet\\s+dreams\\b|^[ \\t]*(?:morning|afternoon|evening|night)(?=\\s*[,.!]))'
 WHERE `workflow_id` = @mw AND `name` = 'mail_time_pattern'
;

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'mail_mark_ignore_case', 'workflow', '1',
       'Счёт меток и своего имени без учёта регистра: «Companion_name» — тоже метка словом'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'mail_mark_ignore_case');

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.ignore_case', 'mail_mark_ignore_case')
 WHERE `workflow_id` = @mw
   AND (`title` LIKE 'Счёт: %' OR `title` = 'Своё имя словами?')
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name')) = 'substr_count'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @mw
         AND JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.ignore_case') IS NOT NULL) AS счётов_без_регистра_11,
       (SELECT LOCATE('hope|wish', `default`) > 0 FROM `agent_workflow_variable`
         WHERE `workflow_id` = @mw AND `name` = 'mail_time_pattern') AS регулярка_1
;
