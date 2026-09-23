-- Судья письма: просим JSON и показываем переписку (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: первое же личное письмо упало на судье
--
-- Живой прогон через семь минут после выкладки
-- (`20260923180000_wf_favorite_mail_via_talk`):
--
--     ❌ Не удалось распарсить JSON от LLM на шаге 'Валидация ответа':
--        string indices must be integers, not 'str'
--     Сырой ответ LLM:
--        girl_response_skip: 0
--        girl_response_fixed: I was thinking about our last chat…
--
-- Модель ответила **строками «ключ: значение»**, а движок ждал JSON.
--
-- ⚠ Само письмо при этом вышло именно таким, какого добивались: три абзаца, и в
-- каждом то, что человек вправду рассказывал — сон вместо хобби, возраст, работа
-- водителем, нелюбовь к рэпу. Потерялось оно уже на проверке.
--
-- ## Причина — моя вставка, и она поучительна
--
-- У шага 13 блок с требованием JSON стоял **после** обеих прежних веток, общим
-- хвостом. Моя ветка письма обернула их целиком:
--
--     %if mail_mode%[ветка письма]
--     %else%[прежние две ветки]
--     === Important information about final response ===  ← общий хвост
--     %endif%
--
-- То есть при `mail_mode` хвост попадал в **отброшенную** половину: модель просто
-- не просили отвечать JSON-ом.
--
-- ⚠⚠ В шаге 12 та же вставка сделана верно — блок JSON я вписала **внутрь**
-- ветки. В шаге 13 забыла, и это видно только на живом прогоне: баланс `%if%`
-- сходится, движок разворачивает ветку правильно, а просьбы про JSON в ней нет.
--
-- ## Второе: судья не видел переписки
--
-- В его списке стоит «он опирается на переписку выше» — а переписки в промпте
-- нет вовсе. История берётся из `session_messages`, которую DatingAi не
-- заполняет: разговор он кладёт в `talk_history` (`answer.py`, оговорка про
-- сессии у соседа). Требование было невыполнимым: судья проверял то, чего не
-- видел.
--
-- Идемпотентность: правится только ветка без блока JSON.

SET @talk = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%исправленное письмо или пустая строка%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS json_у_письма,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%talk_history%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS переписка_у_судьи;

-- ── 1. Просим JSON внутри ветки письма ──────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         'girl_response_fixed своё письмо, от абзаца до трёх, на языке %user_language%.\n',
         CONCAT(
           'girl_response_fixed своё письмо, от абзаца до трёх, на языке ',
           '%user_language%.\n\n',
           '=== Important information about final response ===\n',
           'Please return your response in JSON format. The JSON response must contain follow keys: \n',
           '- "girl_response_skip": всегда 0\n',
           '- "girl_response_fixed": исправленное письмо или пустая строка, если черновик годится\n\n',
           'Example of JSON response:\n',
           '{\n',
           '  "girl_response_skip": 0,\n',
           '  "girl_response_fixed": ""\n',
           '}\n')))
 WHERE `workflow_id` = @talk AND `position` = 13
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%исправленное письмо или пустая строка%';

-- ── 2. Показываем судье переписку ───────────────────────────────────────────
--
-- ⚠ Из `talk_history`, а не `session_messages`: сессию у соседа DatingAi не
-- держит, разговор приходит переменной. Тем же способом, что у шага сочинения.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         '%endif%=== %companion_title% пишет ===',
         CONCAT(
           '%endif%%if talk_history%=== Разговор с этим человеком ',
           '(время в квадратных скобках; «она» — она) ===\n',
           '%talk_history%\n\n',
           '%endif%=== %companion_title% пишет ===')))
 WHERE `workflow_id` = @talk AND `position` = 13
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%talk_history%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%исправленное письмо или пустая строка%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS json_у_письма,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%talk_history%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS переписка_у_судьи,
       -- ⚠ Баланс скобок: вставка добавила один `%if%` и один `%endif%`.
       (SELECT (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
                - CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                                      '%if ', ''))) / 4
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS сколько_if,
       (SELECT (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
                - CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                                      '%endif%', ''))) / 7
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS сколько_endif;
