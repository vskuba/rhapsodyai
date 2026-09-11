-- `dating_mail_write` проверяет себя и переписывает письмо, если оно негодно (2026-09-07)
--
-- ЧТО БЫЛО. Workflow состоял из одного шага: спросили LLM — отдали ответ. Два
-- требования держались только просьбой в промпте, и модель их теряла: три прогона
-- подряд дали разное число переменных (две, одну, ни одной), а до правки языка —
-- ещё и русский текст при `languages = en`.
--
-- Порядок правил и объяснение причины помогают, но не обещают: инструкция для LLM
-- — это пожелание, а не контракт. Проверять надо там, где можно проверить.
--
-- ЧТО ВМЕСТО. Workflow сам проверяет свой ответ и, если тот не годится, отдаёт
-- его на переписывание — с указанием, что именно не так. Проверяются два условия,
-- каждое своим способом:
--
--   переменные — `text_regex_extract`: ищет `[[имя]]` в тексте. Это машинная
--                проверка, и ошибиться она не может;
--   язык       — вопросом к LLM: «письмо на %user_language%?». Определение языка
--                — задача для модели, а не для регулярки: письмо из английских
--                слов с русской фразой посередине регулярка не отличит.
--
-- ⚠ ПОЧЕМУ ЦИКЛ, А НЕ ОТКАЗ. Отказ вернул бы человеку пустоту после ожидания, и
-- он нажал бы кнопку снова — то есть сделал бы то же самое руками. Цикл делает это
-- сам, и человек видит уже годный черновик.
--
-- ⚠ ПОЧЕМУ СЧЁТЧИК. Без него негодный ответ крутил бы цикл до таймаута, сжигая
-- вызовы LLM. Три попытки: если модель не справилась трижды, четвёртая не поможет,
-- а человек всё равно правит черновик глазами. Исчерпав их, отдаём как есть —
-- письмо с изъяном полезнее пустоты: его видно и можно поправить.
--
-- ⚠ ПОЧЕМУ ПОДСКАЗКА, А НЕ ПОВТОР ТОГО ЖЕ ПРОМПТА. Повторный запрос без объяснения
-- даёт тот же ответ: модель не знает, что ошиблась. `write_hint` говорит ей, что
-- именно не так, и подставляется условным блоком `%if%` — на первой попытке его
-- нет, и промпт остаётся чистым.
--
-- Шаги и потоки:
--
--   A(0) Письмо        llm_to_json → letter
--   B(1) Есть переменные?  text_regex_extract; пусто → E
--   C(2) Язык верный?      llm_to_json → letter_lang_ok; 0 → E, 1 → G
--   E(3) Попытка           counter_increment → номер
--   F(4) Что не так        variable_conversion; попыток < 3 → A
--   G(5) Готово            return_response_text → %letter%
--
-- Успех: A → B → C → G. Промах: A → B|C → E → F → A. Исчерпание: F → G.
--
-- Идемпотентность: условие на то, что шагов ещё один.

-- ---------------------------------------------------------------- До
SET @nl = CONCAT(CHAR(92), 'n');
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);

SELECT 'ДО' AS этап, @wf AS workflow_id, @a AS шаг_письма,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ------------------------------------------- A: письмо становится llm_to_json
--
-- ⚠ Тип меняется с `return_response_llm` на `llm_to_json`: первый **завершает**
-- workflow своим ответом, и проверить его было бы уже негде. Второй кладёт ответ
-- в переменную и отдаёт ход дальше.
--
-- Промпт сохраняем прежний (он выверен живыми прогонами), дописывая к нему две
-- вещи: блок доработки и требование вернуть JSON.
UPDATE `agent_workflow_step`
   SET `type_id` = 2,
       `metadata` = JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'letter', 'text', 'текст письма целиком')),
         'prompt_user', CONCAT(
           '%if write_hint%ПРОШЛАЯ ПОПЫТКА НЕ ГОДИТСЯ: %write_hint%',
           @nl, 'Перепиши письмо заново, устранив это.', @nl, @nl, '%endif%',
           JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
           @nl, @nl,
           '=== Important information about final response ===', @nl,
           'Верни JSON с единственным ключом:', @nl,
           '- "letter": текст письма целиком', @nl, @nl,
           'Пример: {"letter": "Hi [[companion_name]], ..."}'))
 WHERE `id` = @a;

-- ------------------------------------------- B: есть ли переменные
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Есть переменные?', 1,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'text_regex_extract',
           'inputs_map', JSON_OBJECT('text', 'letter', 'pattern', 'mail_var_pattern'),
           'outputs_map', JSON_OBJECT()))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 1);

