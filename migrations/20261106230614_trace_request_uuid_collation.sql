-- Коллизация сравнения: `request_uuid` трасс живёт в чужой коллации (2026-11-06)

-- ## Зачем
--
-- Чип «⚙ trace» ищет прогон сравнением `agent_workflow_trace.request_uuid =
-- companion_session.request_uuid` (миграция `20261106211537`, лента вкладки
-- «Чат»). На проде это сравнение рвануло на первой же загрузке страницы:
--
--     OperationalError (1267): Illegal mix of collations
--     (utf8mb4_0900_ai_ci,IMPLICIT) and (utf8mb4_general_ci,IMPLICIT) for operation '='
--
-- ## Причина
--
-- `agent_workflow_trace` заведена в замороженной начальной схеме без `COLLATE`
-- в конце (`ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`) — значит коллацию колонок
-- унаследовала от сервера, на котором миграция бежала. `companion_session`
-- (миграция `20260924300000`) задала `COLLATE utf8mb4_general_ci` каждой
-- колонке явно. На деве оба конца `utf8mb4_general_ci` — сравнение
-- работало и проходило тесты; на проде у трасс оказался `utf8mb4_0900_ai_ci`
-- (серверный умолчанию utf8mb4), и сравнение колонка-с-колонкой стало
-- неразрешимым. Сравнения с литералом такая беда не касается — поэтому бэкфилл
-- прошлой миграции (`t.request_uuid <> ''`) отработал молча, и проверка на деве
-- ничего не показала.

-- ⚠⚠ Начальная схема заморожена и не правится — живёт здесь, новой миграцией.
-- Тот же корень может дремать в других колонках трасс на проде; сравниваемся
-- мы сегодня только этой одной, её и ровняем.

SET @collation = (
    SELECT `COLLATION_NAME` FROM `information_schema`.`COLUMNS`
     WHERE `TABLE_SCHEMA` = DATABASE()
       AND `TABLE_NAME` = 'agent_workflow_trace'
       AND `COLUMN_NAME` = 'request_uuid');

-- Ровняем к той же коллации, что у всего проекта в новых миграциях. Значения
-- не меняются (utf8mb4 → utf8mb4), перестраивается только колонка и её индекс.
-- `ALGORITHM=INPLACE` — чтобы перестройка горячего журнала не ложилась на него
-- копией с блокировкой: если среда не умеет INPLACE, миграция упадёт громко на
-- новом слоте ДО переключения, а не тихой блокировкой на проде.
SET @sql = IF(@collation = 'utf8mb4_general_ci',
    'SELECT 1',
    'ALTER TABLE `agent_workflow_trace`
       MODIFY `request_uuid` CHAR(36)
       CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL,
     ALGORITHM=INPLACE');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Признак починки: то самое сравнение, которое роняло страницу.
SELECT COUNT(*) AS связано_мостов
  FROM `companion_session` `s`
 WHERE `s`.`request_uuid` <> ''
   AND EXISTS (SELECT 1 FROM `agent_workflow_trace` `t`
                WHERE `t`.`request_uuid` = `s`.`request_uuid`
                  AND `t`.`depth` = 0);
