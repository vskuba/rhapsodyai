-- Длину истории задают сами шаги чтения (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- «Сколько разговора видит агент» настраивалось у DatingAi, двумя настройками
-- сайта: `chat_history_max` (20) и `reply_history` (10). Читал их один модуль —
-- `talk_history.py`, — и он собирал ленту сам, из пяти таблиц панели.
--
-- Ленту теперь собирает сосед, а модуль удалён. Настройки при этом остались
-- стоять на странице «Настройки сайтов»: человек их крутил, а не менялось
-- **ничего** — предел решала константа инструмента. Тихо и без следа в журнале.
--
-- Поэтому предел переезжает туда, где живёт история: в сами шаги чтения. Видно
-- в редакторе, правится там же, где промпты.
--
-- ## Сколько и почему
--
--     чат     20 обменов   реплики по десять слов; двадцать — уже разговор
--     письма  10 обменов   письмо это три абзаца, и десять их — целая переписка
--
-- ⚠ Числа те же, что стояли умолчаниями настроек: перенос не меняет поведения, а
-- только переносит место, где значение задано.
--
-- ⚠⚠ Предел стоит **у каждого канала свой**, и уравнивать их нельзя: общий
-- вытолкнул бы письма чатом. Чат идёт десятками коротких реплик, письма —
-- единицами длинных, и «последние двадцать» на общей ленте оставили бы от почты
-- ничего.
--
-- ## ⚠ Почему `_const_`, а не переменная вызова
--
-- Переменную пришлось бы объявлять входящей и слать из панели — то есть вернуть
-- ровно ту связку, которую мы разбираем: настройка у нас, чтение у соседа, и
-- между ними договор, который рвётся молча. Здесь предел — часть устройства
-- workflow, и лежит он в workflow.
--
-- ⚠ Понадобится крутить его человеку — это будет настройка **узла** или самого
-- workflow у соседа, а не сайта у нас: ленту читает он.
--
-- ## ⚠⚠ Шаги ищутся по устройству, а не по заголовку
--
-- Заголовок — подпись в редакторе, и человек правит её когда хочет: пока эта
-- миграция писалась, «Разговор: чат» уже переименовали в «История: чат». Опора на
-- заголовок дала бы худший исход — `UPDATE` проходит «удачно», не задев ни одной
-- строки, и предел молча остаётся прежним.
--
-- Признак берём функциональный: имя инструмента плюс канал в доводах. Оба нельзя
-- поменять, не изменив того, что шаг делает.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
               = 'companion_session_history'
           AND JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.limit')
               IS NOT NULL) AS шагов_с_пределом;

-- ── Предел в шаг чтения ─────────────────────────────────────────────────────
--
-- ⚠ `JSON_SET` по пути, а не замена по тексту: ключ ложится внутрь JSON, и
-- лесенка экранирования в SQL-литерале здесь уже дважды не сошлась — замена
-- проходила «удачно», не изменив ничего (`…_wf_talk_companion_key`).
--
-- ⚠ `_const_` — приставка литерала: без неё движок счёл бы «20» именем
-- переменной, не нашёл её и отдал инструменту пустоту.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.limit', '_const_20')
 WHERE `workflow_id` = @wf
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
       = 'companion_session_history'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.kind'))
       = '_const_chat';

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.limit', '_const_10')
 WHERE `workflow_id` = @wf
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
       = 'companion_session_history'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.kind'))
       = '_const_mail';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.limit'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.kind')) = '_const_chat') AS предел_чата,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.limit'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.kind')) = '_const_mail') AS предел_писем,
       -- ⚠ Остальные доводы обязаны уцелеть: ключи пары и канал. Пропади канал —
       -- оба шага прочитают чат, и переписка писем исчезнет из промпта.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
               = 'companion_session_history'
           AND JSON_LENGTH(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map')) = 4) AS доводов_по_четыре,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND NOT JSON_VALID(`metadata`)) AS битых_метаданных;
