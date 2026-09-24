-- У девушки такая же запись и такой же ключ, как у собеседника (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Ключ девушки собирался в панели одной строкой — `elena_89`, имя и номер
-- слитно (`agent_name`). Это костыль: имя и номер **разные величины**, и слепив
-- их в одну переменную, мы получили `%girl_id%` там, где нужно имя. Прямо в
-- промпте разбора стояло «на этот вопрос **%girl_id%** должна ответить» —
-- модель читала «на этот вопрос elena_89 должна ответить».
--
-- Теперь как у собеседника: `girl_id` — номер, `girl_name` — имя, а ключ
-- склеивается шагом и виден в редакторе.
--
-- ## Что делает миграция
--
--     шаг «Ключи»          добавляется вторая склейка: girl_unique_id
--     шаг «Запись девушки» заводит ей запись в том же справочнике
--     четыре места         ключуются склейкой, а не слитым girl_id
--
-- ## ⚠⚠ Накопленные факты девушек станут недостижимы
--
-- Они лежат под `elena_89`, а искать станем `89_Elena`. На **проде это 116
-- фактов, 5 документов**; локально — тестовые. Перенос делается отдельным
-- запросом и осознанно: молча переложить их значило бы решить за человека, что
-- старые ключи больше не нужны.
--
-- ⚠ Сама миграция данных не трогает — только устройство.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @tool = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'tool_invoke');
SET @made = (SELECT COUNT(*) FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'Запись девушки');

SELECT 'ДО' AS этап, @made AS шаг_уже_есть,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ── Переменная ключа ────────────────────────────────────────────────────────
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'girl_unique_id', 'workflow', '',
       'Ключ записи девушки: её номер и имя. Склеивает шаг «Ключи»' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'girl_unique_id');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'girl_unique_id'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = @wf);

-- ── Вторая склейка в первом шаге ────────────────────────────────────────────
--
-- ⚠ Обе склейки одним шагом: они об одном — «чей это ключ», — и разнеси их по
-- двум, правка формата чинилась бы в двух местах. Заголовок шага меняется на
-- «Ключи»: он больше не только про собеседника.
UPDATE `agent_workflow_step`
   SET `title` = 'Ключи',
       `metadata` = JSON_ARRAY_APPEND(`metadata`, '$.variable_conversion',
           JSON_OBJECT('variable', 'girl_unique_id',
                       'text', '%girl_id%_%girl_name%'))
 WHERE `workflow_id` = @wf AND `title` = 'Ключ собеседника'
   AND JSON_SEARCH(`metadata`, 'one', 'girl_unique_id') IS NULL;

-- ── Запись девушки в том же справочнике ─────────────────────────────────────
--
-- ⚠ Ставим **третьим**: после склейки и записи собеседника. Порядок между двумя
-- записями безразличен, но соседство читается: сперва ключи, потом обе записи.
UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= 2 AND @made = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Запись девушки', 2,
       JSON_OBJECT('tool_invoke', JSON_OBJECT(
                       'tool_name', 'companion_create',
                       'inputs_map', JSON_OBJECT('unique_id', 'girl_unique_id',
                                                 'title', 'girl_name'),
                       'outputs_map', JSON_OBJECT()),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- ── Факты девушки ключуются склейкой ────────────────────────────────────────
--
-- ⚠ Точечно по пути JSON: метка сидит внутри JSON-строки, и лесенка
-- экранирования в SQL-литерале уже однажды не сошлась — замена прошла «удачно»,
-- не изменив ничего (`…_wf_talk_companion_key`).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         '{"document_id":"%girl_unique_id%"}')
 WHERE `workflow_id` = @wf AND `title` = 'Переменные'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.variable_conversion[0].variable')) = 'fact_collection_girl_filter';

-- ── Промпт разбора: ключ пары и имя вместо ключа ────────────────────────────
--
-- ⚠⚠ Две правки одной заменой, и вторая важнее первой. «На этот вопрос
-- %girl_id% должна ответить» — это **имя** в человеческой фразе, а там стоял
-- слитый ключ. Модель читала «на этот вопрос elena_89 должна ответить».
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%girl_id%_%companion_unique_id%',
                 '%girl_unique_id%_%companion_unique_id%'),
                 'вопрос %girl_id% должна', 'вопрос %girl_name% должна'))
 WHERE `workflow_id` = @wf AND `title` = 'Анализ сообщения';

-- ── Подпрогон придуманных фактов ────────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.workflow_invoke.inputs_map.girl_id', 'girl_unique_id')
 WHERE `workflow_id` = @wf AND `title` = 'girl_fact_create';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `title` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS шаг_1,
       (SELECT `title` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 1) AS шаг_2,
       (SELECT `title` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 2) AS шаг_3,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.variable_conversion'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ключи') AS склеек,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `metadata` LIKE '%girl\_unique\_id%') AS шагов_с_ключом,
       -- ⚠ Слитый ключ обязан уйти из промпта разбора совсем.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Анализ сообщения'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%\%girl\_id\%%') AS остался_girl_id,
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step` WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS d) AS позиции_столкнулись;
