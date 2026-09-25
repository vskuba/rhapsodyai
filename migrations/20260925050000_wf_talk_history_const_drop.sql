-- Литералы `_const_` уходят из `dating_talk`: значения задают шаги (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ: непрозрачное значение хуже неверного
--
-- Движок понимает приставку `_const_` в `inputs_map`: значение берётся текстом
-- после неё (`ai_framework_manager.py`, `var_name[len('_const_'):]`). Работает — и
-- при этом такого значения **нет ни в одном списке переменных**: ни во входящих,
-- ни в создаваемых шагами. Поменять его нельзя ничем, кроме правки JSON шага, а на
-- вопрос «откуда здесь 10?» ответа не найти нигде.
--
-- Правило записано (`workflow.md`, §3.0): у значения два законных происхождения —
-- входящая переменная либо результат шага. Эта миграция убирает **весь** долг,
-- который я завёл в `dating_talk`: семь литералов в пяти шагах.
--
--     поз. 3  История: чат               kind, limit
--     поз. 4  История: письма            kind, limit
--     поз. 6  Жребий                     spec (2494 знака JSON)
--     поз.26  Разговор: записать ответ    kind, answer
--     поз.28  Разговор: записать тишину   kind
--
-- ## ⚠⚠ Значения КОПИРУЮТСЯ из шагов, а не набираются заново
--
-- Спецификация жребия — 2494 знака JSON с метками вроде
-- `%dice_mail_name_percent%`. Набери её в миграции руками — и одна опечатка
-- меняет поведение жребия молча. Поэтому каждое значение читается из шага,
-- у него снимается приставка, и ровно оно кладётся в переменную.
--
-- ## ⚠⚠ Где определяются
--
-- Шесть из семи читают только **входящее** (`mail_mode`, `dice_mail_*_percent`),
-- поэтому их задаёт шаг «Ключи» — он нулевой и выполняется раньше всех при любом
-- маршруте.
--
-- Седьмое — `girl_response_final` — читает `girl_response_fixed`, а его кладёт
-- судья (поз. 24). Значит нулевым шагом его не задать, и для него заводится свой
-- шаг сразу после проверки повтора.
--
-- ⚠ Это же выражение стоит **втроём**: в шагах 26, 27 и 30. Здесь заменяется только
-- шаг 26 — у 27 и 30 оно живёт в `prompt_user`, то есть на виду и в списке
-- переменных шага; а главное, шаг 30 — другая ветка, через новый шаг она не идёт, и
-- переменной там просто не будет.
--
-- ## ⚠ Порядок и прыжки
--
-- Новый шаг сдвигает позиции 26+ на единицу. Переходы прыгают по **`step_id`**, а не
-- по соседству, поэтому сдвиг их не задевает: `girl_response_skip = 1` и повтор
-- по-прежнему уводят на «Тишину» тем же номером шага.
--
-- ## ⚠ Строка вместо числа безопасна
--
-- `variable_conversion` кладёт текст, а инструмент ждёт `limit: int`. Приведение
-- делает движок по сигнатуре (`ai_tool.py`: `expected_type(variable_value)` →
-- `int('20')`).

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @tool = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'tool_invoke');
SET @conv = (SELECT `id` FROM `agent_workflow_step_type`
              WHERE `name` = 'variable_conversion');

-- ⚠ Шаги ищем по устройству, а не по названию: названия правят руками.
SET @keys = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.variable_conversion[1].variable')) = 'girl_unique_id'
              LIMIT 1);
SET @chat = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'companion_session_history'
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.inputs_map.kind')) LIKE '%chat' LIMIT 1);
SET @mail = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'companion_session_history'
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.inputs_map.kind')) LIKE '%mail' LIMIT 1);
SET @dice = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'dice' LIMIT 1);
-- Запись ответа: у неё есть довод `answer`; у записи тишины его нет.
SET @said = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'companion_session_add'
                AND JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.inputs_map.answer') IS NOT NULL LIMIT 1);
SET @quiet = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf
                 AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                       '$.tool_invoke.tool_name')) = 'companion_session_add'
                 AND JSON_EXTRACT(`metadata`,
                       '$.tool_invoke.inputs_map.answer') IS NULL LIMIT 1);

