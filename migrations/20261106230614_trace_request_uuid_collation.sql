-- Коллация сравнения: `request_uuid` трасс живёт в чужой коллации (2026-11-06)

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

-- ⚠⚠ Смена коллации для MySQL — смена типа колонки: INPLACE не поддерживается
-- (1846 на ровном месте), исполняется только `ALGORITHM=COPY` — перестройкой
-- таблицы копией. На проде это 1 мин 26 с на 689 МБ, и в 90-секундное окно
-- healthcheck при старте контейнера перестройка не влезает: первая же выкладка с
-- этим ALTER как раз на том и споткнулась (процесс умирал на миграции, слот не
-- отвечал, откат). Поэтому на этой установке ALTER проведён 06.11.2026 ВРУЧНУЮ,
-- в вечерном затишье, а миграция остаётся сторожем и дорогой для свежих
-- установок, где таблица пуста и копия — секунды.

SET @collation = (
    SELECT `COLLATION_NAME` FROM `information_schema`.`COLUMNS`
     WHERE `TABLE_SCHEMA` = DATABASE()
       AND `TABLE_NAME` = 'agent_workflow_trace'
       AND `COLUMN_NAME` = 'request_uuid');

-- Ровняем к той же коллации, что у всего проекта в новых миграциях. Значения
-- не меняются (utf8mb4 → utf8mb4), перестраивается только колонка и её индекс —
-- но целиком таблицей (копия), см. ⚠⚠ выше: на выровненной установке сторож
-- пропускает ALTER, на свежей копия пуста и быстры.
SET @sql = IF(@collation = 'utf8mb4_general_ci',
    'SELECT 1',
    'ALTER TABLE `agent_workflow_trace`
       MODIFY `request_uuid` CHAR(36)
       CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL,
     ALGORITHM=COPY');

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
