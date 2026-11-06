-- Поле «сообщение → прогон»: `agent_workflow_trace.message_id` (2026-11-07).

-- ## Зачем
--
-- Вкладка «Чат» отвечает на вопрос «каким прогоном сочинён этот ответ» через
-- `companion_session.request_uuid` — ключ вызова (`20261106211537`). Он ищет
-- прогон по КЛЮЧУ ВЫЗОВА, то есть связывает строку с вызовом целиком. У
-- строки, которую привезла дверь `/chat/message/add` (письма по намерениям
-- их почтовика, правки оператора), ключа нет: строку писал не движок, и
-- связывать её было нечем — даже когда прогон, сочинивший текст, в журнале
-- есть и номер обмена в его ответе назван (`response_json.$.message_id`).
--
-- Номер обмена и есть тот же самый ключ, только названный прямо: у каждого
-- сообщения он есть, а у прогона, который его записал, он лежит в контракте
-- ответа. Вынести его из JSON в свою колонку — значит сделать поиск прогона
-- по сообщению обычным индексным `WHERE message_id = <номер>`: без JSON, без
-- скана, без коллации (целое о целое — сравниваемо на любой установке, ср.
-- `20261106230614` про строковый ключ).
--
-- У прогона, который кончился ошибкой, таймаутом или «Стопом», номера нет:
-- отвечать было нечем и обмен не записан. Колонка остаётся NULL — это
-- «прогон не записал сообщение», а не «пробегал мимо».
--
-- ## ⚠⚠ Индекс — до запроса страницы, колонка — INSTANT
--
-- Лента вкладки ищет по `message_id` на каждой отрисовке; без индекса это
-- скан таблицы трасс (шапка `workflow_trace.md` говорит про скан прямо).
-- Добавление колонки — `ALGORITHM=INSTANT` (сервер 8.0, таблица большая),
-- индекс — `ALGORITHM=INPLACE`: горячий журнал пишет в трассы непрерывно,
-- COPY встал бы на весь перестроить. Разными `ALTER`-ами, потому что
-- combined-форма в INSTANT не помещается и съехала бы в INPLACE обоими.

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND COLUMN_NAME = 'message_id');

SET @sql = IF(@column_exists = 0,
    'ALTER TABLE `agent_workflow_trace`
       ADD COLUMN `message_id` int NULL DEFAULT NULL
       COMMENT ''Номер обмена (companion_session.id), который записал прогон; NULL — прогон ничего не записал''
       AFTER `request_uuid`,
       ALGORITHM=INSTANT',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_agent_workflow_trace_message_id');

SET @sql = IF(@index_exists = 0,
    'ALTER TABLE `agent_workflow_trace`
       ADD INDEX `idx_agent_workflow_trace_message_id` (`message_id`),
       ALGORITHM=INPLACE',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Донастройка колонки из контракта. Только пустые: контракт нового прогона
-- кладёт номер сам (`ai_workflow_trace_run_contract`), переставлять задним
-- числом незачем. Верхние прогоны (`depth = 0`): контракт пишет ручка про
-- свой вызов, дочерние ответа не отдавали.
--
-- ⚠ `CASE WHEN JSON_VALID`, а не голый `JSON_EXTRACT`: `response_json` —
-- TEXT, а не JSON, и на битом теле `JSON_EXTRACT` рвёт запрос ошибкой;
-- короткого замыкания в `AND` сервер не обещает (тот же приём, что в
-- `20261106211537`).
--
-- ⚠ `> 0` отсекает и `0` («тишина»: агент промолчал, обмена нет), и пустой
-- результат разбора — обоим законный NULL.
UPDATE `agent_workflow_trace`
   SET `message_id` = CAST(CASE WHEN JSON_VALID(`response_json`)
                                THEN JSON_UNQUOTE(JSON_EXTRACT(`response_json`, '$.message_id'))
                           END AS SIGNED)
 WHERE `message_id` IS NULL
   AND `depth` = 0
   AND CAST(CASE WHEN JSON_VALID(`response_json`)
                  THEN JSON_UNQUOTE(JSON_EXTRACT(`response_json`, '$.message_id'))
             END AS SIGNED) > 0;