SET @b = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 1);

-- ------------------------------------------- C: верный ли язык
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 2, 'Язык верный?', 2,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'letter_lang_ok',
                       'text', '1 — письмо на нужном языке, 0 — на другом')),
         'prompt_user', CONCAT(
           'Определи язык письма и сравни с требуемым.', @nl, @nl,
           '=== Требуемый язык (код) ===', @nl, '%user_language%', @nl, @nl,
           '=== Письмо ===', @nl, '%letter%', @nl, @nl,
           'Ответь 1, если письмо целиком написано на требуемом языке. ',
           'Ответь 0, если оно на другом языке или смешивает языки. ',
           'Имена, названия городов и переменные вида [[имя]] языком не считаются.',
           @nl, @nl,
           '=== Important information about final response ===', @nl,
           'Верни JSON: {"letter_lang_ok": 1}'))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 2);

SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);

-- ------------------------------------------- E: счётчик попыток
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Попытка', 3,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'counter_increment',
           'inputs_map', JSON_OBJECT('value', 'write_try'),
           'outputs_map', JSON_OBJECT()))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 3);

SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);

-- ------------------------------------------- F: что именно не так
--
-- ⚠ Подсказка собирается **условными блоками**, а не двумя ветками: промахи могут
-- сойтись оба разом (нет переменных и язык не тот), и одна ветка сообщила бы
-- только про первый — модель починила бы половину.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 5, 'Что не так', 4,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'variable_conversion', JSON_ARRAY(
           JSON_OBJECT('variable', 'write_try',
                       'text', CONCAT('%counter_increment_', @e, '_result_int%')),
           JSON_OBJECT('variable', 'write_hint', 'text', CONCAT(
             '%if !mail_var_found%в письме нет ни одной переменной [[имя]] — ',
             'имена написаны словами, и такое письмо годится одному адресату. %endif%',
             '%if !letter_lang_ok%письмо написано не на языке %user_language%. %endif%'))))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 4);

SET @f = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);

-- ------------------------------------------- G: отдать письмо
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 4, 'Готово', 5,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'continue_workflow', false,
         'prompt_user', '%letter%')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 5);

SET @g = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5);

-- ------------------------------------------- Переходы
--
-- ⚠ Ставятся **после** вставки: `step_id` — настоящие номера строк, и знать их до
-- вставки неоткуда.

-- B: результат поиска переменных кладётся в `mail_var_found` (через outputs_map
-- имя не задать — движок именует сам), поэтому сперва переносим его в понятное
-- имя, а решение принимаем по нему.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.outputs_map',
                             JSON_OBJECT('str', 'mail_var_found')),
       `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
          JSON_OBJECT('variable', 'mail_var_found', 'operator', 'empty',
                      'value', '', 'step_id', CAST(@e AS CHAR))))
 WHERE `id` = @b;

-- C: язык не тот — на счётчик; язык верный — сразу к выдаче, минуя счётчик.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter_lang_ok', 'operator', '==',
                      'value', '0', 'step_id', CAST(@e AS CHAR)),
          JSON_OBJECT('variable', 'letter_lang_ok', 'operator', '==',
                      'value', '1', 'step_id', CAST(@g AS CHAR))))
 WHERE `id` = @c;

-- F: попыток меньше трёх — переписываем; иначе следующий шаг по порядку (G) отдаёт
-- письмо как есть.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
          JSON_OBJECT('variable', 'write_try', 'operator', '<',
                      'value', '3', 'step_id', CAST(@a AS CHAR))))
 WHERE `id` = @f;

-- ------------------------------------------- Переменные workflow
--
-- ⚠ `mail_var_pattern` — регулярка поиска переменных, и она **переменная, а не
-- литерал в шаге**: тот же вид разбирают DatingAi (`DATING_MAIL_VAR_RE`) и
-- страница. Четвёртая копия в metadata разошлась бы с ними молча.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_var_pattern', 'workflow', '\\[\\[[A-Za-z_][A-Za-z0-9_]*\\]\\]',
       'Как выглядит переменная письма: [[имя]]'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_var_pattern');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'write_try', 'workflow', '0', 'Сколько раз письмо переписывали'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'write_try');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'write_hint', 'workflow', '', 'Что было не так с прошлой попыткой'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'write_hint');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_var_pattern', 'write_try', 'write_hint', 'letter',
                    'letter_lang_ok')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       @a AS письмо, @b AS переменные, @c AS язык, @e AS счётчик, @f AS подсказка, @g AS выдача;
