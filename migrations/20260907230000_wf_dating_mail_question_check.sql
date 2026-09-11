-- `dating_mail_question` проверяет, что ответ — вопрос (2026-09-07)
--
-- ЧТО БЫЛО. Круг рассылки набрал сотню писем, и в одном вместо вопроса стояло
-- рассуждение модели о том, какой вопрос задать:
--
--     Given the description of the letter, I need to ask Matthias a question
--     about his interests or activities. Since we don't know much about his
--     profile, I should ask a general but engaging question.
--
-- Это ушло бы живому человеку внутри письма от девушки. Один случай на сто —
-- заметная доля, когда адресаты живые.
--
-- ⚠ ПРИЧИНУ ВИДНО В ТЕКСТЕ ОТВЕТА: модель пересказала правило 4 промпта («О
-- получателе ничего не известно — задай общий вопрос»). Правило стояло
-- утверждением, всегда, даже когда карточка получателя была полной, — и
-- противоречило правилу 2 («спрашивай про то, что есть в его профиле»). Из двух
-- взаимоисключающих правил модель сделала то, что делает человек в такой
-- ситуации: начала рассуждать вслух.
--
-- ЧТО ВМЕСТО. Два изменения:
--
--   1. Правило про незнакомого получателя стало **условным** (`%if%`): оно
--      появляется, только когда карточки действительно нет. Противоречие ушло.
--   2. Workflow из одного шага стал самопроверяющимся: ответ, не оканчивающийся
--      знаком вопроса, уходит на доработку. Признак формальный, и проверяет его
--      регулярка (`text_regex_extract`), а не вопрос к LLM.
--
-- ⚠ Знак ищем В КОНЦЕ. Рассуждение о вопросе тоже содержит «?» в середине
-- («should I ask about hobbies? Let me…»), а вопросом от этого не становится.
--
-- Шаги после правки:
--
--   A(0) Вопрос            → B
--   B(1) Это вопрос?       нет знака → C; есть → E
--   C(2) Попытка           → D
--   D(3) Что не так        попыток < 3 → A
--   E(4) Готово
--
-- ⚠ Исчерпав попытки, workflow отдаёт что вышло — и это не дыра: разбор на нашей
-- стороне (`_question` в `dating_mail_agent.py`) отбросит ответ без знака вопроса,
-- переменная останется пустой, и письмо не уйдёт вовсе. Две линии подряд, потому
-- что цена промаха — письмо живому человеку.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_question');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` = 'text_regex_extract') AS инструмент;

