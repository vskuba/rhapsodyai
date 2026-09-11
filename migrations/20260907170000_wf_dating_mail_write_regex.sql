-- Переменные письма проверяет регулярка, а не LLM (2026-09-07)
--
-- ЧТО БЫЛО. Шаг «Переменные из списка?» спрашивал у модели, все ли имена
-- разрешены. Из четырёх писем три содержали выдуманные (`city`, `city_name`,
-- `girl_city`), и все четыре проверка пропустила.
--
-- Попытка исправить это формулировкой — просить не вердикт, а перечень лишних —
-- лечила симптом: модель по-прежнему решала задачу, для которой не годится.
--
-- ⚠ ЭТО РАБОТА ДЛЯ КОДА. Найти в тексте `[[имя]]` и сверить со списком —
-- механическая операция с точным ответом. LLM здесь не просто избыточна, она
-- **хуже**: даёт вероятностный ответ там, где есть достоверный, и стоит вызова.
--
-- ЧТО ВМЕСТО. Инструмент `text_regex_unknown(text, pattern, allowed)`: находит все
-- совпадения и возвращает те, которых нет в списке. Заодно отдаёт `found_qty` —
-- сколько меток нашлось всего.
--
-- ⚠ ОТСЮДА ЛИШНИМ СТАНОВИТСЯ ОТДЕЛЬНЫЙ ШАГ «ЕСТЬ ПЕРЕМЕННЫЕ?». Он звал
-- `text_regex_extract`, чтобы узнать, есть ли в письме хоть одна метка; теперь на
-- это отвечает `found_qty` того же вызова. Два прохода по одному тексту ради двух
-- вопросов об одном и том же — работа впустую, и один из них рано или поздно
-- разошёлся бы с другим шаблоном поиска.
--
-- Порядок шагов после правки:
--
--   A(0) Письмо                → B
--   B(1) Переменные            found_qty = 0 → E; лишние есть → E
--   C(2) Язык верный?          0 → E; 1 → G
--   E(4) Попытка               → F
--   F(5) Что не так            попыток < 3 → A
--   G(6) Готово
--
-- Шаг D (позиция 3) удаляется: его работу делает B.
--
-- ⚠ Позиции 3 не остаётся вовсе, и это законно: движок идёт по `ORDER BY position`,
-- а не по номерам подряд. Переупорядочивать остальные ради красоты — значит
-- трогать `step_id` в переходах, которые на них ссылаются.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);
SET @b = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 1);
SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);
SET @d = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);
SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);
SET @f = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5);
SET @g = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 6);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` = 'text_regex_unknown') AS инструмент_есть;

-- ------------------------------------------- B: одна проверка вместо двух
--
-- ⚠ Шаблон ищет **имя в группе**, а не всю метку: сверять со списком надо `city`,
-- а не `[[city]]`. Прежний шаг искал метку целиком — там это годилось, потому что
-- ответ был нужен только «нашлось / нет».
UPDATE `agent_workflow_step`
   SET `title` = 'Переменные',
       `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(
          -- Ни одной метки — имена написаны словами.
          JSON_OBJECT('variable', CONCAT('text_regex_unknown_', @b, '_result_found_qty'),
                      'operator', '==', 'value', '0', 'step_id', CAST(@e AS CHAR)),
          -- Есть лишние — модель выдумала имя.
          JSON_OBJECT('variable', 'letter_vars_extra',
                      'operator', '!=', 'value', '', 'step_id', CAST(@e AS CHAR))),
        'tool_invoke', JSON_OBJECT(
          'tool_name', 'text_regex_unknown',
          'inputs_map', JSON_OBJECT('text', 'letter', 'pattern', 'mail_var_pattern',
                                    'allowed', 'mail_var_names'),
          'outputs_map', JSON_OBJECT('str', 'letter_vars_extra',
                                     'found_qty', 'letter_vars_qty')))
 WHERE `id` = @b;

-- ------------------------------------------- C: снова ведёт к выдаче
--
-- Проверка D исчезает, и путь «язык верный» должен вести прямо на выдачу.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
        JSON_OBJECT('variable', 'letter_lang_ok', 'operator', '==',
                    'value', '0', 'step_id', CAST(@e AS CHAR)),
        JSON_OBJECT('variable', 'letter_lang_ok', 'operator', '==',
                    'value', '1', 'step_id', CAST(@g AS CHAR))))
 WHERE `id` = @c;

-- ------------------------------------------- D больше не нужен
DELETE FROM `agent_workflow_step` WHERE `id` = @d;

-- ------------------------------------------- Подсказка по новым переменным
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
          '— убери их или замени разрешёнными. %endif%') USING utf8mb4))))
 WHERE `id` = @f;

-- ------------------------------------------- Шаблон ищет имя, а не метку
UPDATE `agent_workflow_variable`
   SET `default` = '\\[\\[([A-Za-z_][A-Za-z0-9_]*)\\]\\]'
 WHERE `name` = 'mail_var_pattern';

-- ------------------------------------------- Список разрешённых имён
--
-- ⚠ Отдельно от `mail_vars`: тот — «имя — подпись» построчно, для чтения моделью.
-- Инструменту нужны голые имена через запятую, и подписи он принял бы за часть
-- имени. Заполняет её вызывающая сторона (DatingAi), потому что реестр её.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_var_names', 'workflow', '',
       'Разрешённые имена переменных письма через запятую, без подписей'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_var_names');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_var_names', 'letter_vars_qty')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'letter_vars_qty', 'workflow', '0', 'Сколько переменных нашлось в письме'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'letter_vars_qty');

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT `default` FROM `agent_workflow_variable` WHERE `name` = 'mail_var_pattern') AS шаблон,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after'))
          FROM `agent_workflow_step` WHERE `id` = @b) AS переходов_у_проверки;
