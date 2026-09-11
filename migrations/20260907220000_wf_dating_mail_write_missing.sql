-- `dating_mail_write` проверяет, что все обязательные метки на месте (2026-09-07)
--
-- ЧТО БЫЛО. Агент вернул шаблон с одной меткой из трёх:
--
--     Hi [[companion_name]],
--     …
--     I'm curious, though — what do you enjoy most when you have some free time?
--
-- Имени девушки нет вовсе, а вопрос получателю написан словами. Письмо, ради
-- которого и заведена `question_to_companion`, вышло бы у всех одинаковым — то
-- есть ровно тем, чего рассылка избегает.
--
-- ⚠ ПОЧЕМУ ПРОШЛО. Проверок было три, и ни одна такого не ловит:
--
--   `text_regex_unknown` — есть ли САМОВОЛЬНЫЕ метки. Лишних не было;
--   язык                 — английский, верно;
--   `text_marks_inline`  — стоит ли живая метка отдельно. Её не было вовсе,
--                          а чего нет, то и не встроено.
--
-- «Нет лишнего» и «есть всё нужное» — разные вопросы, и первый на второй не
-- отвечает. Текст с единственной верной меткой безупречен по всем трём и всё же
-- никуда не годится.
--
-- ЧТО ВМЕСТО. Шаг M с `text_marks_missing`: список обязательных имён приходит
-- переменной `mail_var_must`, инструмент возвращает те, которых в тексте нет.
-- Есть недостающие — на доработку, с их перечислением в подсказке.
--
-- ⚠ Список шлёт DatingAi, а не workflow собирает сам. Обязательность — вопрос
-- предметный: сегодня обязательны все три переменные реестра, завтра появится
-- четвёртая, уместная не в каждом письме. Решать это должна сторона, которая
-- знает про письма, а не шаг проверки.
--
-- Шаги после правки:
--
--   A(0) Письмо              → B
--   B(1) Переменные          нет меток → E; лишние → E
--   C(2) Язык верный?        0 → E
--   H(3) Вопрос отдельно?    встроен → E; чисто → M
--   E(4) Попытка             → F
--   F(5) Что не так          попыток < 3 → A
--   G(6) Готово
--   M(7) Все ли метки?       нет каких-то → E; все → G
--
-- ⚠ M стоит последним по номеру, а исполняется предпоследним — переходы у него
-- явные в обе стороны, и порядок позиций тут ничего не решает. Вставлять его
-- между H и E значило бы сдвинуть номера четырёх шагов, а на них ссылаются
-- переходы: одна пропущенная ссылка — и workflow уходит в шаг, которого не ждали.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);
SET @f = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5);
SET @g = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 6);
SET @h = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` = 'text_marks_missing') AS инструмент;

-- ------------------------------------------- M: чего в тексте нет
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Все ли метки?', 7,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'text_marks_missing',
           'inputs_map', JSON_OBJECT('text', 'letter', 'names', 'mail_var_must'),
           'outputs_map', JSON_OBJECT('str', 'letter_marks_missing')))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 7);

SET @m = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 7);

-- ------------------------------------------- Переходы
--
-- H: вопрос стоит отдельно — теперь не сразу к выдаче, а на проверку полноты.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_marks_inline', 'operator', '!=',
                    'value', '', 'step_id', CAST(@e AS CHAR)),
        JSON_OBJECT('variable', 'letter_marks_inline', 'operator', 'empty',
                    'value', '', 'step_id', CAST(@m AS CHAR))))
 WHERE `id` = @h;

-- M: чего-то не хватает — на доработку; всё на месте — к выдаче.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_marks_missing', 'operator', '!=',
                    'value', '', 'step_id', CAST(@e AS CHAR)),
        JSON_OBJECT('variable', 'letter_marks_missing', 'operator', 'empty',
                    'value', '', 'step_id', CAST(@g AS CHAR))))
 WHERE `id` = @m;

-- ------------------------------------------- Подсказка называет пропущенные
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
          '%endif%',
          '%if letter_marks_missing%в письме нет переменных: ',
          '%letter_marks_missing% — их надо вставить как [[имя]], а не писать ',
          'словами. Вопрос получателю не сочиняй сам: на его месте ставится ',
          'переменная. %endif%') USING utf8mb4))))
 WHERE `id` = @f;

-- ------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_var_must', 'workflow', '',
       'Имена переменных, которые обязаны быть в шаблоне: список шлёт DatingAi'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_var_must');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'letter_marks_missing', 'workflow', '', 'Обязательные переменные, которых в письме нет'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'letter_marks_missing');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_var_must', 'letter_marks_missing')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       @m AS шаг_полноты,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after')) LIKE CONCAT('%', @m, '%')
          FROM `agent_workflow_step` WHERE `id` = @h) AS h_ведёт_к_m;
