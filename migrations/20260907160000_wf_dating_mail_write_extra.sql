-- Проверка переменных требует доказательства, а не вердикта (2026-09-07)
--
-- ЧТО БЫЛО. Шаг «Переменные из списка?» спрашивал `letter_vars_ok`: 1 или 0. Из
-- четырёх прогонов три содержали выдуманные имена (`city`, `city_name`,
-- `girl_city`) — и все четыре получили от проверки единицу. То есть проверка
-- работала, но всегда отвечала «годится».
--
-- ⚠ ОТЧЕГО. Вопрос «все ли переменные из списка?» требует сверить два списка и
-- ответить одним битом. Мелкая модель на такой вопрос отвечает утвердительно
-- почти всегда: сверку она не делает, а «да» — вероятный ответ на вопрос,
-- начинающийся с «все ли».
--
-- ЧТО ВМЕСТО. Просим не вердикт, а **список лишних имён**. Разница
-- принципиальная: чтобы ответить «city», модель обязана пройти по переменным
-- письма и сверить каждую — то есть проделать работу, а не угадать её итог.
-- Пустой ответ тогда означает «сверил, лишних нет», а не «не глядя согласился».
--
-- Переход строится на `empty`: пусто — к выдаче, что-то есть — на доработку. И
-- само перечисление уходит в подсказку: модель узнаёт, какие именно имена
-- выдумала, а не общее «есть лишние».
--
-- ⚠ ТОТ ЖЕ ПРИЁМ ГОДИТСЯ НЕ ВЕЗДЕ. Проверка языка осталась битом (`0`/`1`):
-- «на каком языке письмо» — вопрос с коротким ответом, и предъявлять там нечего.
-- Списочная проверка нужна там, где вердикт подменяет работу.

-- ---------------------------------------------------------------- До
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @d = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 3);
SET @e = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 4);
SET @f = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5);
SET @g = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 6);

SELECT 'ДО' AS этап, @d AS шаг_проверки,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.llm_to_json_variable[0].variable'))
          FROM `agent_workflow_step` WHERE `id` = @d) AS спрашивала;

-- ------------------------------------------- D: перечисли лишние
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter_vars_extra', 'operator', 'empty',
                      'value', '', 'step_id', CAST(@g AS CHAR))),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter_vars_extra',
                      'text', 'имена переменных письма, которых нет в списке; пусто, если все на месте')),
        'prompt_user', CONVERT(CONCAT(
          'Разрешённые переменные:', @nl, '%mail_vars%', @nl, @nl,
          'Письмо:', @nl, '%letter%', @nl, @nl,
          'Выпиши каждую [[переменную]] из письма и сверь со списком разрешённых.',
          @nl,
          'Перечисли через запятую те имена, которых в списке нет. ',
          'Если все на месте — верни пустую строку.', @nl, @nl,
          'Верни JSON: {"letter_vars_extra": "city, age"} или {"letter_vars_extra": ""}')
          USING utf8mb4))
 WHERE `id` = @d;

-- ------------------------------------------- Подсказка называет имена
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion', JSON_ARRAY(
        JSON_OBJECT('variable', 'write_try',
                    'text', CONVERT(CONCAT('%counter_increment_', @e, '_result_int%')
                                    USING utf8mb4)),
        JSON_OBJECT('variable', 'write_hint', 'text', CONVERT(CONCAT(
          '%if !mail_var_found%в письме нет ни одной переменной [[имя]] — ',
          'имена написаны словами. %endif%',
          '%if !letter_lang_ok%письмо написано не на языке %user_language%. %endif%',
          '%if letter_vars_extra%таких переменных нет в списке: %letter_vars_extra% ',
          '— убери их или замени разрешёнными. %endif%') USING utf8mb4))))
 WHERE `id` = @f;

-- ------------------------------------------- Переменная
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'letter_vars_extra', 'workflow', '', 'Переменные письма, которых нет в реестре'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'letter_vars_extra');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'letter_vars_extra'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.llm_to_json_variable[0].variable'))
          FROM `agent_workflow_step` WHERE `id` = @d) AS спрашивает,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after'))
          FROM `agent_workflow_step` WHERE `id` = @d) AS переходов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @d) AS испорчен;
