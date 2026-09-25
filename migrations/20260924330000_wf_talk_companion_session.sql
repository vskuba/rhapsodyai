-- Разговор пишется и читается из `companion_session` (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Таблица заведена и наполнена прод-диалогами, но в неё никто не пишет и из неё
-- никто не читает: живая переписка по-прежнему копится у DatingAi, а ленту он
-- собирает из пяти своих таблиц и присылает готовым текстом. Домов два, и
-- разойдутся они на первой правке.
--
-- Эта миграция делает дом один:
--
--     читаем   два шага в начале кладут `talk_history_chat` и `talk_history_mail`
--     пишем    два шага перед выходами кладут обмен обратно
--
-- ## ⚠⚠ Шагов записи **два**, потому что и выхода два
--
-- Разговор кончается либо ответом, либо тишиной — и тишина тоже событие: реплика
-- пришла, на неё не ответили, и следующий раз агент обязан это видеть. Один шаг
-- на оба выхода поставить негде: они не сходятся.
--
-- ⚠⚠ **Прыжки на «Тишину» перенацелены на шаг записи.** Три перехода (27, 105,
-- 109) вели прямо в выход, и шаг, поставленный рядом по позиции, они бы
-- перескочили — переходы ходят по `step_id`, а не по соседству. Теперь они ведут
-- в запись, а та проваливается в «Тишину» следующим шагом. Ровно так же
-- перенацелен единственный прыжок на «Ответ» (из ветки писем и фото).
--
-- ## ⚠ Что кладётся в обмен
--
--     вопрос   %prompt_user%   пусто у инициативы — заговорили мы
--     ответ    тот же оборот, что отдаёт шаг «Ответ»: правленое, иначе сырое
--     канал    mail при `mail_mode`, иначе chat
--
-- ⚠ Канал и ответ приходят **метками в `_const_`**: метаданные шага проходят
-- подстановку до вызова инструмента, поэтому `%if mail_mode%` здесь работает.
--
-- ## ⚠ Чтение стоит после ключей и до всего остального
--
-- Ленты нужны промптам сочинения, а ключи — самому чтению. Между ними ставить
-- нечего, поэтому оба шага идут сразу за регистрацией сторон.
--
-- ⚠⚠ DatingAi продолжит слать `talk_history_*` своими переменными до тех пор,
-- пока не выложена его правка. Это **не** ломает переход: наши шаги кладут те же
-- имена, а переменные шага идут позже переменных запроса и побеждают. То есть
-- порядок выкладки свободный, чего почти не бывает.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @tool = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'tool_invoke');
-- ⚠⚠ Сторож повтора смотрит на **инструмент**, а не на заголовок. Заголовок —
-- подпись в редакторе, человек правит её когда хочет; переименуй он шаг, и
-- повторный прогон счёл бы шагов нет и завёл бы вторые — с теми же чтениями и
-- записями, то есть с двойной записью каждого обмена.
SET @made = (SELECT COUNT(*) FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'companion_session_history');

