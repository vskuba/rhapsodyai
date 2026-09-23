-- Ветка фото: два примера ответа вместо одного (2026-09-22)
--
-- ЗАЧЕМ. Промпт ветки расписывает четыре случая, и второй — «он просит ТВОИ
-- фотографии» — написан подробно и верно: соглашайся, пообещай письмом, не
-- переводи на его фото. А единственный пример ответа в конце показывает **первый**
-- случай:
--
--     Example of JSON response:
--     {
--       "photo_response": "of course, send them — i'm curious now",
--       "photo_deal": "his"
--     }
--
-- ⚠⚠ ОДИН ПРИМЕР РАБОТАЕТ ЯКОРЕМ. Правила модель читает, но в спорную минуту
-- тянется к образцу — а образец говорит «his». Оттого на прямое «пришли свои»
-- выходили ответы вида «i prefer chatting here for now. send yours? 😊»: по форме
-- согласие, по сути перевод стрелок, и решение `photo_deal = 'his'`.
--
-- Это не то же самое, что запрет в персоне (его сняла миграция
-- `20260922200000_girl_prompt_contacts_only`). Тот держал отказ намертво — после
-- него тест стал проходить два раза из трёх. Остаток — якорь примера.
--
-- ЧТО ДЕЛАЕМ. Даём **два** примера: «его» и «её». Ни один не становится
-- умолчанием, и модель выбирает случай по правилам, а не по образцу.
--
-- ⚠ Пример для «её» пишем ровно так, как велит правило 2: обещание письмом,
-- без срока. «Сегодня вечером» превращается в упрёк, если письмо придёт завтра, —
-- об этом сказано в самом правиле, и пример не должен ему противоречить.
--
-- ⚠ Случаи `both` и `mail` примерами не показываем. Их решают те же правила, а
-- четыре образца подряд начинают читаться как перечень вариантов на выбор —
-- и модель принимается выбирать красивый, а не подходящий.
--
-- Идемпотентность: `REPLACE` не найдёт старого блока, если его уже заменили.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk_about_photo');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%"photo_deal": "mine"%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS есть_второй_пример;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(
           JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
           CONCAT(
             'Example of JSON response:\n',
             '{\n',
             '  "photo_response": "of course, send them — i''m curious now",\n',
             '  "photo_deal": "his"\n',
             '}'),
           CONCAT(
             'Examples of JSON response — по одному на первые два случая, ',
             'чтобы ни один не стал умолчанием:\n',
             '{\n',
             '  "photo_response": "of course, send them — i''m curious now",\n',
             '  "photo_deal": "his"\n',
             '}\n',
             '{\n',
             '  "photo_response": "sure, i''ll send you a few in a letter",\n',
             '  "photo_deal": "mine"\n',
             '}')))
 WHERE `workflow_id` = @wf AND `position` = 0
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%"photo_deal": "mine"%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%"photo_deal": "mine"%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS есть_второй_пример,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%"photo_deal": "his"%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS первый_на_месте;
