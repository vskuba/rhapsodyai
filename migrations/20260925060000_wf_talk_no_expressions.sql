-- Выражений в значениях не остаётся: значение ставит ветка (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Предыдущая миграция убрала литералы `_const_` из `inputs_map` — но два значения
-- я задал **выражением**:
--
--     talk_session_kind    = %if mail_mode%mail%else%chat%endif%
--     girl_response_final  = %if girl_response_fixed%…%else%…%endif%
--
-- Выражение в значении — та же беда, что литерал, только спрятанная глубже. Оно
-- заново решает то, что **уже решено переходами**: развилка на шаге «Ответ в чат»
-- разводит письма и чат, судья ставит правку или не ставит. Второе место, где то же
-- условие вычисляется иначе, разойдётся с первым на первой же правке — и разойдётся
-- молча.
--
-- Правило: значение — либо переменная, либо простой текст, положенный шагом. Условие
-- живёт **в переходах**, и только там.
--
-- ## Что делается
--
--     «Ключи»                  talk_session_kind = chat      (простой текст)
--     после «Письмо первым»     talk_session_kind = mail      новый шаг
--     после «Ответ на письмо»   talk_session_kind = mail      новый шаг
--     «Ответ: правка судьи»     girl_response_final = %girl_response_fixed%
--     «Ответ: исходный»         girl_response_final = %girl_response%
--
-- ## ⚠⚠ Почему у канала «chat» — умолчание, а «mail» ставят ветки
--
-- Веток четыре: чат, письмо первым, ответ на письмо, инициатива. Чат и инициатива
-- пишутся в канал `chat`, письма — в `mail`. Шаг на каждую дал бы четыре шага там,
-- где хватает двух: `chat` ставится нулевым шагом как основа, а обе почтовые ветки
-- её перекрывают.
--
-- ⚠ Это **не** «условие наизнанку»: каждая запись — простой текст, и кто её
-- поставил, видно по шагу. Порядок задан маршрутом, а не вычислением.
--
-- ## ⚠⚠ Переходы приходится ПЕРЕНАЦЕЛИВАТЬ, иначе новый шаг минуют
--
-- Ветки писем уходят на судью **прыжком по `step_id`** (`prompt_user exists`), а не
-- к соседу по номеру. Вставь шаг сразу за ветку — прыжок его перескочит, и канал
-- останется прежним. Поэтому у каждой почтовой ветки цель прыжка меняется на новый
-- шаг, а новый шаг прыгает на судью тем же условием.
--
-- ## ⚠⚠ Правка судьи разводится переходом `empty`
--
--     «Ответ: правка судьи»  before: girl_response_fixed empty → «Ответ: исходный»
--                            after:  → «Разговор: записать ответ»
--     «Ответ: исходный»      падает к записи по номеру
--
-- То есть правка есть — работает первый шаг и прыгает через второй; правки нет —
-- первый минуется, работает второй. Ни одного `%if%`.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @conv = (SELECT `id` FROM `agent_workflow_step_type`
              WHERE `name` = 'variable_conversion');

SET @keys = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.variable_conversion[1].variable')) = 'girl_unique_id' LIMIT 1);
SET @judge = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Валидация ответа' LIMIT 1);
SET @said = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'companion_session_add'
                AND JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.inputs_map.answer') IS NOT NULL LIMIT 1);
-- Почтовые ветки узнаём по развилке: на них уводит шаг чата своими условиями.
SET @write = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Письмо первым' LIMIT 1);
SET @reply = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Ответ на письмо' LIMIT 1);
-- Мой прежний шаг с выражением — его заменяют два новых.
SET @old = (SELECT `id` FROM `agent_workflow_step`
             WHERE `workflow_id` = @wf AND `title` = 'Ответ: итоговый' LIMIT 1);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `metadata` LIKE '%\%if %') AS шагов_с_выражением,
       COALESCE(@old, 0) AS прежний_шаг,
       COALESCE(@write, 0) AS письмо, COALESCE(@reply, 0) AS ответ_на_письмо;

-- ── 1. Переменную канала объявляем каналом чата простым текстом ──────────────
--
-- ⚠ Место записи ищем, а не берём номером: порядок задан прошлой миграцией, но
-- полагаться на него — значит сломаться от любой ручной правки шага.
--
-- ⚠⚠ `JSON_SEARCH` отдаёт **путь** (`$[6]`), а не номер, и склейка его в
-- `$.variable_conversion[$[6]].text` даёт «Invalid JSON path expression». Номер
-- вынимается отдельно — цифры из пути.
SET @slot = (SELECT REGEXP_REPLACE(JSON_UNQUOTE(JSON_SEARCH(
                      JSON_EXTRACT(`metadata`, '$.variable_conversion[*].variable'),
                      'one', 'talk_session_kind')), '[^0-9]', '')
               FROM `agent_workflow_step` WHERE `id` = @keys);

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REPLACE(`metadata`,
         CONCAT('$.variable_conversion[', @slot, '].text'), 'chat')
 WHERE `id` = @keys AND @keys IS NOT NULL
   AND @slot IS NOT NULL AND @slot <> '';

