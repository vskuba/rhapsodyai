-- Письмо проверяется и на выдуманные переменные (2026-09-07)
--
-- ЧТО БЫЛО. Цикл проверок заработал: переменные в письме есть всегда, язык всегда
-- английский. Но из трёх прогонов в двух модель сослалась на `[[city]]` —
-- переменной, которой в реестре сайта нет.
--
-- ЦЕНА. Такое письмо не сохранится вовсе: DatingAi проверяет имена по реестру и
-- отвечает отказом. Человек ждал ответа агента, а получил ошибку — и должен сам
-- искать в тексте, что не так.
--
-- ОТЧЕГО ТАК. Проверка `B` спрашивает «есть ли хоть одна переменная», и `[[city]]`
-- ей подходит: она ищет форму, а не имя. Список допустимых имён есть в промпте, но
-- это снова просьба, а не проверка.
--
-- ЧТО ВМЕСТО. Ещё один шаг: спросить у модели, все ли переменные письма есть в
-- списке. ⚠ **Не регуляркой** — та умеет найти `[[что-то]]`, но сверить с
-- произвольным списком имён, приходящим переменной, ей нечем. Сверка «список
-- против списка» — работа для модели.
--
-- Порядок шагов после вставки:
--
--   A(0) Письмо              → B
--   B(1) Есть переменные?    пусто → E
--   C(2) Язык верный?        0 → E
--   D(3) Переменные из списка? 0 → E, 1 → G
--   E(4) Попытка             → F
--   F(5) Что не так          попыток < 3 → A
--   G(6) Готово
--
-- ⚠ У `C` убран переход «1 → G»: раньше он вёл прямо к выдаче, а теперь между
-- ними появилась проверка `D`. Оставь мы его — новая проверка не выполнялась бы
-- никогда, и это самая тихая из возможных поломок.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);
SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);
SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);
SET @f = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);
SET @g = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       @e AS счётчик, @f AS подсказка, @g AS выдача;

-- ------------------------------------------- Сдвигаем хвост
--
-- ⚠ Сверху вниз (5 → 6, затем 4 → 5, затем 3 → 4): обратный порядок затёр бы
-- соседнюю позицию, потому что уникальности у неё нет.
UPDATE `agent_workflow_step` SET `position` = 6 WHERE `id` = @g;
UPDATE `agent_workflow_step` SET `position` = 5 WHERE `id` = @f;
UPDATE `agent_workflow_step` SET `position` = 4 WHERE `id` = @e;

-- ------------------------------------------- D: только известные переменные
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 2, 'Переменные из списка?', 3,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'letter_vars_ok',
                       'text', '1 — все переменные письма есть в списке, 0 — есть лишние')),
         'prompt_user', CONVERT(CONCAT(
           'Разрешённые переменные:', @nl, '%mail_vars%', @nl, @nl,
           'Письмо:', @nl, '%letter%', @nl, @nl,
           'Все ли [[переменные]] письма есть в списке разрешённых?', @nl,
           'Верни JSON: {"letter_vars_ok": 1} или {"letter_vars_ok": 0}')
           USING utf8mb4))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 3);

SET @d = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);

-- ------------------------------------------- Переходы
--
-- C: язык не тот — на счётчик. Перехода «1 → G» больше нет: дальше идёт проверка D.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_lang_ok', 'operator', '==',
                    'value', '0', 'step_id', CAST(@e AS CHAR))))
 WHERE `id` = @c;

-- D: есть лишние — на счётчик; всё чисто — к выдаче.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_vars_ok', 'operator', '==',
                    'value', '0', 'step_id', CAST(@e AS CHAR)),
        JSON_OBJECT('variable', 'letter_vars_ok', 'operator', '==',
                    'value', '1', 'step_id', CAST(@g AS CHAR))))
 WHERE `id` = @d;

-- ------------------------------------------- Подсказка знает про третий промах
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion', JSON_ARRAY(
        JSON_OBJECT('variable', 'write_try',
                    'text', CONVERT(CONCAT('%counter_increment_', @e, '_result_int%')
                                    USING utf8mb4)),
        JSON_OBJECT('variable', 'write_hint', 'text', CONVERT(CONCAT(
          '%if !mail_var_found%в письме нет ни одной переменной [[имя]] — ',
          'имена написаны словами. %endif%',
          '%if !letter_lang_ok%письмо написано не на языке %user_language%. %endif%',
          '%if !letter_vars_ok%в письме есть переменные, которых нет в списке ',
          'разрешённых — используй только те, что даны. %endif%') USING utf8mb4))))
 WHERE `id` = @f;

-- ------------------------------------------- Переменная проверки
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'letter_vars_ok', 'workflow', '1', 'Все ли переменные письма есть в реестре'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'letter_vars_ok');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'letter_vars_ok'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       @d AS проверка_имён,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after'))
          FROM `agent_workflow_step` WHERE `id` = @c) AS переходов_у_языка;
