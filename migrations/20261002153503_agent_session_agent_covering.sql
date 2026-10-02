-- Отбор по агенту тоже перестаёт ходить в таблицу (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Вторая половина работы, начатой в `…_agent_session_list_covering`. Тот
-- индекс накрыл список БЕЗ фильтра, и на проде это сразу видно:
--
--     страница списка          3,9 с  →  0,84 с   Using index
--     DISTINCT kind_type       1,1 с  →  0,24 с   Using index
--
-- Но два запроса остались в таблице на 1 328 МБ, и оба на горячем пути:
--
--     список с фильтром по агенту   2,94 с   Using temporary; filesort, в таблицу
--     пары для отборов              3,18 с   в таблицу
--
-- Второй идёт на КАЖДОМ открытии страницы: из него собираются оба отбора
-- (`/session/agent/list`). То есть страница упирается теперь в него.
--
-- Причина та же: `idx_agent_user` отдаёт только `agent_id, user_id,
-- created_at`, а выборке нужны ещё `session_uuid`, `kind_type` и `role`.
-- Трёх столбцов хватает отфильтровать, но не хватает ответить.
--
-- ## Что делает миграция
--
-- Расширяет `idx_agent_user` с трёх столбцов до шести:
--
--     (agent_id, user_id, created_at, session_uuid, kind_type, role)
--
-- После этого все шесть запросов страницы показывают `Using index` —
-- проверено переписью планов на копии боевых данных (443 371 строка).
--
-- ## ⚠⚠ ПОРЯДОК ШАГОВ ОБЯЗАТЕЛЕН: сперва новый индекс, потом снос старого
--
-- На `agent_id` висит внешний ключ `fk_memory_agent`, и единственный индекс,
-- который его обслуживает, — это `idx_agent_user`. Снеси его первым, и
-- InnoDB откажет: «Cannot drop index … needed in foreign key constraint».
-- Поэтому новый строится под временным именем, потом уходит старый, потом
-- имя возвращается на место (`RENAME INDEX` — это правка метаданных, мгновенная).
--
-- ## ⚠ Почему отдельной выкладкой, а не вместе с первым индексом
--
-- Вместе два индекса строятся 60–80 секунд, а `bluegreen.sh` ждёт ответа
-- нового слота 90. Миграции накатывает новый контейнер при старте, до
-- переключения слота, — то есть сборка стоит прямо в окне healthcheck.
-- Запас в десять секунд запасом не является.
--
-- ## ⚠ ALGORITHM=INPLACE, LOCK=NONE — прод продолжает писать
--
-- Указано явно: умолчание выбрала бы сама база, а молчаливый откат к
-- `LOCK=SHARED` на боевой таблице — это остановка всех вызовов модели на
-- время сборки.
--
-- Цена: индексы вырастают до ~157 МБ при таблице в 1 328 МБ (замерено на
-- копии боевых столбцов). Идемпотентность: каждый шаг заводится по проверке
-- числа столбцов в `information_schema`, файл переживает любое число прогонов.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
           AND INDEX_NAME = 'idx_agent_user') AS столбцов_в_idx_agent_user,
       (SELECT ROUND(INDEX_LENGTH/1024/1024) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session') AS индексы_мб;

-- ---------------------------------------------------------------- 1. Новый под временным именем
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
        AND INDEX_NAME = 'idx_agent_user_new') = 0
    AND (SELECT COUNT(*) FROM information_schema.STATISTICS
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
            AND INDEX_NAME = 'idx_agent_user') = 3,
    'ALTER TABLE `agent_session`
        ADD INDEX `idx_agent_user_new`
            (`agent_id`, `user_id`, `created_at`, `session_uuid`, `kind_type`, `role`),
        ALGORITHM=INPLACE, LOCK=NONE',
    'SELECT ''расширенный индекс уже заведён либо старого в три столбца нет'' AS пропуск');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- 2. Старый уходит: ключ держит новый
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
        AND INDEX_NAME = 'idx_agent_user_new') = 6
    AND (SELECT COUNT(*) FROM information_schema.STATISTICS
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
            AND INDEX_NAME = 'idx_agent_user') = 3,
    'ALTER TABLE `agent_session` DROP INDEX `idx_agent_user`, ALGORITHM=INPLACE, LOCK=NONE',
    'SELECT ''старый idx_agent_user уже убран'' AS пропуск');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- 3. Имя возвращается на место
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
        AND INDEX_NAME = 'idx_agent_user_new') = 6
    AND (SELECT COUNT(*) FROM information_schema.STATISTICS
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
            AND INDEX_NAME = 'idx_agent_user') = 0,
    'ALTER TABLE `agent_session` RENAME INDEX `idx_agent_user_new` TO `idx_agent_user`',
    'SELECT ''переименование не требуется'' AS пропуск');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
           AND INDEX_NAME = 'idx_agent_user') AS столбцов_в_idx_agent_user,
       (SELECT COUNT(*) FROM information_schema.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session'
           AND INDEX_NAME = 'idx_agent_user_new') AS временных_осталось,
       (SELECT ROUND(INDEX_LENGTH/1024/1024) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_session') AS индексы_мб;
