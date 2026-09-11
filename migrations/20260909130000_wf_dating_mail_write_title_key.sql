-- Починка: ключ названия в ответе LLM — `letter_title`, а не `title` (2026-09-09)
--
-- ЧТО СЛОМАЛОСЬ. Предыдущая миграция (`..._wf_dating_mail_write_title.sql`) просила
-- модель вернуть `{"letter": …, "title": …}`, а в `llm_to_json_variable` объявила
-- переменную `letter_title`. Имя переменной и ключ JSON у этого шага — **одно и то
-- же**: движок ищет в ответе ключ с именем переменной. Ключа `letter_title` в ответе
-- не было никогда, и шаг падал на каждом прогоне:
--
--     В ответе LLM отсутствуют обязательные ключи воркфлоу: ['letter_title']
--
-- То есть сломалось всё, что зовёт `dating_mail_write`: и кнопка черновика на
-- странице «Письма», и круг, пишущий заготовки по расписанию.
--
-- ⚠ ПОЧЕМУ НЕ ПЕРЕИМЕНОВАТЬ ПЕРЕМЕННУЮ В `title`. Она уезжает в шаг «Готово» как
-- `%letter_title%`, и там же рядом стоит `%letter%`. Пара `letter` / `letter_title`
-- читается как одно целое; `title` в одиночку — это «название чего?», и следующий
-- читатель полезет искать ответ. Дешевле поправить промпт.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SELECT 'ДО' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Письмо') LIKE '%"letter_title"%'
       AS ключ_верный;

-- Меняем только последнюю строку промпта — ту, где назван формат ответа.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
           `metadata`, '$.prompt_user',
           REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                   'Верни JSON: {"letter": "текст письма", "title": "название"}',
                   'Верни JSON: {"letter": "текст письма", "letter_title": "название"}'))
 WHERE `workflow_id` = @wf AND `title` = 'Письмо';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Письмо') LIKE '%"letter_title"%'
       AS ключ_верный;
