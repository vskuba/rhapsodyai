-- Поле «сообщение → прогон»: `companion_session.workflow_trace_uuid` (2026-11-07).

-- ## Зачем

-- Вкладка «Чат» отвечала на вопрос «каким прогоном сочинён этот ответ» двумя
-- скалярными подзапросами на каждой отрисовке ленты: сначала по номеру обмена,
-- который прогон назвал в своём ответе (`agent_workflow_trace.message_id`),
-- затем по ключу вызова (`request_uuid`). Оба поиска искали с другой стороны:
-- у журнала. А сочинивший прогон у текста ровно ОДИН — это обычный внешний
-- ключ, ему место там, где «многие», то есть у строки обмена. Адрес ложится в
-- строку один раз, в момент записи, — страница его читает, а не ищет.

-- Записывают адрес те же две точки, что и писали ключи:
--  * движок, когда `companion_session_add` вернул номер строки, — вместе со
--    `request_uuid` тем же `UPDATE`-ом (`ai_framework_manager`, перехват
--    инструмента); адрес — верхнего прогона, дочерние модель не переписывают;
--  * дверь `/chat/message/add` с `composing_message_id` — строкам, которых
--    движок не касался (письма по намерениям их почтовика).

-- Колонка `agent_workflow_trace.message_id` остаётся: это ключ, который прогон
-- назвал сам, — по нему вяжет дверь и по нему же донастраивается история ниже.

-- ## ⚠⚠ Индекс не заводим

-- Чип читает колонку из своей строки по PRIMARY ленты — индекса для этого не
-- бывает нужно. Обратный запрос («какие обмены сочинил прогон») страницей не
-- задаётся, а пустой индекс на живой таблице — только налог на запись.

-- ## Колонка — INSTANT

-- Лента на проде читается непрерывно; `ALGORITHM=INSTANT` (сервер 8.0) не
-- берёт таблицу в перестроение. Guard по `information_schema` — как у
-- `20261107004418`: повторный накат обязан проходить молча.

SET @column_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'companion_session'
       AND COLUMN_NAME = 'workflow_trace_uuid');

SET @sql = IF(@column_exists = 0,
    'ALTER TABLE `companion_session`
       ADD COLUMN `workflow_trace_uuid` char(36) COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''''
       COMMENT ''run_uuid прогона из agent_workflow_trace, сочинившего этот ответ; пусто — прогон неизвестен, чипа нет''
       AFTER `request_uuid`,
       ALGORITHM=INSTANT',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ## Донастройка истории — теми же двумя ключами

-- Тот самый порядок точности, что жили в роутере, переезжает сюда, в один
-- проход: номер обмена из контракта ответа (прогон, ЗАПИСАВШИЙ строку) —
-- точнее, его берём первым; ключ вызова — общий на весь вызов, годится вторым.
-- Оба пути только по верхним прогонам (`depth = 0`): под-сюжет ответ не
-- сочинял; `ORDER BY id LIMIT 1` при повторе ключа — иначе выбор гулял бы.

-- ⚠ `s`.`request_uuid` <> '' — пустой ключ ни с чем не сравниваем: два пустых
-- ключа связались бы друг с другом и навесили чип наугад.

-- ⚠ EXISTS в WHERE: обе дороги могут не найтись, а присвоить NULL колонке
-- NOT NULL сервер не позволит (1048 на весь `UPDATE`).

UPDATE `companion_session` s
   SET s.`workflow_trace_uuid` = COALESCE(
       (SELECT t.`run_uuid` FROM `agent_workflow_trace` t
         WHERE t.`message_id` = s.`id`
           AND t.`depth` = 0
         ORDER BY t.`id` LIMIT 1),
       (SELECT t.`run_uuid` FROM `agent_workflow_trace` t
         WHERE t.`request_uuid` = s.`request_uuid`
           AND s.`request_uuid` <> ''
           AND t.`depth` = 0
         ORDER BY t.`id` LIMIT 1))
 WHERE s.`workflow_trace_uuid` = ''
   AND (EXISTS (SELECT 1 FROM `agent_workflow_trace` t
                 WHERE t.`message_id` = s.`id` AND t.`depth` = 0)
     OR EXISTS (SELECT 1 FROM `agent_workflow_trace` t
                 WHERE t.`request_uuid` = s.`request_uuid`
                   AND s.`request_uuid` <> ''
                   AND t.`depth` = 0));

-- ⚠⚠ После выкладки — тем же текстом. Миграция накатывается до переключения
-- зелёного слота, и строки, записанные старым кодом в эти секунды окна,
-- адреса не получат: прогон уже отработал, донастройка мимо него прошла.
-- `UPDATE` идемпотентен (`workflow_trace_uuid = ''`), повтор его добирает.
