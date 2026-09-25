-- Ленты разговора доезжают до промптов шагом-конверсией (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Шаги «Разговор: чат» и «Разговор: письма» зовут `companion_session_history`,
-- и тот отдаёт **строку**. Движок кладёт её под машинным именем:
--
--     companion_session_history_<номер шага>_result_str
--
-- А промпты ветки чата, письма, инициативы и судьи читают человеческие имена —
-- `%talk_history_chat%` и `%talk_history_mail%`, по семь шагов на каждое.
--
-- Прежде их присылал DatingAi переменными запроса; теперь не присылает — дом у
-- разговора один, и он здесь (`…_wf_talk_companion_session`). Значит, имена надо
-- заполнить у себя.
--
-- ## ⚠ Почему конверсией, а не `outputs_map`
--
-- Я и пробовал `outputs_map` — и ошибся. Он отвечает на вопрос «какое **поле
-- словаря** куда положить», а у строки полей нет: движок такое объявление не
-- читает вовсе, и переменная не появлялась. Объявления сняты соседней миграцией
-- (`…_wf_outputs_map_not_dict_drop`).
--
-- Конверсия работает независимо от типа: она просто подставляет значение метки в
-- текст. Тем же типом шага собраны «Ключи» и «Переменные».
--
-- ## ⚠⚠ Номера шагов вычисляются, а не зашиваются
--
-- Машинное имя несёт **`id` шага**, а он у нас и на проде разный: шаги заводила
-- миграция, и автонумерация в двух базах своя. Зашей я здесь `1736` — локально
-- бы сработало, на проде молча дало бы пустую ленту.
--
-- ⚠ Именно `id`, а не `position`: перестановка шагов машинное имя не меняет, и
-- ломаться от перестановки конверсии нечему.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @conv = (SELECT `id` FROM `agent_workflow_step_type`
              WHERE `name` = 'variable_conversion');
-- ⚠ Свой шаг узнаём по тому, **что он кладёт**: подпись человек переименует, а
-- переменную — нет, иначе шаг перестанет работать.
SET @made = (SELECT COUNT(*) FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_SEARCH(`metadata`, 'one', 'talk_history_chat')
                    IS NOT NULL
                AND JSON_EXTRACT(`metadata`, '$.variable_conversion')
                    IS NOT NULL);

-- Номера шагов чтения — из самой базы, **по устройству шага**.
--
-- ⚠⚠ Не по заголовку: он подпись в редакторе, и человек правит её когда хочет —
-- «Разговор: чат» уже переименовали в «История: чат». Найдись здесь `NULL`, и
-- конверсия молча собрала бы метку без номера
-- (`%companion_session_history__result_str%`), то есть пустую ленту без единой
-- ошибки в журнале.
--
-- Признак функциональный: имя инструмента плюс канал в доводах. Поменять их, не
-- изменив того, что шаг делает, нельзя.
SET @id_chat = (SELECT `id` FROM `agent_workflow_step`
                 WHERE `workflow_id` = @wf
                   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                         '$.tool_invoke.tool_name')) = 'companion_session_history'
                   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                         '$.tool_invoke.inputs_map.kind')) = '_const_chat');
SET @id_mail = (SELECT `id` FROM `agent_workflow_step`
                 WHERE `workflow_id` = @wf
                   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                         '$.tool_invoke.tool_name')) = 'companion_session_history'
                   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                         '$.tool_invoke.inputs_map.kind')) = '_const_mail');

SELECT 'ДО' AS этап, @made AS шаг_уже_есть,
       @id_chat AS шаг_чата, @id_mail AS шаг_писем,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf) AS шагов;

-- ── Место сразу за чтением ──────────────────────────────────────────────────
--
-- ⚠ Конверсия обязана стоять **после обеих** — она читает то, что они положили.
SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step`
             WHERE `id` = @id_mail);

UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= @pos AND @made = 0;

-- ── Сам шаг ─────────────────────────────────────────────────────────────────
--
-- ⚠ Обе ленты одним шагом: они об одном — «что пара уже сказала друг другу», — и
-- разнеси их по двум, правка имён чинилась бы в двух местах. Тот же довод, по
-- которому обе склейки ключей живут в шаге «Ключи».
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @conv, 'Ленты разговора', @pos,
       JSON_OBJECT('variable_conversion', JSON_ARRAY(
                       JSON_OBJECT('variable', 'talk_history_chat',
                                   'text', CONCAT('%companion_session_history_',
                                                  @id_chat, '_result_str%')),
                       JSON_OBJECT('variable', 'talk_history_mail',
                                   'text', CONCAT('%companion_session_history_',
                                                  @id_mail, '_result_str%'))),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- Свой шаг для отчёта — по тому же признаку, что и `@made`.
SET @id_conv = (SELECT `id` FROM `agent_workflow_step`
                 WHERE `workflow_id` = @wf
                   AND JSON_SEARCH(`metadata`, 'one', 'talk_history_chat')
                       IS NOT NULL
                   AND JSON_EXTRACT(`metadata`, '$.variable_conversion')
                       IS NOT NULL);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.variable_conversion[0].text'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `id` = @id_conv) AS чат_берётся_из,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.variable_conversion[1].text'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `id` = @id_conv) AS письма_берутся_из,
       -- ⚠⚠ Главная проверка: конверсия **ниже** обоих чтений. Встань она выше —
       -- переменные окажутся пустыми, и это была бы та же тихая беда, что уже
       -- случилась с `outputs_map`.
       (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @id_conv)
       - (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @id_mail)
         AS отступ_от_чтения,
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step` WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS d) AS позиции_столкнулись;
