-- Шаг записи ответа отдаёт номер обмена наружу (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- DatingAi должен сказать «эта реплика дошла», а сказать может только про
-- конкретную строку `companion_session`. Номер у неё есть — его возвращает
-- `companion_session_add`, — но наружу он не выходил.
--
-- Движок и так раскладывает результат инструмента по переменным
-- (`%companion_session_add_743_result_id%`); `outputs_map` даёт ему имя, под
-- которым его найдёт ручка `/chat/ask`.
--
-- ## ⚠ Шаг «тишины» (744) не трогаем
--
-- У него нет половины «ответ» — агент промолчал, доставлять нечего. Пустой
-- `message_id` в ответе `/chat/ask` это и означает, и отказом не является.
--
-- Идемпотентность: правка по условию — второй прогон видит `talk_message_id` на
-- месте и ничего не делает.

SET @step = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = (SELECT `id` FROM `agent_workflow`
                                      WHERE `name` = 'dating_talk')
                AND `metadata` LIKE '%companion_session_add%'
                AND `title` LIKE '%ответ%' LIMIT 1);

SELECT 'ДО' AS этап, @step AS шаг,
       (SELECT `metadata` LIKE '%talk_message_id%'
          FROM `agent_workflow_step` WHERE `id` = @step) AS уже_отдаёт;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.outputs_map.id',
                             'talk_message_id')
 WHERE `id` = @step
   AND `metadata` NOT LIKE '%talk_message_id%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_EXTRACT(`metadata`, '$.tool_invoke.outputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step) AS outputs_map;
