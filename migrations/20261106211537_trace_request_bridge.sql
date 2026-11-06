-- Мост «ответ → прогон»: индекс по `request_uuid` и разовая донастройка
-- `companion_session.request_uuid` (2026-11-06).

-- ## Зачем
--
-- Вкладка «Чат» страницы `/admin/session` теперь показывает у каждого нашего
-- ответа ссылку на Workflow Trace, которое этот ответ сочинило. Ключ связи —
-- `companion_session.request_uuid`: он и раньше был заведён «мостом в
-- `agent_session`» и в журнале прогонов (`agent_workflow_trace.request_uuid`),
-- но его **никто не заполнял** — на установке он пуст во всех строках.
-- С этой даты его ставит движок: там, где он уже ловит `id` записанного
-- обмена (`AI_FRAMEWORK_SESSION_TOOL`), он же кладёт в строку `request_uuid`
-- прогона. Дальше мост заполняется сам, каждой записью LLM.
--
-- Осталось связать то, что записано ДО этой даты. Единственный обратный
-- мост, который не нужно заводить, — контракт прогона: верхний прогон ручки
-- `/chat/ask` пишет в `agent_workflow_trace.response_json` тело ответа, а в
-- нём `message_id` — ровно номер обмена (`ai_workflow_trace_run_contract`,
-- миграция `20261013114318`). Им и дозаполняем пустые строки.
--
-- ## ⚠⚠ Индекс — до запроса страницы, а не после
--
-- Страница ищет прогон по ключу вызова (`request_uuid`) на каждой отрисовке
-- ленты. Без индекса это полный скан `agent_workflow_trace` — таблицы на
-- 174 МБ, где каждый следующий прогон дороже вчерашнего; про скан в ленте
-- говорит и шапка `.claude/docs/workflow_trace.md`. Индекс простой, по
-- одной колонке: у запроса нет второго условия, кроме `depth = 0`, и он
-- отрабатывает уже на отборе по ключу.
--
-- ## ⚠⚠ Контрактa нет у строк до 13.10.2026 — их не связать
--
-- Колонка `response_json` заведена миграцией `20261013114318`. У прогонов
-- раньше неё связываться нечем: текст ответа мы не сравниваем (одинаковые
-- реплики — не редкость, совпадение дало бы чужой прогон), а больше общего
-- ключа нет. Такие ответы остаются без ссылки — это честный «не знаем»,
-- а не сломанная ссылка.

SET @index_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_trace'
       AND INDEX_NAME = 'idx_agent_workflow_trace_request_uuid');

SET @sql = IF(@index_exists = 0,
    'ALTER TABLE `agent_workflow_trace`
       ADD INDEX `idx_agent_workflow_trace_request_uuid` (`request_uuid`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Донастройка моста. Только пустые строки: движок уже пишет `request_uuid`
-- сам, и переставлять его задним числом незачем. Верхние прогоны (`depth = 0`):
-- дочерние несут тот же `request_uuid` и тот же контракт, а ссылка должна
-- вести на прогон, который отдал ответ, — страница покажет дерево сама.
-- ⚠ Достаём номер через `CASE WHEN JSON_VALID`: `response_json` — TEXT, а не
-- JSON, и `JSON_EXTRACT` на битом теле не пропускает запрос ошибкой; MySQL не
-- обещает, что условие `JSON_VALID` слева от него вычислится первым.
--
-- ⚠ Ставим и строкам без ответа («тишина»): движок и в живом прогоне ставит
-- мост любой строке, которую записал инструмент, — отбор страницы решит это
-- сам, а разнобоя между старой и новой памятью таблицы быть не должно.
UPDATE `companion_session` `s`
  JOIN `agent_workflow_trace` `t`
    ON `t`.`depth` = 0
   AND `t`.`request_uuid` <> ''
   AND CAST(CASE WHEN JSON_VALID(`t`.`response_json`)
                 THEN JSON_UNQUOTE(JSON_EXTRACT(`t`.`response_json`, '$.message_id'))
            END AS UNSIGNED) = `s`.`id`
   SET `s`.`request_uuid` = `t`.`request_uuid`
 WHERE `s`.`request_uuid` = '';
