-- Трасса workflow: номер задачи и подзадачи — колонками, а не поиском по тексту
-- (2026-09-29)
--
-- ## Зачем
--
-- Конвейер задач находит свои прогоны по переменным старта, и до сих пор делал это
-- двумя способами, одинаково дорогими:
--
--   * `variables_start LIKE '%"subtask_id": "5219"%'` — подстрокой по LONGTEXT;
--   * `JSON_UNQUOTE(JSON_EXTRACT(variables_start, '$.task_id'))` — разбором JSON
--     в каждой строке таблицы.
--
-- И то и другое невозможно проиндексировать: условие считается **после** чтения
-- значения, то есть база обязана прочитать `variables_start` у всех 26 тысяч
-- прогонов — а это в среднем 2.9 КБ на строку и 174 МБ на таблицу. Замер на
-- проде: `LIKE`-поиск сессии — **639 мс**, разбор JSON под отмену — 80 мс,
-- и оба идут `type: ALL`.
--
-- Хуже цены — бесполезность работы: сегодня на проде ни у одного из 26 669
-- прогонов нет ни `task_id`, ни `subtask_id` в переменных (трафик там дейтинговый,
-- конвейер стоит). То есть 639 миллисекунд уходят на то, чтобы не найти ничего.
--
-- ## Что делаем
--
-- Заводим две **виртуальные** генерируемые колонки и индекс на них. Значение
-- вычисляется из того же `variables_start` — второго источника правды не
-- появляется, и писать в них не надо: движок трассы про них не знает и знать не
-- должен.
--
-- ⚠ **VIRTUAL, а не STORED, и это важно.** `STORED` переписывает всю таблицу —
-- 174 МБ под замком на проде. `VIRTUAL` добавляется как изменение метаданных, а
-- материализуется только в индексе, который строится `INPLACE`.
--
-- ## ⚠ Выражение обязано быть безотказным — иначе оно уронит запись трассы
--
-- Генерируемая колонка считается **на каждой вставке**. Ошибка в выражении — это
-- отказ `INSERT`, то есть потерянный прогон, а не кривая колонка. Отсюда три
-- страховки, и каждая закрывает свой случай:
--
--   1. `JSON_VALID(...)` — `variables_start` объявлен `LONGTEXT`, а не `JSON`, и
--      база его содержимое ничем не проверяет. `JSON_EXTRACT` по не-JSON бросает
--      ошибку.
--   2. `REGEXP '^[0-9]{1,9}$'` — значение приходит и строкой (`"5219"`), и числом
--      (`5219`): движок кладёт переменные как есть. `JSON_UNQUOTE` сводит оба к
--      строке цифр, а регулярное выражение отсеивает всё, что числом не является,
--      **до** приведения к `INT`. Девять знаков, а не сколько попало: десятый
--      уже переполняет `INT`.
--   3. `NULLIF(..., '')` — «ключа нет» и «ключ есть, но пустой» становятся
--      одинаковым `NULL`. Ровно так их и читает код конвейера:
--      `variables.get('subtask_id') or variables.get('task_id')` — пустая строка
--      там ложна и уступает место номеру задачи.
--
-- ⚠ Полагаться на нестрогий `sql_mode` (сейчас `NO_ENGINE_SUBSTITUTION`, то есть
-- `STRICT_TRANS_TABLES` выключен, и кривое приведение дало бы предупреждение
-- вместо отказа) здесь нельзя: режим меняется одной строкой в
-- `docker-compose.yml`, а сломается от этого запись трассы.
--
-- ## Индекс
--
-- Один составной `(subtask_id, task_id)`, а не два отдельных. Спрашивают их
-- всегда вместе и всегда в этом порядке: у подзадачи номер важнее — в её трассе
-- лежит и номер родителя, и по одному `task_id` задача забирала бы себе прогоны
-- всех своих подзадач.
--
-- Идемпотентность — через `information_schema` и `PREPARE`, как в `20260902125514`.

-- 1. Номер подзадачи.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND COLUMN_NAME = 'subtask_id'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `agent_workflow_trace`
        ADD COLUMN `subtask_id` INT
            GENERATED ALWAYS AS (
                NULLIF(REGEXP_SUBSTR(
                    IF(JSON_VALID(`variables_start`),
                       JSON_UNQUOTE(JSON_EXTRACT(`variables_start`, ''$.subtask_id'')),
                       NULL),
                    ''^[0-9]{1,9}$''), '''')
            ) VIRTUAL
            COMMENT ''Номер подзадачи из variables_start; NULL — прогон не из конвейера''
            AFTER `request_uuid`',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. Номер задачи.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND COLUMN_NAME = 'task_id'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `agent_workflow_trace`
        ADD COLUMN `task_id` INT
            GENERATED ALWAYS AS (
                NULLIF(REGEXP_SUBSTR(
                    IF(JSON_VALID(`variables_start`),
                       JSON_UNQUOTE(JSON_EXTRACT(`variables_start`, ''$.task_id'')),
                       NULL),
                    ''^[0-9]{1,9}$''), '''')
            ) VIRTUAL
            COMMENT ''Номер задачи из variables_start; у подзадачи здесь номер родителя''
            AFTER `subtask_id`',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. Индекс: спрашивают их вместе, подзадача первой.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_workflow_run_task'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `agent_workflow_trace`
        ADD INDEX `idx_workflow_run_task` (`subtask_id`, `task_id`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
