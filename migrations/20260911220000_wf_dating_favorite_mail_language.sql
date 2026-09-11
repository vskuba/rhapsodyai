-- `dating_favorite_mail_write`: привязать `user_language` (2026-09-11)
--
-- ЧТО БЫЛО. Заводящая миграция привязала переменные условием `v.type =
-- 'workflow'` — и из четырёх привязались три. `user_language` в этой базе
-- **глобальная** (#120, `type = 'global'`), и фильтр её отсёк молча: накат
-- отчитался «переменных 3» там, где ожидалось 4.
--
-- ⚠ ПОЧЕМУ ЭТО ВАЖНО, А НЕ КОСМЕТИКА. Язык письма — не вкусовщина: фильтр сайта
-- отклоняет кириллицу («Message not delivered. Unacceptable words: …»), и письмо
-- на русском не дойдёт до человека вовсе. Ровно на этом уже спотыкались инвайты:
-- первый прогон дал все реплики по-русски, потому что язык не был задан.
--
-- ⚠ ФИЛЬТР ПО ТИПУ ВООБЩЕ ЛИШНИЙ. Он стоял там от `invite_companion_name`, где
-- имя занято дважды (#73 global, #81 input) и выбирать приходилось. Здесь имена
-- уникальны, и сужать по типу значило требовать от соседней базы того, чего она
-- не обещала.
--
-- Идемпотентность: привязка по условию отсутствия.

SET @wf = (SELECT `id` FROM `agent_workflow`
            WHERE `name` = 'dating_favorite_mail_write');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'user_language'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных,
       (SELECT GROUP_CONCAT(v.`name` ORDER BY v.`name`)
          FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @wf) AS какие;