-- ------------------------------------------- A: промпт без противоречия
--
-- ⚠ Тип шага меняем с `return_response_llm` (1) на `llm_to_json` (2): ответ теперь
-- не выдаётся сразу, а ложится в переменную — её и проверяет следующий шаг.
UPDATE `agent_workflow_step`
   SET `type_id` = 2,
       `title` = 'Вопрос',
       `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'question', 'text', 'сам вопрос, без пояснений')),
        'prompt_user', CONVERT(CONCAT(
          '%if ask_hint%НЕ ГОДИТСЯ: %ask_hint%', @nl,
          'Ответь заново — только вопросом.', @nl, @nl, '%endif%',
          'Ты придумываешь ОДИН вопрос для письма на сайте знакомств. Письмо ',
          'пишет девушка мужчине, они не знакомы.', @nl, @nl,
          '=== Что известно о получателе ===', @nl, '%companion_card%', @nl, @nl,
          '=== Кто пишет ===', @nl, '%girl_card%', @nl, @nl,
          'Правила:', @nl,
          '1. Ровно один вопрос, одно-два предложения. Он встанет внутрь готового ',
          'абзаца письма, а два вопроса подряд превращают письмо в анкету.', @nl,
          '2. Спрашивай про то, что есть в его профиле. Вопрос «чем вы ',
          'увлекаетесь?» он читал сотню раз и не ответит; вопрос про его дело ',
          'показывает, что профиль прочли. Если про него ничего не известно — ',
          'задай общий, но живой вопрос про его занятия.', @nl,
          '3. Не обращайся по имени: оно уже стоит в письме отдельно, и второе ',
          'обращение внутри абзаца читается как сбой подстановки.', @nl,
          '4. ЯЗЫК ВОПРОСА — %user_language% (код языка). Пиши только на нём, ',
          'даже если профиль получателя и эти правила написаны на другом.', @nl,
          '5. Ответ — САМ ВОПРОС и ничего больше. Не описывай, какой вопрос ты ',
          'собираешься задать, и не объясняй выбор: всё, что ты напишешь, встанет ',
          'в письмо как есть. Ответ обязан заканчиваться знаком вопроса.', @nl, @nl,
          'Верни JSON: {"question": "текст вопроса"}') USING utf8mb4))
 WHERE `id` = @a;

-- ------------------------------------------- B: это вообще вопрос?
--
-- ⚠ `outputs_map` ЗДЕСЬ НЕ РАБОТАЕТ, и это не оплошность движка, а его устройство:
-- алиасы он расставляет только для инструментов, вернувших словарь
-- (`ai_framework_manager.py`). `text_regex_extract` отдаёт строку, и её движок
-- кладёт в автоимя `<инструмент>_<шаг>_result_str` — без алиаса.
--
-- Поэтому переход ниже ссылается на автоимя напрямую. Тем же приёмом уже написан
-- счётчик попыток в `dating_mail_write` (`%counter_increment_1312_result_int%`).
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Это вопрос?', 1,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'text_regex_extract',
           'inputs_map', JSON_OBJECT('text', 'question', 'pattern', 'ask_pattern'),
           'outputs_map', JSON_OBJECT()))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 1);

-- ------------------------------------------- C: счётчик попыток
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Попытка', 2,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'counter_increment',
           'inputs_map', JSON_OBJECT('value', 'ask_try'),
           'outputs_map', JSON_OBJECT()))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 2);

-- ------------------------------------------- D: что именно не так
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 5, 'Что не так', 3,
       JSON_OBJECT('transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY(),
                   'variable_conversion', JSON_ARRAY())
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 3);

-- ------------------------------------------- E: выдача
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 4, 'Готово', 4,
       JSON_OBJECT('transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY(),
                   'continue_workflow', false,
                   'prompt_user', '%question%')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 4);

SET @b = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 1);
SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);
SET @d = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);
SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);

-- ------------------------------------------- Переходы
--
-- B: знака нет — на доработку; есть — к выдаче.
SET @mark = CONVERT(CONCAT('text_regex_extract_', @b, '_result_str') USING utf8mb4);

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', @mark, 'operator', 'empty',
                    'value', '', 'step_id', CAST(@c AS CHAR)),
        JSON_OBJECT('variable', @mark, 'operator', '!=',
                    'value', '', 'step_id', CAST(@e AS CHAR))))
 WHERE `id` = @b;

-- D: попытки не исчерпаны — заново; исчерпаны — идём по порядку, к выдаче.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
        `metadata`,
        '$.transitions_after', JSON_ARRAY(
          JSON_OBJECT('variable', 'ask_try', 'operator', '<',
                      'value', '3', 'step_id', CAST(@a AS CHAR))),
        '$.variable_conversion', JSON_ARRAY(
          JSON_OBJECT('variable', 'ask_try',
                      'text', CONVERT(CONCAT('%counter_increment_', @c, '_result_int%')
                                      USING utf8mb4)),
          JSON_OBJECT('variable', 'ask_hint', 'text', CONVERT(CONCAT(
            'ответ не оканчивается знаком вопроса — похоже, ты описал вопрос ',
            'словами вместо того, чтобы его задать. Верни только сам вопрос.')
            USING utf8mb4))))
 WHERE `id` = @d;

-- ------------------------------------------- Переменные
--
-- ⚠ Регулярку держим переменной, а не строкой в шаге: `inputs_map` подставляет
-- значения переменных, и литерал в нём уехал бы как имя несуществующей.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'ask_pattern', 'workflow', '\\?\\s*$',
       'Чем кончается настоящий вопрос: знак в конце текста'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'ask_pattern');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'question', 'workflow', '', 'Вопрос получателю, как его написала модель'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'question');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'ask_try', 'workflow', '0', 'Какая это попытка написать вопрос'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'ask_try');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'ask_hint', 'workflow', '', 'Что не так с прошлым ответом'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'ask_hint');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('ask_pattern', 'question', 'ask_try', 'ask_hint')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%ничего не известно — задай%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS противоречие_осталось,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS испорчен,
       @mark AS переменная_проверки;