SELECT 'ДО' AS этап, @made AS шаги_уже_есть,
       -- ⚠⚠ Место для чтения обязано найтись: `NULL` означает, что шаг «Жребий»
       -- переименовали, и чтения встанут перед склейкой ключей — то есть прочтут
       -- пустоту. Ноль здесь — повод не выкладывать, а разбираться.
       @pos_read IS NOT NULL AS место_нашлось,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` LIKE 'companion\_session%') AS инструментов;

-- ── Инструменты в реестре ───────────────────────────────────────────────────
--
-- ⚠ `name` обязан совпадать с именем **функции**: движок достаёт её из модуля
-- через `getattr`. Разойдись они — шаг упадёт «не удалось подготовить функцию к
-- запуску», и виновата будет эта строка, а не код.
--
-- ⚠ Группа `Companion` уже есть — имя ей даёт папка инструмента с большой буквы.
SET @grp = (SELECT `id` FROM `tool_group` WHERE `name` = 'Companion' LIMIT 1);

INSERT INTO `tool` (`name`, `group_id`, `path`, `description`, `args`)
SELECT 'companion_session_add', @grp,
       '/app/src/tool/companion/companion_session.py',
       'Записать один обмен разговора: что спросил он, что ответили мы.',
       JSON_OBJECT('input', JSON_OBJECT(
                       'owner_unique_id', JSON_OBJECT('type', 'str', 'default', 'Required'),
                       'companion_unique_id', JSON_OBJECT('type', 'str', 'default', 'Required'),
                       'question', JSON_OBJECT('type', 'str', 'default', ''),
                       'answer', JSON_OBJECT('type', 'str', 'default', ''),
                       'kind', JSON_OBJECT('type', 'str', 'default', 'chat'),
                       'source_uid', JSON_OBJECT('type', 'str', 'default', '')),
                   'output', JSON_OBJECT('type', 'dict'))
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT 1) AS x
                    WHERE EXISTS (SELECT 1 FROM `tool`
                                   WHERE `name` = 'companion_session_add'));

INSERT INTO `tool` (`name`, `group_id`, `path`, `description`, `args`)
SELECT 'companion_session_history', @grp,
       '/app/src/tool/companion/companion_session.py',
       'Последние обмены пары строками промпта. Пусто — разговора не было.',
       JSON_OBJECT('input', JSON_OBJECT(
                       'owner_unique_id', JSON_OBJECT('type', 'str', 'default', 'Required'),
                       'companion_unique_id', JSON_OBJECT('type', 'str', 'default', 'Required'),
                       'kind', JSON_OBJECT('type', 'str', 'default', 'chat'),
                       'limit', JSON_OBJECT('type', 'int', 'default', '0')),
                   'output', JSON_OBJECT('type', 'str'))
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT 1) AS x
                    WHERE EXISTS (SELECT 1 FROM `tool`
                                   WHERE `name` = 'companion_session_history'));

-- ── Два шага чтения, сразу за регистрацией сторон ───────────────────────────
--
-- ⚠⚠ Здесь заголовок — **единственная** примета, и это осознанная уступка:
-- шагов с инструментом `dice` в этом workflow два («Жребий» и «Жребий письма»), и
-- структурно они не различаются вовсе. Переименуй кто-нибудь первый — `@pos_read`
-- станет `NULL`, и шаги чтения лягут в самое начало, **до** склейки ключей: они
-- читают `girl_unique_id`, которого там ещё нет.
--
-- Поэтому ниже стоит проверка `место_нашлось`: без неё беда была бы тихой.
SET @pos_read = (SELECT `position` FROM `agent_workflow_step`
                  WHERE `workflow_id` = @wf AND `title` = 'Жребий');

UPDATE `agent_workflow_step`
   SET `position` = `position` + 2
 WHERE `workflow_id` = @wf AND `position` >= @pos_read AND @made = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Разговор: чат', @pos_read,
       JSON_OBJECT('tool_invoke', JSON_OBJECT(
                       'tool_name', 'companion_session_history',
                       'inputs_map', JSON_OBJECT(
                           'owner_unique_id', 'girl_unique_id',
                           'companion_unique_id', 'companion_unique_id',
                           'kind', '_const_chat'),
                       -- ⚠ `str` — ключ авто-переменной у строкового ответа
                       -- (`{инструмент}_{шаг}_result_str`); `outputs_map` даёт
                       -- ей человеческое имя, которое и ждут промпты.
                       'outputs_map', JSON_OBJECT('str', 'talk_history_chat')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Разговор: письма', @pos_read + 1,
       JSON_OBJECT('tool_invoke', JSON_OBJECT(
                       'tool_name', 'companion_session_history',
                       'inputs_map', JSON_OBJECT(
                           'owner_unique_id', 'girl_unique_id',
                           'companion_unique_id', 'companion_unique_id',
                           'kind', '_const_mail'),
                       'outputs_map', JSON_OBJECT('str', 'talk_history_mail')),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- ── Шаг записи перед «Ответом» ──────────────────────────────────────────────
-- ⚠ Выход «Ответ» узнаём по **непустому промпту**: он отдаёт сочинённый текст, а
-- «Тишина» — пустую строку. Признак функциональный, в отличие от подписи.
SET @pos_ans = (SELECT `position` FROM `agent_workflow_step` s
                 JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
                 WHERE s.`workflow_id` = @wf
                   AND t.`name` = 'return_response_text'
                   AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`,
                         '$.prompt_user')) <> '');

UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= @pos_ans AND @made = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Разговор: записать ответ', @pos_ans,
       JSON_OBJECT('tool_invoke', JSON_OBJECT(
                       'tool_name', 'companion_session_add',
                       'inputs_map', JSON_OBJECT(
                           'owner_unique_id', 'girl_unique_id',
                           'companion_unique_id', 'companion_unique_id',
                           'question', 'prompt_user',
                           -- ⚠ Тот же оборот, что отдаёт сам выход: правленый
                           -- ответ, если он есть, иначе сырой. Разойдись они —
                           -- в переписке лежало бы не то, что ушло человеку.
                           'answer', '_const_%if girl_response_fixed%%girl_response_fixed%%else%%girl_response%%endif%',
                           'kind', '_const_%if mail_mode%mail%else%chat%endif%'),
                       'outputs_map', JSON_OBJECT()),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- ── Шаг записи перед «Тишиной» ──────────────────────────────────────────────
--
-- ⚠ Ответа здесь нет вовсе, и это не потеря: строка с одним вопросом честно
-- говорит «пришло, не ответили».
SET @pos_sil = (SELECT `position` FROM `agent_workflow_step` s
                 JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
                 WHERE s.`workflow_id` = @wf
                   AND t.`name` = 'return_response_text'
                   AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`,
                         '$.prompt_user')) = '');

UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= @pos_sil AND @made = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Разговор: записать тишину', @pos_sil,
       JSON_OBJECT('tool_invoke', JSON_OBJECT(
                       'tool_name', 'companion_session_add',
                       'inputs_map', JSON_OBJECT(
                           'owner_unique_id', 'girl_unique_id',
                           'companion_unique_id', 'companion_unique_id',
                           'question', 'prompt_user',
                           'kind', '_const_%if mail_mode%mail%else%chat%endif%'),
                       'outputs_map', JSON_OBJECT()),
                   'transitions_before', JSON_ARRAY(),
                   'transitions_after', JSON_ARRAY())
 WHERE @made = 0;

-- ── Прыжки ведут в запись, а та проваливается в выход ───────────────────────
--
-- ⚠⚠ Без этого вся затея бесполезна на трёх дорогах из четырёх: переход ходит по
-- `step_id`, и шаг, поставленный перед выходом по позиции, прыжок перескочит.
-- ⚠ Свои шаги записи различаем **доводом `answer`**: у шага перед «Ответом» он
-- есть, у шага перед «Тишиной» его нет вовсе — там реплика пришла, а ответа не
-- было. Признак функциональный: пропади он, шаг перестанет делать своё.
SET @id_ans = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf
                  AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                        '$.tool_invoke.tool_name')) = 'companion_session_add'
                  AND JSON_EXTRACT(`metadata`,
                        '$.tool_invoke.inputs_map.answer') IS NOT NULL);
SET @id_sil = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf
                  AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                        '$.tool_invoke.tool_name')) = 'companion_session_add'
                  AND JSON_EXTRACT(`metadata`,
                        '$.tool_invoke.inputs_map.answer') IS NULL);
SET @id_out_ans = (SELECT s.`id` FROM `agent_workflow_step` s
                    JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
                    WHERE s.`workflow_id` = @wf
                      AND t.`name` = 'return_response_text'
                      AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`,
                            '$.prompt_user')) <> '');
