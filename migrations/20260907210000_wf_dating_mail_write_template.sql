-- `dating_mail_write` пишет ШАБЛОН, а не письмо одному человеку (2026-09-07)
--
-- ЧТО БЫЛО. Агент возвращал текст с конкретикой вместо переменных:
--
--     Hi [[companion_name]], Diana here! I'm a choreographer living in Kyiv…
--
-- Имя, город и профессия вписаны словами. Такой шаблон годится ровно одной
-- анкете — а рассылка берёт его для всех, у кого включены письма.
--
-- ⚠ ПРИЧИНА — В САМОМ ПРОМПТЕ. Он давал `%girl_card%` и `%companion_card%`:
-- «От кого: Имя: Diana, Город: Kyiv…». Модель вела себя ровно так, как её
-- просили — писала письмо **от Дианы Джону**, потому что ей их и показали.
-- Требовать при этом «имена только переменной» значит давать данные и запрещать
-- ими пользоваться; в такой борьбе данные побеждают.
--
-- ЧТО ВМЕСТО. Карточек в промпте больше нет. Шаблон — заготовка **для всех**:
-- кто именно напишет и кому, выяснится при генерации пула, где переменные и
-- подставятся. Нет данных — нечего вписать.
--
-- ⚠ ВТОРАЯ БЕДА, ИЗ ТОГО ЖЕ ОТВЕТА: `What are [[question_to_companion]]?`
-- Переменная встроена в фразу, а её значение — целый вопрос. На выходе вышло бы
-- «What are What kind of hobbies do you enjoy??». Такие переменные обязаны стоять
-- отдельным абзацем, и теперь это проверяется кодом (`text_marks_inline`), а не
-- просьбой.
--
-- Шаги после правки:
--
--   A(0) Письмо              → B
--   B(1) Переменные          нет меток → E; лишние → E
--   C(2) Язык верный?        0 → E
--   H(3) Вопрос отдельно?    встроен → E; чисто → G
--   E(4) Попытка             → F
--   F(5) Что не так          попыток < 3 → A
--   G(6) Готово
--
-- ⚠ У `C` снова убран переход «1 → G»: между ним и выдачей встала новая проверка.
-- Оставь мы его — `H` не выполнялся бы никогда.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);
SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);
SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);
SET @f = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5);
SET @g = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 6);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` = 'text_marks_inline') AS инструмент;

-- ------------------------------------------- A: промпт без карточек
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter', 'text', 'текст письма целиком')),
        'prompt_user', CONVERT(CONCAT(
          '%if write_hint%НЕ ГОДИТСЯ: %write_hint%', @nl,
          'Перепиши, устранив это.', @nl, @nl, '%endif%',
          'Напиши ШАБЛОН первого письма от девушки мужчине на сайте знакомств.',
          @nl, @nl,
          '⚠ Это заготовка для рассылки: одним и тем же текстом напишут разные ',
          'девушки разным мужчинам. Ты не знаешь, кто именно, — и знать не должен.',
          @nl, @nl,
          'Переменные (вставляй как [[имя]]):', @nl, '%mail_vars%', @nl, @nl,
          'Пожелание: %mail_hint%', @nl, @nl,
          'Обязательно:', @nl,
          '- язык письма: %user_language%;', @nl,
          '- НИКАКОЙ конкретики: ни имён, ни городов, ни профессий, ни возраста. ',
          'Всё это подставится переменными. Придумаешь «Diana из Kyiv» — шаблон ',
          'станет годен одной анкете из сорока;', @nl,
          '- переменная, чья подпись говорит про вопрос (question_to_companion), ',
          'ставится ОТДЕЛЬНЫМ абзацем: её значение — целый вопрос, и внутри фразы ',
          'выйдет «What are What do you enjoy??».', @nl, @nl,
          'Ещё:', @nl,
          '- до четырёх абзацев;', @nl,
          '- обращайся к получателю, а не к себе;', @nl,
          '- живо и просто, без признаний в любви;', @nl,
          '- о себе — общими словами, которые подойдут любой: не «я хореограф», ',
          'а «я люблю своё дело».', @nl, @nl,
          'Верни JSON: {"letter": "текст письма"}') USING utf8mb4))
 WHERE `id` = @a;

-- ------------------------------------------- H: вопрос отдельным абзацем
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Вопрос отдельно?', 3,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'text_marks_inline',
           'inputs_map', JSON_OBJECT('text', 'letter', 'names', 'mail_var_live'),
           'outputs_map', JSON_OBJECT('str', 'letter_marks_inline')))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 3);

SET @h = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);

-- ------------------------------------------- Переходы
--
-- C: язык не тот — на счётчик. Дальше по порядку идёт H.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_lang_ok', 'operator', '==',
                    'value', '0', 'step_id', CAST(@e AS CHAR))))
 WHERE `id` = @c;

-- H: есть встроенные — на доработку; чисто — к выдаче.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_marks_inline', 'operator', '!=',
                    'value', '', 'step_id', CAST(@e AS CHAR)),
        JSON_OBJECT('variable', 'letter_marks_inline', 'operator', 'empty',
                    'value', '', 'step_id', CAST(@g AS CHAR))))
 WHERE `id` = @h;

-- ------------------------------------------- Подсказка знает про новый промах
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion', JSON_ARRAY(
        JSON_OBJECT('variable', 'write_try',
                    'text', CONVERT(CONCAT('%counter_increment_', @e, '_result_int%')
                                    USING utf8mb4)),
        JSON_OBJECT('variable', 'write_hint', 'text', CONVERT(CONCAT(
          '%if !letter_vars_qty%в письме нет ни одной переменной [[имя]] — ',
          'имена написаны словами. %endif%',
          '%if !letter_lang_ok%письмо написано не на языке %user_language%. %endif%',
          '%if letter_vars_extra%таких переменных нет в списке: %letter_vars_extra% ',
          '— убери их или замени разрешёнными. %endif%',
          '%if letter_marks_inline%переменные %letter_marks_inline% встроены в ',
          'фразу — поставь каждую отдельным абзацем: их значение это целый вопрос. ',
          '%endif%') USING utf8mb4))))
 WHERE `id` = @f;

-- ------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_var_live', 'workflow', '',
       'Имена переменных, чьё значение — целая фраза: они должны стоять отдельным абзацем'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_var_live');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'letter_marks_inline', 'workflow', '', 'Переменные, встроенные в фразу'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'letter_marks_inline');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_var_live', 'letter_marks_inline')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%girl_card%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS карточки_остались,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS испорчен,
       @h AS шаг_проверки;
