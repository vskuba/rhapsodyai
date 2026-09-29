-- Трасса workflow: индексы под отборы, которые до сих пор шли полным проходом
-- (2026-09-29)
--
-- ## Зачем
--
-- Замерено на проде, `performance_schema.table_io_waits_summary_by_table`, 9 суток
-- аптайма: из 1.55 млрд прочитанных строк 1.53 млрд приходятся на две таблицы
-- трассы, и 2.5 часа из 2.9 — на чтение их же. У `agent_workflow_trace` при этом
-- всего 26 668 строк: 905 764 499 чтений — это примерно **34 тысячи полных
-- проходов**, по одному каждые 23 секунды. Столько же, сколько тикает опрос
-- страниц команды и задач (15 с).
--
-- Индексов у таблицы пять, и ни один не покрывает то, по чему её отбирают:
--
--   PRIMARY(id) · u_workflow_run_uuid(run_uuid) · idx_workflow_run_workflow(workflow_id, started_at)
--   idx_workflow_run_session(session_uuid) · idx_workflow_run_parent(parent_run_id)
--
-- `EXPLAIN SELECT id FROM agent_workflow_trace WHERE status = 'running'` отвечает
-- `type: ALL, possible_keys: NULL` — то есть ключа нет даже в кандидатах.
--
-- ## ⚠ Полный проход по этой таблице дороже, чем кажется по числу строк
--
-- В строке лежат три LONGTEXT (`variables_start` в среднем 2.9 КБ, до 9.4 КБ,
-- плюс `prompt_user` и `result`), и таблица весит 174 МБ при 26 тысячах строк.
-- Проход читает кластерный индекс целиком, то есть все 174 МБ, — а буферный пул
-- на всю базу (2.1 ГБ) до сегодняшнего дня был 128 МБ. Каждый такой проход
-- вытеснял из кэша **весь остальной проект**; отсюда 4.26 ТБ, прочитанных с
-- диска за девять суток. Размер пула правится отдельно, в `docker-compose.yml`.
--
-- ## Три индекса и что каждый закрывает
--
--   (status, id)         — `WHERE status = 'running' ORDER BY id`: опрос прогресса
--                          команды (`team_progress._runs_running`, каждые 15 с),
--                          список журналов конвейера (`task_log`), отмена
--                          (`task_abort`). Замер до: 80–81 мс на каждый.
--   (depth, status, id)  — список трассы `/admin/workflow_trace`: `WHERE depth = 0
--                          AND status = ? ORDER BY id DESC LIMIT 30` и счётчик
--                          `COUNT(*)` рядом с ним (73–87 мс). Порядок колонок
--                          именно такой: `depth` и `status` — равенства, `id`
--                          уходит в сортировку и в постраничный сдвиг.
--   (finished_at)        — уборка старых прогонов (119 мс на каждый показ списка,
--                          пока её не унесли в крон).
--
-- ⚠ **`id` дописан к обоим составным не для отбора, а чтобы индекс закрывал
-- сортировку.** Без него `ORDER BY id DESC` после отбора по индексу заставил бы
-- MySQL либо сортировать найденное, либо всё равно ходить в кластерный индекс за
-- порядком. С ним `COUNT(*)` по вкладке считается вовсе не трогая строки —
-- `Using index`, то есть ни одного LONGTEXT не прочитано.
--
-- ⚠ **`(status, id)` не лишний при наличии `(depth, status, id)`.** Составной
-- ключ читается слева направо: запрос без `depth` в условии — а таких три —
-- воспользоваться им не может.
--
-- ## Идемпотентность
--
-- `ADD INDEX IF NOT EXISTS` MySQL не поддерживает, поэтому проверка через
-- `information_schema` и `PREPARE` — тем же приёмом, что в `20260902125514`.
--
-- ⚠ На проде это `ALTER` по таблице в 174 МБ. MySQL 8 строит вторичный индекс
-- `ALGORITHM=INPLACE` без блокировки записи, но время на него уходит: миграции
-- прогоняются на старте `main_uvicorn.py`, и старт будет дольше обычного.

-- 1. Отбор по состоянию прогона: `WHERE status = ? ORDER BY id`.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_workflow_run_status'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `agent_workflow_trace` ADD INDEX `idx_workflow_run_status` (`status`, `id`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. Список трассы: верхний уровень плюс вкладка состояния, свежие сверху.
--    86 % строк таблицы — это `depth = 1` (23 031 из 26 668), и до сих пор
--    обратный проход по первичному ключу перебирал и отбрасывал их все.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_workflow_run_depth_status'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `agent_workflow_trace`
        ADD INDEX `idx_workflow_run_depth_status` (`depth`, `status`, `id`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. Уборка по сроку: `WHERE finished_at < NOW() - INTERVAL ? DAY`.
--    Одна колонка, а не пара с `depth`: уборка берёт строки пачками по времени, и
--    `depth` в ней — условие-довесок, а не отбор.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_workflow_run_finished'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `agent_workflow_trace` ADD INDEX `idx_workflow_run_finished` (`finished_at`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