-- ── 2. Прежний шаг с выражением уходит ──────────────────────────────────────
DELETE FROM `agent_workflow_step` WHERE `id` = @old AND @old IS NOT NULL;

-- ── 3. Два шага канала — по одному на почтовую ветку ────────────────────────
--
-- ⚠ Позиции берём «рядом с веткой» и не двигаем соседей: нумерация у этого
-- workflow с разрывами с прежних правок, а порядок держат переходы.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @conv, one.`title`,
       (SELECT MAX(`position`) + 1 FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf),
       JSON_OBJECT('variable_conversion', JSON_ARRAY(JSON_OBJECT(
                     'text', 'mail', 'variable', 'talk_session_kind')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY(JSON_OBJECT(
                     'step_id', CAST(@judge AS CHAR), 'variable', 'prompt_user',
                     'operator', 'exists', 'value', '')))
  FROM (        SELECT 'Канал: письмо первым' AS `title`
          UNION SELECT 'Канал: ответ на письмо') AS one
 WHERE @wf IS NOT NULL AND @conv IS NOT NULL AND @judge IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf AND x.`title` = one.`title`);

SET @kwrite = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf
                  AND `title` = 'Канал: письмо первым' LIMIT 1);
SET @kreply = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf
                  AND `title` = 'Канал: ответ на письмо' LIMIT 1);

-- ── 4. Ветки писем уходят теперь на свой шаг канала ─────────────────────────
--
-- ⚠⚠ Меняем **цель прыжка**, а не порядок: прыжок и есть то, чем ветка кончается.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.transitions_after[0].step_id', CAST(@kwrite AS CHAR))
 WHERE `id` = @write AND @write IS NOT NULL AND @kwrite IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.transitions_after[0].step_id', CAST(@kreply AS CHAR))
 WHERE `id` = @reply AND @reply IS NOT NULL AND @kreply IS NOT NULL;

-- ── 5. Два шага итогового ответа вместо выражения ───────────────────────────
--
-- ⚠ Позиции: правка судьи стоит **перед** записью ответа, исходный — сразу за ней.
-- Порядок важен: «исходный» должен доставаться тому, кто минул первый шаг.
SET @at = (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @said);

UPDATE `agent_workflow_step`
   SET `position` = `position` + 2
 WHERE `workflow_id` = @wf AND `position` >= @at AND @at IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf
                      AND x.`title` = 'Ответ: правка судьи');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @conv, 'Ответ: исходный', @at + 1,
       JSON_OBJECT('variable_conversion', JSON_ARRAY(JSON_OBJECT(
                     'text', '%girl_response%', 'variable', 'girl_response_final')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @at IS NOT NULL AND @conv IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf AND x.`title` = 'Ответ: исходный');

SET @orig = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'Ответ: исходный' LIMIT 1);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @conv, 'Ответ: правка судьи', @at,
       JSON_OBJECT('variable_conversion', JSON_ARRAY(JSON_OBJECT(
                     'text', '%girl_response_fixed%',
                     'variable', 'girl_response_final')),
                   'transitions_before', JSON_ARRAY(JSON_OBJECT(
                     'step_id', CAST(@orig AS CHAR),
                     'variable', 'girl_response_fixed',
                     'operator', 'empty', 'value', '')),
                   'transitions_after', JSON_ARRAY(JSON_OBJECT(
                     'step_id', CAST(@said AS CHAR), 'variable', 'prompt_user',
                     'operator', 'exists', 'value', '')))
 WHERE @at IS NOT NULL AND @conv IS NOT NULL AND @orig IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf
                      AND x.`title` = 'Ответ: правка судьи');

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Выражений в значениях не остаётся ни одного — это и есть цель.
       --
       -- ⚠ Шаг «Влить придуманные факты» из счёта исключён намеренно: он **старше**
       -- этих правок (миграции его только упоминают, INSERT-а нет ни в одной), и
       -- склейка фактов там — чужое решение. Не исключи мы его, проверка всегда
       -- показывала бы единицу и перестала бы что-либо значить.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_EXTRACT(`metadata`, '$.variable_conversion') IS NOT NULL
           AND `metadata` LIKE '%\%if %'
           AND `title` <> 'Влить придуманные факты') AS выражений_в_значениях,
       -- ⚠ Литералов тоже нет — прошлая миграция не отменяется этой.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `metadata` LIKE '%_const_%') AS литералов,
       -- ⚠⚠ Четыре новых шага обязаны быть на месте: не будь их, канал и ответ
       -- остались бы пустыми, и запись разговора легла бы без текста.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `title` IN ('Канал: письмо первым', 'Канал: ответ на письмо',
                           'Ответ: правка судьи', 'Ответ: исходный')) AS новых_шагов,
       -- ⚠ Прежний шаг с выражением убран.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ответ: итоговый') AS прежний_остался,
       -- ⚠⚠ Ветки писем ведут на свои шаги канала, а не прямо на судью.
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.transitions_after[0].step_id'))
          FROM `agent_workflow_step` WHERE `id` = @write) AS письмо_ведёт_на,
       COALESCE(@kwrite, 0) AS шаг_канала_письма;