-- ── Значения снимаются с шагов как есть ─────────────────────────────────────
--
-- ⚠ `SUBSTRING(…, 8)` — ровно длина `_const_` плюс один. Значение уже без
-- приставки (повторный прогон) — под условие ниже оно не попадёт.
SET @spec = (SELECT SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.inputs_map.spec')), 8)
               FROM `agent_workflow_step` WHERE `id` = @dice);
SET @kind = (SELECT SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.inputs_map.kind')), 8)
               FROM `agent_workflow_step` WHERE `id` = @said);
SET @answer = (SELECT SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                        '$.tool_invoke.inputs_map.answer')), 8)
                 FROM `agent_workflow_step` WHERE `id` = @said);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `metadata` LIKE '%_const_%') AS шагов_с_литералами,
       LENGTH(COALESCE(@spec, '')) AS длина_жребия,
       COALESCE(@kind, '—') AS канал,
       LENGTH(COALESCE(@answer, '')) AS длина_ответа;

-- ── 1. Переменные в реестре ─────────────────────────────────────────────────
--
-- ⚠ Тип `workflow`, не `input`: снаружи их не присылают, и требовать с панели
-- значило бы отвечать `400` на каждый чат.
--
-- ⚠ Умолчание пустое намеренно: значение задаёт шаг, и второе место для него
-- разошлось бы с первым на первой же правке.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT one.`name`, 'workflow', '', one.`note` FROM (
        SELECT 'talk_history_chat_kind' AS `name`,
               'Канал ленты чата. Кладёт шаг «Ключи»' AS `note`
  UNION SELECT 'talk_history_chat_limit',
               'Сколько последних обменов чата брать. Кладёт шаг «Ключи»'
  UNION SELECT 'talk_history_mail_kind',
               'Канал ленты писем. Кладёт шаг «Ключи»'
  UNION SELECT 'talk_history_mail_limit',
               'Сколько последних обменов письмами брать. Кладёт шаг «Ключи»'
  UNION SELECT 'talk_session_kind',
               'Канал записи разговора: письма или чат. Кладёт шаг «Ключи»'
  UNION SELECT 'dice_spec',
               'Спецификация жребия: оси, варианты и веса. Кладёт шаг «Ключи»'
  UNION SELECT 'girl_response_final',
               'Ответ девушки после судьи: правленый, иначе исходный. '
               'Кладёт шаг «Ответ: итоговый»'
) AS one
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) x
                    WHERE x.`name` = one.`name`);

-- ── 2. Объявление у workflow: без него переменной нет в списке редактора ─────
--
-- ⚠ Наименьший номер на имя: в этой базе имена переменных не уникальны (288 строк
-- при 271 имени), и соединение по имени дало бы по два объявления на одну.
INSERT INTO `agent_workflow_variable_workflow` (`workflow_id`, `variable_id`)
SELECT @wf, (SELECT MIN(v.`id`) FROM `agent_workflow_variable` v
              WHERE v.`name` = one.`name`)
  FROM (        SELECT 'talk_history_chat_kind' AS `name`
          UNION SELECT 'talk_history_chat_limit'
          UNION SELECT 'talk_history_mail_kind'
          UNION SELECT 'talk_history_mail_limit'
          UNION SELECT 'talk_session_kind'
          UNION SELECT 'dice_spec'
          UNION SELECT 'girl_response_final') AS one
 WHERE @wf IS NOT NULL
   AND NOT EXISTS (
         SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
          WHERE x.`workflow_id` = @wf
            AND x.`variable_id` = (SELECT MIN(v2.`id`)
                                     FROM `agent_workflow_variable` v2
                                    WHERE v2.`name` = one.`name`));

