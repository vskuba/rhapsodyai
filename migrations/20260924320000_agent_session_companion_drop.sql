-- `agent_session` перестаёт знать про собеседника (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- У таблицы одно занятие: журнал вызова LLM — промпт, ответ, вызов инструмента,
-- потраченные токены. Столбец `companion_id` подмешивал к нему второй вопрос —
-- «кто с кем разговаривает», — и отвечал на него плохо: переписка попадала сюда
-- слепком собранного промпта, из которого разговор не выбрать ни по паре, ни по
-- времени, ни по каналу.
--
-- Теперь на этот вопрос отвечает `companion_session`, строкой на обмен.
--
-- ## ⚠ Порядок обязателен: сперва код, потом схема
--
-- Иначе первый же вызов упрётся в «Unknown column». Уехало перед этой миграцией:
--
--     src/ai/ai_session.py                       довод писателя; два мёртвых
--                                                читателя удалены совсем
--     src/ai/framework/agent/ai_framework.py     обёртка
--     src/ai/framework/agent/ai_framework_manager.py  поле модели и шесть вызовов
--     src/tool/session/session_.py               довод инструмента
--
-- ⚠⚠ Два читателя (`ai_session_messages`, `ai_session_uuid_get`) отбирали строки
-- **по этому столбцу** и не звались ниоткуда — ни из кода, ни из тестов. Они и
-- были той дорогой, ради которой столбец завели; дороги не стало задолго до
-- сегодня, просто столбец пережил её.
--
-- ## ⚠ Переменная `companion_id` остаётся, и это другое существо
--
-- В workflow есть переменная с тем же именем — ею `dating_talk` склеивает ключ
-- собеседника, и она приходит запросом от DatingAi. Одинаковое имя у столбца
-- журнала и у переменной вызова — совпадение, стоившее этой оговорки.
--
-- Точно так же остаётся поле `companion_id` в теле `POST /chat/ask`: им сосед
-- находит запись собеседника (`chat.py`, иначе 401). Уходит **только столбец**.
--
-- ## ⚠ Что теряется вместе со столбцом
--
-- Локально его несут 1 974 строки из 56 659. Потеря невелика: строка журнала
-- говорит, что спросили у модели, а с кем шёл разговор, теперь знает
-- `companion_session` — и знает разборно.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'workflow_shell_test');

-- ⚠⚠ Отчёт «ДО» идёт **подготовленным запросом**, и это не причуда: обычный
-- `SELECT … WHERE companion_id IS NOT NULL` разбирается до выполнения, то есть
-- и тогда, когда столбца уже нет. Повторный прогон падал бы на собственном
-- отчёте — «Unknown column 'companion_id' in 'where clause'», — успев при этом
-- сделать всю работу. Поймано репетицией.
SET @sql = IF(
    (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'agent_session'
        AND `COLUMN_NAME` = 'companion_id') > 0,
    'SELECT ''ДО'' AS этап, 1 AS столбец_есть,
            (SELECT COUNT(*) FROM `agent_session` WHERE `companion_id` IS NOT NULL)
              AS строк_со_ссылкой',
    'SELECT ''ДО'' AS этап, 0 AS столбец_есть, 0 AS строк_со_ссылкой');
PREPARE go FROM @sql; EXECUTE go; DEALLOCATE PREPARE go;

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.companion_id') IS NOT NULL)
         AS шагов_шлют_довод;

-- ── Довод у единственного, кто его слал ─────────────────────────────────────
--
-- ⚠ `workflow_shell_test` зовёт инструмент `session_message_add` и кладёт туда
-- `companion_id`. Довода у инструмента больше нет, и лишний ключ в `inputs_map`
-- уехал бы в вызов лишним параметром.
--
-- ⚠ Точечно по пути JSON: метка сидит внутри JSON-строки, и лесенка
-- экранирования в SQL-литерале уже однажды не сошлась — замена прошла «удачно»,
-- не изменив ничего (`…_wf_talk_companion_key`).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REMOVE(`metadata`, '$.tool_invoke.inputs_map.companion_id')
 WHERE `workflow_id` = @wf
   AND JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.companion_id') IS NOT NULL;

-- ── Связь и столбец ─────────────────────────────────────────────────────────
--
-- ⚠⚠ Связь снимается **раньше** столбца: `DROP COLUMN` под внешним ключом
-- отвечает «Cannot drop index … needed in a foreign key constraint», а не
-- убирает его заодно.
--
-- ⚠ Оба шага идут подготовленным запросом и только если есть что убирать:
-- повторный прогон иначе упал бы «check that column/key exists».
SET @sql = IF(
    (SELECT COUNT(*) FROM `information_schema`.`REFERENTIAL_CONSTRAINTS`
      WHERE `CONSTRAINT_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'agent_session'
        AND `CONSTRAINT_NAME` = 'fk_memory_companion') > 0,
    'ALTER TABLE `agent_session` DROP FOREIGN KEY `fk_memory_companion`',
    'SELECT ''связь уже снята'' AS _');
PREPARE go FROM @sql; EXECUTE go; DEALLOCATE PREPARE go;

SET @sql = IF(
    (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'agent_session'
        AND `COLUMN_NAME` = 'companion_id') > 0,
    'ALTER TABLE `agent_session` DROP COLUMN `companion_id`',
    'SELECT ''столбец уже убран'' AS _');
PREPARE go FROM @sql; EXECUTE go; DEALLOCATE PREPARE go;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'agent_session'
           AND `COLUMN_NAME` = 'companion_id') AS остался_столбец,
       (SELECT COUNT(*) FROM `information_schema`.`REFERENTIAL_CONSTRAINTS`
         WHERE `CONSTRAINT_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'agent_session')
         AS связей_осталось,
       -- ⚠ Журнал обязан уцелеть целиком: уходит столбец, а не строки.
       (SELECT COUNT(*) FROM `agent_session`) AS строк_журнала,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.companion_id') IS NOT NULL)
         AS шагов_шлют_довод;
