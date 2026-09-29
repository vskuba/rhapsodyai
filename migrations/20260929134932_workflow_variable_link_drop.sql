-- Сужение: таблица связей `agent_workflow_variable_workflow` уходит
--
-- ## ⚠⚠ Эта миграция едет ОТДЕЛЬНОЙ выкладкой, после `20260929003100`
--
-- Владельца переменной (`agent_workflow_variable.workflow_id`) завела
-- `20260929003100_workflow_variable_own.sql`, и таблицу связей она намеренно
-- оставила жить. Причина — в её шапке целиком, коротко: миграции накатывает
-- новый контейнер uvicorn при старте, а трафик в это время держит старый слот,
-- и `telegram` с `worker_task` перезапускаются уже после переключения. Старый
-- код читает переменные через `JOIN agent_workflow_variable_workflow` — в том
-- числе `ai_workflow_load`, то есть каждый прогон workflow. Удали таблицу в той
-- же выкладке — и от наката до перезапуска телеграма любой запрос к агенту
-- падает с «Table doesn't exist».
--
-- Значит, условие ровно одно: **на установке уже работает код с `workflow_id`**.
-- После выкладки `20260929003100` это так, и таблицу можно убирать.
--
-- ⚠ Проверить перед выкладкой, что расширение доехало:
--
--     SELECT COUNT(*) FROM `_yoyo_migration`
--      WHERE `migration_id` = '20260929003100_workflow_variable_own';
--
-- Ноль — эта миграция рано: сначала выложи предыдущую.
--
-- ## Что делаем
--
-- Читателей у таблицы больше нет: `ai_workflow_load`,
-- `ai_workflow_variables_input_get`, редактор (`/workflow/{id}/variables` и
-- правка переменной), экспорт и импорт спрашивают `workflow_id` строки. Связи
-- же остались ровно такими, какими были до расширения, — данные из них
-- перенесены, и сверять больше нечего.
--
-- Второй шаг — `seed_table_config`: настройка перечисляет таблицы для снимка
-- seed, и таблица связей в ней стояла. Без вычистки сломается не миграция, а
-- **чистая база**: сборка снимка падала бы на удалённой таблице, а старый
-- снимок — при заливке (порядок старта `миграции → seed`).

-- ── 0. Что было ───────────────────────────────────────────────────────────────
--
-- ⚠ Про саму таблицу спрашиваем `information_schema`, а не её: на второй прогон
-- таблицы уже нет, и запрос к ней уронил бы миграцию там, где она обязана быть
-- пустой работой.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = 'agent_workflow_variable_workflow') AS таблица_связей,
       (SELECT COUNT(*) FROM `setting`
         WHERE `key` = 'seed_table_config' AND JSON_VALID(`value`)
           AND JSON_SEARCH(`value`, 'one', 'agent_workflow_variable_workflow')
               IS NOT NULL) AS в_списке_seed,
       (SELECT COUNT(*) FROM `_yoyo_migration`
         WHERE `migration_id` = '20260929003100_workflow_variable_own')
           AS расширение_доехало;

-- ── 1. Таблица связей ─────────────────────────────────────────────────────────

DROP TABLE IF EXISTS `agent_workflow_variable_workflow`;

-- ── 2. Имя таблицы из списка seed ─────────────────────────────────────────────
--
-- `JSON_SEARCH` возвращает `NULL`, когда имени в списке нет, — второй прогон не
-- трогает ни строки.

UPDATE `setting`
   SET `value` = JSON_REMOVE(
           `value`,
           JSON_UNQUOTE(JSON_SEARCH(`value`, 'one', 'agent_workflow_variable_workflow')))
 WHERE `key` = 'seed_table_config'
   AND JSON_VALID(`value`)
   AND JSON_SEARCH(`value`, 'one', 'agent_workflow_variable_workflow') IS NOT NULL;

-- ── 3. Что стало ──────────────────────────────────────────────────────────────
--
-- Оба числа обязаны быть нулями: таблицы нет, имени в списке seed нет.

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = 'agent_workflow_variable_workflow') AS таблица_связей,
       (SELECT COUNT(*) FROM `setting`
         WHERE `key` = 'seed_table_config' AND JSON_VALID(`value`)
           AND JSON_SEARCH(`value`, 'one', 'agent_workflow_variable_workflow')
               IS NOT NULL) AS в_списке_seed;
