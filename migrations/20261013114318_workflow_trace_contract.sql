-- Трасса: контракт вызова, которым прогон начался и кончился (2026-10-13)
--
-- ## Зачем
--
-- Страница прогона показывает ЗАПРОС и ОТВЕТ — но это `prompt_user` и `result`
-- движка, то есть то, что увидел и вернул **workflow**. Чем его позвали по HTTP
-- и что ушло зовущему — не записано нигде:
--
--     запрос  /chat/ask: {question, agent_id, session_uuid, variables}
--     ответ   /chat/ask: {result, message_id, intentions}
--
-- Из прогона восстанавливаются только `question` (он же `prompt_user`),
-- `agent_id` и `session_uuid` — это колонки. `variables` запроса растворены в
-- `variables_start` вперемешку с переменными агента, ноды и реестра: какие из
-- полутора сотен имён прислал зовущий, по снапшоту не сказать. `message_id` и
-- `intentions` не хранятся вовсе — они живут на модели прогона и уезжают в
-- ответе HTTP.
--
-- ⚠⚠ Без них разбор жалобы «агент не ответил/ответил не то» упирается в
-- вопрос, на который нечем ответить: **что именно прислал зовущий**. Ровно так
-- уже искали потерянный `subtask_id` (см. `workflow_trace.md`) и молчащий
-- `message_id` — шесть дней.
--
-- ## Что делает
--
-- Две колонки на `agent_workflow_trace`, обе `LONGTEXT NULL`:
--
--     request_json   — тело запроса, которым прогон начали
--     response_json  — тело ответа, которым он кончился (или отказ)
--
-- ⚠ Колонки **общие**, а не «чатовые»: прогон начинают и `/chat/ask`, и
-- мини-приложение, и блог. Пишет их тот, кто владеет контрактом, — ручка;
-- движок про HTTP не знает и знать не должен.
--
-- ⚠ `NULL` — законное значение и останется им навсегда: у прогонов, снятых до
-- этой миграции, контракта нет и взяться ему неоткуда. Страница говорит об этом
-- прямо, а не рисует пустые скобки.
--
-- ⚠⚠ Это `ADD COLUMN` на таблице в 174 МБ. MySQL 8 делает такое `INSTANT`
-- (добавление в конец, без перестройки) — но только если колонка идёт
-- последней. Поэтому `AFTER` здесь НЕ указан: порядок колонок в этой таблице не
-- значит ничего, а перестройка под замком на проде значит очень много.

SELECT 'ДО' AS stage,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_trace'
           AND COLUMN_NAME IN ('request_json', 'response_json')) AS columns_found;

-- ---------------------------------------------------------------- request_json
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_trace'
        AND COLUMN_NAME = 'request_json') = 0,
    'ALTER TABLE `agent_workflow_trace` ADD COLUMN `request_json` LONGTEXT NULL',
    'SELECT ''request_json уже есть'' AS skipped');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- response_json
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_trace'
        AND COLUMN_NAME = 'response_json') = 0,
    'ALTER TABLE `agent_workflow_trace` ADD COLUMN `response_json` LONGTEXT NULL',
    'SELECT ''response_json уже есть'' AS skipped');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT 'ПОСЛЕ' AS stage,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_workflow_trace'
           AND COLUMN_NAME IN ('request_json', 'response_json')) AS columns_now;
