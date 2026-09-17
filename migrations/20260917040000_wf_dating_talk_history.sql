-- `dating_talk`: история разговора приходит переменной от панели (2026-09-17)
--
-- ЧТО НЕ ТАК БЫЛО. Промпт ответа читает историю из шага `session_messages`, а тот
-- берёт её по `session_uuid`. DatingAi этот ключ **не передаёт** — и правильно:
-- запрос к LLM прошлого не помнит, а история переписки уже лежит у панели, в её
-- собственной таблице.
--
-- Выходило, что на каждый вызов здесь рождалась новая сессия, история в ней была
-- пуста, а секция «История переписки» не появлялась вовсе (она под `%if%`).
-- Агент отвечал, видя **одну строку** — ту реплику, на которую отвечает: ни
-- своего приглашения, которым начался разговор, ни того, что человек писал
-- вчера. Проверено по базе: у чат-агента три сессии за всё время, последняя от 2
-- сентября — следы ручных проверок из админки, а не работа.
--
-- ЧТО СТАВИМ. Секцию, читающую переменную `talk_history`: её кладёт панель из
-- своей `message`, где лежат и ответы человека, и перенесённые приглашения.
-- Формат — одна реплика на строку, старое сверху:
--
--     [16.09 21:04] она: Спорим, ты сейчас улыбнулся?
--     [17.09 08:12] он: Улыбнулся. Как тебя зовут?
--
-- ⚠ ШАГ `session_messages` ОСТАЁТСЯ, И УБИРАТЬ ЕГО НЕ НАДО. Он отдаёт пустоту
-- нашему случаю и настоящую историю тому, кто придёт с `session_uuid` — например
-- человеку, который пробует агента из чата админки. Его секция уже под `%if%`,
-- так что пустота ничего не портит.
--
-- ⚠ ДВЕ СЕКЦИИ НЕ СПОРЯТ. У сессии история «детально, время в скобках», у
-- панели — тот же вид. Придут обе (человек из админки по сессии, которой панель
-- ещё и историю передала) — модель увидит один разговор дважды, и это честнее
-- молчания: лучше повтор, чем потерянная реплика.
--
-- ⚠ КЛЮЧ СОБЕСЕДНИКА (`companion_uid`) ТОЖЕ ПРИХОДИТ. Сам промпт его не
-- показывает: человеку в реплике он не нужен. Заведён как переменная затем,
-- чтобы поиск фактов о мужчине шёл по нему, а не сливал всех в один документ —
-- та же беда, от которой у девушек стоит `girl_id`.
--
-- Идемпотентность: секция вставляется по якорю, повторный накат её не удвоит —
-- проверка `LIKE` стоит в условии.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%talk_history%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 10) AS история_есть;

-- ------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'talk_history', 'workflow',
       'Разговор пары строками, старое сверху. Кладёт DatingAi из своей message', ''
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'talk_history');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'companion_uid', 'workflow',
       'Ключ собеседника на сайте знакомств: по нему факты о нём не сливаются', ''
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'companion_uid');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('talk_history', 'companion_uid')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ------------------------------------------- Секция истории в промпт ответа
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%if session_messages_29_result_str%',
                 CONCAT('%if talk_history%=== Разговор с этим человеком ',
                        '(время в квадратных скобках; «она» — ты) ===\n',
                        '%talk_history%\n\n%endif%',
                        '%if session_messages_29_result_str%')))
 WHERE `workflow_id` = @wf AND `position` = 10
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) NOT LIKE '%talk_history%';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%talk_history%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 10) AS история_есть,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @wf
           AND v.`name` IN ('talk_history', 'companion_uid')) AS переменных_привязано;
