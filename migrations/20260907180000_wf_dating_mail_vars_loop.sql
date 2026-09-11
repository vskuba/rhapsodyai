-- `dating_mail_vars` собирает JSON по настоящим ключам и проверяет себя (2026-09-07)
--
-- ЧТО БЫЛО. Один шаг: спросили LLM — отдали ответ как есть. Промпт перечислял
-- имена переменных списком, а нужный вид ответа показывал **примером** с
-- выдуманными ключами:
--
--     Пример ответа: {"girl_name": "Diana", "girl_city": "Kyiv"}
--
-- Модель должна была сообразить, что ключи надо взять не из примера, а из списка
-- выше. Это лишняя работа для неё и лишний повод ошибиться — тот же промах, что и
-- в письмах, где она выдумывала `city` вместо `girl_city`.
--
-- Проверки не было вовсе: что вернулось, то и уходило в базу. Пустые значения и
-- пропущенные ключи выяснялись потом, глазами человека на вкладке «Переменные».
--
-- ЧТО ВМЕСТО.
--
-- 1. **Заготовка вместо примера.** Вызывающая сторона (DatingAi) знает реестр и
--    передаёт `%mail_vars_json%` — готовый объект с настоящими ключами и пустыми
--    значениями. Модели остаётся вписать значения, а не строить структуру.
--
-- 2. **Проверка кодом.** `dict_fields_check` сверяет, все ли ключи заполнены, и
--    заодно отдаёт словарь строкой. ⚠ Спрашивать об этом модель бессмысленно: на
--    вопрос «всё ли заполнено?» она отвечает «да» почти всегда — так уже вышло с
--    проверкой переменных письма.
--
-- 3. **Цикл доработки.** Не заполнено — говорим, чего именно не хватает, и просим
--    ещё раз. Три попытки: если данных в анкете нет, четвёртая их не создаст.
--
-- ⚠ ИСЧЕРПАВ ПОПЫТКИ, ОТДАЁМ ЗАПОЛНЕННОЕ, А НЕ НИЧЕГО. Часть значений лучше
-- пустоты: письмо с одной незаполненной переменной не уйдёт, но остальные
-- переменные уже проставлены, и человеку останется дописать одну.
--
-- Шаги:
--
--   A(0) Значения       llm_to_json → values
--   B(1) Проверка       dict_fields_check; всё заполнено → E
--   C(2) Попытка        counter_increment
--   D(3) Чего не хватает variable_conversion; попыток < 3 → A
--   E(4) Готово         return_response_text → %vars_json%
--
-- ⚠ `values` кладётся движком как **словарь** (LLM вернула объект), и отдавать его
-- напрямую нельзя: `str(dict)` в Python даёт одинарные кавычки, которые не
-- разберутся как JSON. Поэтому в ответ уходит `%vars_json%` — строка от
-- инструмента.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_vars');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);

SELECT 'ДО' AS этап, @wf AS workflow_id, @a AS шаг,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` = 'dict_fields_check') AS инструмент;

-- ------------------------------------------- A: значения по заготовке
UPDATE `agent_workflow_step`
   SET `type_id` = 2,
       `title` = 'Значения',
       `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'values', 'text', 'значения переменных')),
        'prompt_user', CONVERT(CONCAT(
          '%if vars_hint%НЕ ЗАПОЛНЕНО: %vars_hint%', @nl,
          'Поищи эти сведения в анкете внимательнее.', @nl, @nl, '%endif%',
          'Заполни карточку анкеты для рассылки писем на сайте знакомств.', @nl, @nl,
          'Что известно об анкете:', @nl, '%girl_card%', @nl, @nl,
          'Какие поля нужны:', @nl, '%mail_vars%', @nl, @nl,
          'Правила:', @nl,
          '- значения на языке %user_language%;', @nl,
          '- бери из сведений об анкете, не выдумывай;', @nl,
          '- чего в анкете нет — оставь пустым;', @nl,
          '- значения короткие: имя, город, род занятий — не предложения.', @nl, @nl,
          'Верни JSON ровно с этими ключами, заполнив значения:', @nl,
          '{"values": %mail_vars_json%}') USING utf8mb4))
 WHERE `id` = @a;

-- ------------------------------------------- B: проверка заполненности
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Проверка', 1,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'dict_fields_check',
           'inputs_map', JSON_OBJECT('data', 'values', 'keys', 'mail_var_names'),
           'outputs_map', JSON_OBJECT('empty', 'vars_empty', 'json', 'vars_json')))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 1);

SET @b = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 1);

-- ------------------------------------------- C: счётчик попыток
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Попытка', 2,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'counter_increment',
           'inputs_map', JSON_OBJECT('value', 'vars_try'),
           'outputs_map', JSON_OBJECT()))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 2);

SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);

-- ------------------------------------------- D: чего не хватает
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 5, 'Чего не хватает', 3,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'variable_conversion', JSON_ARRAY(
           JSON_OBJECT('variable', 'vars_try',
                       'text', CONVERT(CONCAT('%counter_increment_', @c, '_result_int%')
                                       USING utf8mb4)),
           JSON_OBJECT('variable', 'vars_hint',
                       'text', CONVERT('%vars_empty%' USING utf8mb4))))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 3);

SET @d = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);

-- ------------------------------------------- E: отдать заполненное
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 4, 'Готово', 4,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'continue_workflow', false,
         'prompt_user', '%vars_json%')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 4);

SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);

-- ------------------------------------------- Переходы
--
-- B: пусто в `vars_empty` — заполнено всё, идём к выдаче мимо счётчика.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'vars_empty', 'operator', 'empty',
                    'value', '', 'step_id', CAST(@e AS CHAR))))
 WHERE `id` = @b;

-- D: попыток меньше трёх — просим заново; иначе следующий по порядку (E) отдаёт
-- то, что набралось.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'vars_try', 'operator', '<',
                    'value', '3', 'step_id', CAST(@a AS CHAR))))
 WHERE `id` = @d;

-- ------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_vars_json', 'workflow', '{}',
       'Заготовка ответа: JSON с настоящими ключами и пустыми значениями'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_vars_json');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'vars_try', 'workflow', '0', 'Сколько раз переспрашивали значения'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'vars_try');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'vars_hint', 'workflow', '', 'Какие поля остались незаполненными'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'vars_hint');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'vars_json', 'workflow', '{}', 'Заполненные значения строкой — то, что уходит в ответ'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'vars_json');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'vars_empty', 'workflow', '', 'Незаполненные ключи через запятую'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'vars_empty');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_vars_json', 'mail_var_names', 'vars_try', 'vars_hint',
                    'vars_json', 'vars_empty', 'values')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS испорчен,
       @b AS проверка, @c AS счётчик, @d AS подсказка, @e AS выдача;
