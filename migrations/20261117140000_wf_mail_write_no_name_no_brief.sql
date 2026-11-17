-- Шаблон рассылки: снят шаг «Своё имя словами?» и зачины прошлых писем у писателя (2026-11-17)
--
-- ЗАЧЕМ. Проба шести анкет на проде после 20261117130000: три прогона из шести
-- упёрлись в 240 с, переписывая письмо по 7–10 раз.
--   1. Шаг «Своё имя словами?» возвращал письмо Yana шесть раз подряд с той же
--      причиной: модель подписывается именем, сколько её ни проси. А имя
--      девушки в её же заготовке — правда, не брак (решение владельца от
--      17.10.2026, повторено 17.11.2026). Шаг, его счёт и его причина сняты.
--   2. Писатель КОПИРОВАЛ зачины из блока «как начинались её прошлые письма —
--      начни иначе» (`mail_avoid_brief`): STELA пять раз начала её же прошлым
--      «Do you ever notice how the world gets quieter…», Elena девять раз —
--      «There is a specific kind of silence…», и судья всякий раз честно
--      отвечал «повтор». Блок снят с промпта; повторы ловит судья — он видит
--      прошлые письма целиком. Входная переменная остаётся объявленной: панель
--      её шлёт, а необъявленная отвечает 400.

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @me = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Своё имя словами?');

SET @why = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Что не так');

-- Причина про имя — до удаления шага: в ней его номер.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.variable_conversion[0].text')),
                 REPLACE('[<if substr_count_{ME}_result_qty != ''0''>]your own name %girl_title% is written as a plain word — never write it: about yourself only «I», and [[girl_name]] stands only on the last line as the signature. [<endif>]

', '{ME}', @me), ''))
 WHERE `id` = @why AND @me IS NOT NULL
;

DELETE FROM `agent_workflow_variable`
 WHERE `workflow_id` = @mw AND @me IS NOT NULL
   AND CAST(`name` AS BINARY) = CAST(CONCAT('substr_count_', @me, '_result_qty') AS BINARY);

DELETE FROM `agent_workflow_step` WHERE `id` = @me;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '[<if mail_avoid_brief>]=== How her previous letters began — begin differently ===
    %mail_avoid_brief%
[<endif>]

', ''))
 WHERE `workflow_id` = @mw AND `title` = 'Письмо'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Своё имя словами?') AS шаг_имени_0,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `id` = @why AND `metadata` LIKE '%is written as a plain word — never%') AS причина_имени_0,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `title` = 'Письмо'
         AND `metadata` LIKE '%mail_avoid_brief%') AS зачины_у_писателя_0,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @mw AND `position` >= 23) AS хвост
;
