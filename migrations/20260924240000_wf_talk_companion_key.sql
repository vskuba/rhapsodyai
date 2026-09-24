-- Своя запись на каждого собеседника, и ключ фактов из её номера (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Собеседники ходили под **одной общей** записью справочника (`dating_person`,
-- `companion_id = 10`): поле обязательное, ведёт внешним ключом на
-- `agent_session`, и DatingAi подставлял туда одну на всех, а кто именно пишет —
-- передавал переменной `companion_name`.
--
-- Работало это потому, что факты ключевались самой переменной. Но имя ей врало:
-- в «имени собеседника» лежал ключ `dating_343_128282`, и всякий, кто правил
-- промпт, видел не то, что там на самом деле.
--
-- Теперь запись заводится **на человека**, и её номер становится настоящим
-- ключом: факты Gerard и Bartholomew расходятся сами собой, а не потому, что
-- кто-то не забыл подставить переменную.
--
-- ## Два шага, и оба в начале
--
--     1. Ключ собеседника   склеивает `%companion_id%_%companion_name%`
--     2. companion_create   заводит запись, если её ещё нет
--
-- ⚠⚠ **Склейка отдельным шагом, а не внутри инструмента.** Собрать ключ мог бы и
-- он — но тогда правило «из чего ключ состоит» лежало бы в коде, а читают
-- workflow в редакторе. Шаг «Ключ собеседника» показывает состав прямо в списке.
--
-- ⚠ И склейка нужна **дважды**: ею же уходим в Qdrant (шаг «Переменные» и
-- промпт разбора). Один шаг на оба применения — иначе два места собирали бы ключ
-- порознь и разошлись бы на первой правке.
--
-- ## ⚠ Почему в начале
--
-- Ключ нужен шагу «Анализ сообщения» (он велит модели, каким `document_id`
-- помечать факты) и подпрогону `companion_fact_extract` — оба идут рано. Ставить
-- склейку позже значило бы искать, какой шаг первым её спросит.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @conv = (SELECT `id` FROM `agent_workflow_step_type`
              WHERE `name` = 'variable_conversion');
SET @tool = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'tool_invoke');
SET @made = (SELECT COUNT(*) FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'Ключ собеседника');

SELECT 'ДО' AS этап, @made AS шаги_уже_есть,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ── Переменная ключа ────────────────────────────────────────────────────────
--
-- ⚠ Тип `workflow`: её кладёт шаг внутри прогона, снаружи не присылают.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'companion_unique_id', 'workflow', '',
       'Ключ записи собеседника: номер общей записи и кто именно пишет' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'companion_unique_id');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'companion_unique_id'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = @wf);

-- ── Место под два шага ──────────────────────────────────────────────────────
--
-- ⚠⚠ Сдвиг только когда шагов ещё нет: без оговорки повторный прогон раздвинул
-- бы позиции снова, и склейка отстала бы от тех, кто её ждёт.
UPDATE `agent_workflow_step`
   SET `position` = `position` + 2
 WHERE `workflow_id` = @wf AND @made = 0;

-- ── Шаг 1: склейка ──────────────────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @conv, 'Ключ собеседника', 0,
       JSON_OBJECT('variable_conversion', JSON_ARRAY(JSON_OBJECT(
                       'variable', 'companion_unique_id',
                       'text', '%companion_id%_%companion_name%')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- ── Шаг 2: заведение записи ─────────────────────────────────────────────────
--
-- ⚠ `title` — отображаемое имя: в списке собеседников панели человек должен
-- зваться «Gerard», а не ключом.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'companion_create', 1,
       JSON_OBJECT('tool_invoke', JSON_OBJECT(
                       'tool_name', 'companion_create',
                       'inputs_map', JSON_OBJECT('unique_id', 'companion_unique_id',
                                                 'title', 'companion_title'),
                       'outputs_map', JSON_OBJECT()),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- ── Факты ключуются склейкой ────────────────────────────────────────────────
--
-- ⚠ Три места, и все три обязаны взять одно значение: промпт разбора велит
-- модели, чем помечать факты, шаг «Переменные» — чем их искать, а подпрогон
-- кладёт их в документ. Разойдись они — записанное не нашлось бы.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%companion_name%''', '%companion_unique_id%'''))
 WHERE `workflow_id` = @wf AND `title` = 'Анализ сообщения';

-- ⚠⚠ Здесь метка сидит **внутри JSON-строки**, и вокруг неё экранированные
-- кавычки: `{\"document_id\":\"%companion_name%\"}`. Повторить эту лесенку в
-- SQL-литерале я уже пробовал — замена молча не сработала, и репетиция показала
-- старый ключ там, где ждали новый.
--
-- Поэтому правим **точечно, по пути JSON**: `JSON_SET` кладёт готовое значение
-- целиком, и экранирование делает сама база. Заодно видно, что именно получится.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[1].text',
         '{"document_id":"%companion_unique_id%","tags":"%prompt_user_tags%"}')
 WHERE `workflow_id` = @wf AND `title` = 'Переменные'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.variable_conversion[1].variable')) = 'fact_collection_man_filter';

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.workflow_invoke.inputs_map.companion_name', 'companion_unique_id')
 WHERE `workflow_id` = @wf AND `title` = 'companion_fact_extract';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `title` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS первый_шаг,
       (SELECT `title` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 1) AS второй_шаг,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `metadata` LIKE '%companion\_unique\_id%') AS шагов_с_ключом,
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step` WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS d) AS позиции_столкнулись;