SET @id_out_sil = (SELECT s.`id` FROM `agent_workflow_step` s
                    JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
                    WHERE s.`workflow_id` = @wf
                      AND t.`name` = 'return_response_text'
                      AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`,
                            '$.prompt_user')) = '');

-- ⚠ Замена по тексту, а не по пути JSON: переходы лежат массивом, и нужный
-- элемент у каждого шага под своим номером. Ключ `"step_id"` со значением
-- достаточно приметен, чтобы не задеть чужое — кавычки ограничивают число
-- целиком, и `"107"` не совпадёт с `"1070"`.
--
-- ⚠⚠ **Написаний два, и оба живые.** `metadata` — это `longtext`, а не `json`:
-- база текст не выравнивает, и как его записали, так он и лежит. Из 97 шагов 81
-- несёт `"step_id": "107"` с пробелом, а 16 — `"step_id":"107"` без него.
-- Замена по одному написанию прошла «удачно», перенацелив два перехода из трёх;
-- третий молча остался вести прямо в выход, то есть запись на его дороге просто
-- не случалась бы. Поймано репетицией, а живой заход выглядел бы обычным.
-- ⚠⚠ Сличение **не зашиваем в переменную**: у неё оно «неявное» и столбцу не
-- уступает, а столбец разный — на проде `utf8mb4_0900_ai_ci`, локально
-- `utf8mb4_general_ci`. Отсюда «Illegal mix of collations» ровно на проде, где
-- проверить некому. Поймано репетицией на копии прода.
--
-- Поэтому сличение указано **в месте сравнения**, и указано `utf8mb4_bin`: он
-- есть в любой сборке и сравнивает побайтно — то самое, что нужно ключам JSON.
SET @sil_a = CONCAT('"step_id": "', @id_out_sil, '"');
SET @sil_b = CONCAT('"step_id":"', @id_out_sil, '"');
SET @sil_to_a = CONCAT('"step_id": "', @id_sil, '"');
SET @sil_to_b = CONCAT('"step_id":"', @id_sil, '"');

UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(REPLACE(`metadata`,
         @sil_a COLLATE utf8mb4_bin, @sil_to_a COLLATE utf8mb4_bin),
         @sil_b COLLATE utf8mb4_bin, @sil_to_b COLLATE utf8mb4_bin)
 WHERE `workflow_id` = @wf AND `id` NOT IN (@id_sil, @id_ans)
   AND (`metadata` LIKE CONCAT('%', @sil_a, '%') COLLATE utf8mb4_bin
     OR `metadata` LIKE CONCAT('%', @sil_b, '%') COLLATE utf8mb4_bin);

SET @ans_a = CONCAT('"step_id": "', @id_out_ans, '"');
SET @ans_b = CONCAT('"step_id":"', @id_out_ans, '"');
SET @ans_to_a = CONCAT('"step_id": "', @id_ans, '"');
SET @ans_to_b = CONCAT('"step_id":"', @id_ans, '"');

UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(REPLACE(`metadata`,
         @ans_a COLLATE utf8mb4_bin, @ans_to_a COLLATE utf8mb4_bin),
         @ans_b COLLATE utf8mb4_bin, @ans_to_b COLLATE utf8mb4_bin)
 WHERE `workflow_id` = @wf AND `id` NOT IN (@id_sil, @id_ans)
   AND (`metadata` LIKE CONCAT('%', @ans_a, '%') COLLATE utf8mb4_bin
     OR `metadata` LIKE CONCAT('%', @ans_b, '%') COLLATE utf8mb4_bin);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `tool` WHERE `name` LIKE 'companion\_session%') AS инструментов,
       -- ⚠ Запись обязана стоять **прямо перед** своим выходом: между ними
       -- шагов нет, иначе провал пойдёт не туда.
       (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @id_out_ans)
       - (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @id_ans)
         AS зазор_ответа,
       (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @id_out_sil)
       - (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @id_sil)
         AS зазор_тишины,
       -- ⚠⚠ Главная проверка: прямых прыжков в выходы не осталось ни одного.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND (`metadata` LIKE CONCAT('%', @sil_a, '%') COLLATE utf8mb4_bin
             OR `metadata` LIKE CONCAT('%', @sil_b, '%') COLLATE utf8mb4_bin
             OR `metadata` LIKE CONCAT('%', @ans_a, '%')
             OR `metadata` LIKE CONCAT('%', @ans_b, '%')))
         AS прыжков_мимо_записи,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND (`metadata` LIKE CONCAT('%', @sil_to_a, '%') COLLATE utf8mb4_bin
             OR `metadata` LIKE CONCAT('%', @sil_to_b, '%') COLLATE utf8mb4_bin
             OR `metadata` LIKE CONCAT('%', @ans_to_a, '%')
             OR `metadata` LIKE CONCAT('%', @ans_to_b, '%')))
         AS прыжков_в_запись,
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step` WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS d) AS позиции_столкнулись;
