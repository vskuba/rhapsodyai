-- Осиротевший workflow `dating_mail_reply` убран (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Ответы на письма переехали в ветку `dating_talk` («Ответ на письмо», миграция
-- `…010000_wf_talk_branches`): агент `mail_reply_<сайт>` смотрит теперь туда, и
-- на этот workflow не ссылается **ни один** агент. Пять шагов, десять связей с
-- переменными — и никакого способа их запустить.
--
-- Мёртвый workflow хуже отсутствующего: его видно в списке, его правят по
-- ошибке, а правка не доезжает никуда. Так уже вышло сегодня — тесты папки
-- `tests_llm/dating_mail_reply/` падали с `400`, потому что звали агента,
-- который давно ходит другой дорогой.
--
-- ## ⚠ Что уходит вместе с ним
--
-- Семь переменных, которые больше нигде не объявлены:
--
--     reply_try, reply_hint, reply_lang_ok, reply_clean_ok,
--     reply_topic_ok, reply_safe_ok, mail_history
--
-- ⚠⚠ Общие **не трогаем**: `girl_card` объявлена у четырёх workflow,
-- `companion_card` у трёх, `chat_timeout` у восьми. Реестр
-- `agent_workflow_variable` один на все занятия, и удаление по имени сломало бы
-- соседей — тех, о ком мы тут не думали.
--
-- ## ⚠ Прогоны остаются
--
-- У `agent_workflow_trace.workflow_id` внешний ключ `ON DELETE SET NULL`: 28
-- прошлых прогонов сохранятся, потеряв ссылку на workflow. Это верно — журнал
-- отвечает на вопрос «что было», и стирать историю ради чистоты справочника
-- нельзя. Связи переменных уходят сами, у них `CASCADE`.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_reply');

SELECT 'ДО' AS этап, COALESCE(@wf, 0) AS workflow,
       (SELECT COUNT(*) FROM `agent` WHERE `workflow_id` = @wf) AS агентов,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `agent_workflow_trace` WHERE `workflow_id` = @wf) AS прогонов;

-- ⚠⚠ **Проверка перед сносом, а не доверие к памяти.** Появись у workflow агент
-- между написанием миграции и её применением — дальше идти нельзя: снос унёс бы
-- работающее занятие. Условие стоит в каждом запросе, потому что миграцию
-- применяют и через месяц.

-- ── Свои переменные: те, что больше нигде не объявлены ──────────────────────
--
-- ⚠ Порядок: сначала переменные (пока связь цела и видно, чьи они), потом сам
-- workflow. Снеси его первым — `CASCADE` унесёт связи, и «чьи это переменные»
-- станет неизвестно.
DELETE v FROM `agent_workflow_variable` v
  JOIN `agent_workflow_variable_workflow` vw ON vw.`variable_id` = v.`id`
 WHERE vw.`workflow_id` = @wf
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` <> @wf)
   AND NOT EXISTS (SELECT 1 FROM `agent` a WHERE a.`workflow_id` = @wf);

-- ── Шаги ────────────────────────────────────────────────────────────────────
DELETE FROM `agent_workflow_step`
 WHERE `workflow_id` = @wf
   AND NOT EXISTS (SELECT 1 FROM `agent` a WHERE a.`workflow_id` = @wf);

-- ── Сам workflow ────────────────────────────────────────────────────────────
DELETE FROM `agent_workflow`
 WHERE `id` = @wf
   AND NOT EXISTS (SELECT 1 FROM `agent` a WHERE a.`workflow_id` = @wf);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow` WHERE `name` = 'dating_mail_reply')
         AS остался_workflow,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf)
         AS остались_шаги,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('reply_try', 'reply_hint', 'reply_lang_ok',
                          'reply_clean_ok', 'reply_topic_ok', 'reply_safe_ok',
                          'mail_history')) AS остались_свои_переменные,
       -- ⚠ Общие обязаны уцелеть: их читают соседние занятия.
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('girl_card', 'companion_card', 'chat_timeout'))
         AS общие_целы;
