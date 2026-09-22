-- Анкета собеседника, когда фактов о нём ещё нет (2026-09-22)
--
-- ЗАЧЕМ. Агент чата узнаёт о человеке из **фактов**: их извлекает из переписки
-- `companion_fact_extract`, а ищет шаг 9 (`qdrant_fact_search_companion`).
--
-- В начале разговора фактов нет и быть не может — извлекать ещё не из чего. И
-- агент пишет человеку, не зная о нём ничего, хотя у DatingAi его анкета есть:
-- имя, возраст, город, страна и рассказ о себе с сайта знакомств. На проде из
-- 736 карточек рассказ снят у 537, имя и возраст — у всех.
--
-- Заводим переменную `companion_bio`: DatingAi кладёт в неё эту анкету одним
-- текстом, а промпт автора подставляет её **только тогда, когда фактов не
-- нашлось**.
--
-- ⚠⚠ ИМЕННО «ВМЕСТО», А НЕ «ВМЕСТЕ». Дать и то, и другое значило бы дать модели
-- два источника об одном человеке, а они расходятся: в анкете «Семейное
-- положение: Single», а в разговоре он упомянул жену. Модель не знает, какой
-- источник свежее, и возьмёт тот, что удобнее фразе. Факты свежее по
-- устройству — их кладёт разговор, идущий сейчас; анкета написана однажды и
-- часто давно.
--
-- Отсюда `%else%`, а не второй `%if%` рядом.
--
-- ⚠ ВЛОЖЕННЫЙ `%if%` — ЗАКОННЫЙ. Разворачивает блоки `ai_workflow_if_blocks_render`
-- изнутри наружу в цикле, и внутренний разбирается первым. Второй `%if%` нужен
-- затем, что анкеты может не быть вовсе (карточку ещё не снимали): пустой
-- заголовок «Анкета на сайте знакомств ===» без строк под ним модель читает как
-- «анкета пуста», то есть как факт.
--
-- ⚠ ЗАГОЛОВОК РАЗНЫЙ. «Информация в базе данных» — это наши факты из разговора;
-- «Анкета на сайте знакомств» — то, что человек написал о себе сам. Назови мы
-- их одинаково, модель не отличила бы «он сказал мне» от «так написано в
-- профиле» — и сослалась бы на анкету словами «ты же говорил».
--
-- ⚠ УМОЛЧАНИЕ ПУСТОЕ, и переменная необязательная: не передали — ведём себя как
-- раньше. `%if%` считает ложными пустое, `'0'` и отсутствие
-- (`ai_workflow_variable_truthy`).
--
-- Тип `workflow`, как у `talk_history` и `companion_uid`: это ровно те же
-- переменные — их кладёт DatingAi на каждый вызов. Тип `input` у `girl_id` —
-- про другое: он приходит из настройки агента.
--
-- Идемпотентность: переменная и связь заводятся проверкой на наличие, промпт
-- переписывается только там, где новой ветки ещё нет.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'companion_bio') AS переменная_есть,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%companion_bio%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 12) AS есть_в_промпте;

-- ── Переменная ──────────────────────────────────────────────────────────────

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'companion_bio', 'workflow', '',
       'Анкета собеседника с сайта знакомств одним текстом: имя, возраст, город, рассказ о себе. Кладёт DatingAi. Идёт в промпт, только если фактов о нём не нашлось'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'companion_bio');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'companion_bio'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ── Шаг 12: «Генерация ответа». Анкета вместо ненайденных фактов ────────────
--
-- ⚠ Позиция 12, а не номер шага: номера `id` у каждой базы свои
-- (`auto_increment`), и миграция, написанная под локальные, на проде правила бы
-- чужой шаг. Позиция — часть самого workflow и совпадает везде.

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(
           JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
           CONCAT(
             '%if qdrant_fact_search_38_result_str%\n',
             '=== Информация о %companion_title% в базе данных ===\n',
             '%qdrant_fact_search_38_result_str%\n',
             '%endif%'),
           CONCAT(
             '%if qdrant_fact_search_38_result_str%\n',
             '=== Информация о %companion_title% в базе данных ===\n',
             '%qdrant_fact_search_38_result_str%\n',
             '%else%%if companion_bio%\n',
             '=== Анкета %companion_title% на сайте знакомств ===\n',
             '⚠ Это он написал о себе сам при регистрации, а не сказал тебе в разговоре. Ссылаться на это словами «ты же говорил» нельзя — он тебе этого не говорил.\n',
             '%companion_bio%\n',
             '%endif%%endif%')))
 WHERE `workflow_id` = @wf AND `position` = 12
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%companion_bio%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'companion_bio') AS переменная_есть,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE v.`name` = 'companion_bio' AND vw.`workflow_id` = @wf) AS связь_есть,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%companion_bio%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 12) AS есть_в_промпте;