-- ── 3. Шесть значений задаёт шаг «Ключи» ────────────────────────────────────
--
-- ⚠ Одним `JSON_ARRAY_APPEND`: шесть отдельных `UPDATE` читали и писали бы тот же
-- массив по разу каждый, и порядок записей зависел бы от порядка запросов.
--
-- ⚠⚠ Защита от повтора — отсутствие первой добавляемой. Без неё второй прогон
-- положил бы по две записи на переменную: вреда нет (вторая перезапишет первую тем
-- же значением), но шаг станет нечитаемым.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_ARRAY_APPEND(`metadata`,
         '$.variable_conversion',
         JSON_OBJECT('text', 'chat', 'variable', 'talk_history_chat_kind'),
         '$.variable_conversion',
         JSON_OBJECT('text', '20', 'variable', 'talk_history_chat_limit'),
         '$.variable_conversion',
         JSON_OBJECT('text', 'mail', 'variable', 'talk_history_mail_kind'),
         '$.variable_conversion',
         JSON_OBJECT('text', '10', 'variable', 'talk_history_mail_limit'),
         '$.variable_conversion',
         JSON_OBJECT('text', COALESCE(@kind, '%if mail_mode%mail%else%chat%endif%'),
                     'variable', 'talk_session_kind'),
         '$.variable_conversion',
         JSON_OBJECT('text', @spec, 'variable', 'dice_spec'))
 WHERE `id` = @keys
   AND @keys IS NOT NULL
   AND @spec IS NOT NULL
   AND `metadata` NOT LIKE '%talk\_history\_chat\_kind%';

-- ── 4. Шаг «Ответ: итоговый» — для того, что считается после судьи ───────────
--
-- ⚠⚠ Позиция: сразу **после проверки повтора** и перед записью ответа. Раньше
-- нельзя — `girl_response_fixed` ещё не положен; позже нельзя — запись его уже
-- прочитает.
SET @at = (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @said);

UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= @at
   AND @at IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf AND x.`title` = 'Ответ: итоговый');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @conv, 'Ответ: итоговый', @at,
       JSON_OBJECT('variable_conversion', JSON_ARRAY(JSON_OBJECT(
                     'text', COALESCE(@answer,
                       '%if girl_response_fixed%%girl_response_fixed%'
                       '%else%%girl_response%%endif%'),
                     'variable', 'girl_response_final')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @at IS NOT NULL AND @conv IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf AND x.`title` = 'Ответ: итоговый');

-- ── 5. Литералы в `inputs_map` меняются на имена переменных ──────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.kind', 'talk_history_chat_kind',
         '$.tool_invoke.inputs_map.limit', 'talk_history_chat_limit')
 WHERE `id` = @chat AND @chat IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.kind', 'talk_history_mail_kind',
         '$.tool_invoke.inputs_map.limit', 'talk_history_mail_limit')
 WHERE `id` = @mail AND @mail IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.spec', 'dice_spec')
 WHERE `id` = @dice AND @dice IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.kind', 'talk_session_kind',
         '$.tool_invoke.inputs_map.answer', 'girl_response_final')
 WHERE `id` = @said AND @said IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.kind', 'talk_session_kind')
 WHERE `id` = @quiet AND @quiet IS NOT NULL;

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Литералов не должно остаться ни одного: это и есть цель.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `metadata` LIKE '%_const_%') AS литералов,
       -- ⚠ Семь переменных объявлены — значит видны в списке редактора.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @wf
           AND v.`name` IN ('talk_history_chat_kind', 'talk_history_chat_limit',
                            'talk_history_mail_kind', 'talk_history_mail_limit',
                            'talk_session_kind', 'dice_spec',
                            'girl_response_final')) AS объявлено,
       -- ⚠⚠ Шесть значений кладёт «Ключи»: было две записи, стало восемь.
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.variable_conversion'))
          FROM `agent_workflow_step` WHERE `id` = @keys) AS записей_в_ключах,
       -- ⚠ Седьмое — свой шаг, и он обязан стоять перед записью ответа.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ответ: итоговый') AS шаг_ответа,
       (SELECT `position` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ответ: итоговый') AS его_позиция,
       (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @said) AS позиция_записи,
       -- ⚠⚠ Спецификация жребия обязана уцелеть целиком: обрежься она, жребий
       -- стал бы бросать по обрывку JSON и молча выбирать первый вариант.
       (SELECT LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.variable_conversion[7].text')))
          FROM `agent_workflow_step` WHERE `id` = @keys) AS длина_жребия_в_ключах;
