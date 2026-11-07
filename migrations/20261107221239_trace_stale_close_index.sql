-- Индексы под уборку брошенных прогонов (`ai_workflow_trace_runs_stale_close`).
--
-- Такт конвейера идёт из cron раз в минуту и звал уборку каждый такт. Цена
-- измерена на проде по `journal_mysql`: 55 159 прогонов, 12.2 часа суммарного
-- времени базы, самый долгий прогон — 623 с. Запрос группировал
-- `agent_workflow_trace_step` целиком (998 МБ, 223 тыс. строк) ради максимума по
-- каждому `run_id`, а `UPDATE` под `REPEATABLE-READ` держал next-key-замки на
-- просмотренных строках трасс — тех самых, в которые пишутся живые прогоны.
-- Вставка шага ждала до 18 минут, страницы отдавались по 90–180 с.
--
-- Запрос переписан на подзапрос по найденному прогону, и ему нужны два индекса:
--   * `agent_workflow_trace_step (run_id, created_at)` — максимум по шагам
--     одного прогона берётся одним обратным проходом по индексу вместо
--     группировки всей таблицы. Индекс от FK (`run_id` отдельно) этого не даёт:
--     по нему пришлось бы прочитать все строки прогона.
--   * `agent_workflow_trace (status, started_at)` — предпроверка «есть ли вообще
--     что закрывать» становится чисто индексной. Существующий
--     `idx_workflow_run_status (status, id)` до строк всё равно дочитывается:
--     `started_at` в нём нет.
--
-- ⚠ Оба ALTER идут INPLACE: добавление индекса перестройки таблицы не требует,
-- запись в таблицы на это время не останавливается.

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace_step'
       AND INDEX_NAME = 'idx_trace_step_run_created');
SET @sql = IF(@index_exists = 0,
    'ALTER TABLE `agent_workflow_trace_step`
       ADD INDEX `idx_trace_step_run_created` (`run_id`, `created_at`),
       ALGORITHM=INPLACE',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_trace_status_started');
SET @sql = IF(@index_exists = 0,
    'ALTER TABLE `agent_workflow_trace`
       ADD INDEX `idx_trace_status_started` (`status`, `started_at`),
       ALGORITHM=INPLACE',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
