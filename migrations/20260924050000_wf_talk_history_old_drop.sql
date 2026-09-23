-- Убрать `talk_history`: окно выкладки закрыто (2026-09-24)
--
-- ## ⚠⚠ Условие применения выполнено — проверено 24.09.2026
--
-- Она снимает страховку, поставленную `20260923200000_wf_talk_history_two_channels`:
-- старое объявление `talk_history`, оставленное там **ради окна выкладки**.
--
-- Проекта два, выкладываются они не одновременно, а `/chat/ask` отвечает 400 на
-- незаявленную переменную. Пока на проде мог работать старый DatingAi, шлющий
-- `talk_history`, объявление было обязано существовать.
--
-- ## Когда применять
--
-- Когда **оба** проекта выложены и проверено, что новый DatingAi шлёт
-- `talk_history_chat` и `talk_history_mail`:
--
--     SELECT JSON_EXTRACT(variables_start, '$.talk_history') IS NOT NULL AS старая,
--            JSON_EXTRACT(variables_start, '$.talk_history_chat') IS NOT NULL AS новая
--       FROM agent_workflow_trace
--      WHERE workflow_id = (SELECT id FROM agent_workflow WHERE name = 'dating_talk')
--      ORDER BY id DESC LIMIT 5;
--
-- Все пять строк должны показать `старая = 0, новая = 1`. Если хоть одна с
-- `старая = 1` — на проде ещё крутится прежний код, и применять рано.
--
-- ⚠ Положить её в `migrations/` (без `pending/`) и выложить, а не выполнять
-- руками: так она попадёт в общий порядок и не потеряется.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'talk_history') AS старая,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `metadata` LIKE '%\%talk\_history\%%'
            OR `metadata` LIKE '%\%if talk\_history\%%'
            OR `metadata` LIKE '%"talk\_history"%') AS упоминаний_в_шагах;

-- ⚠ Только если в шагах её не осталось: живое упоминание означало бы, что
-- переименование прошло не везде, и снос объявления оставил бы промпт со
-- ссылкой в никуда.
DELETE v FROM `agent_workflow_variable` v
 WHERE v.`name` = 'talk_history'
   AND NOT EXISTS (
         SELECT 1 FROM `agent_workflow_step` s
          WHERE s.`metadata` LIKE '%\%talk\_history\%%'
             OR s.`metadata` LIKE '%\%if talk\_history\%%'
             OR s.`metadata` LIKE '%"talk\_history"%');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'talk_history') AS старая,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('talk_history_chat', 'talk_history_mail')) AS новых;
