-- Модель по умолчанию у агента: `agent.llm_id` (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Модель агенту не принадлежала: её брала нода. Все точки входа зовут
-- `ai_llm_node_get(node_id)` и берут первую по приоритету ноду — а другому
-- агенту из всех агентов ноды свою модель не поставить: захочешь выделить,
-- заводи отдельную ноду. Колонка говорит точке входа «этому агенту — вот эта
-- модель», не трогая ноду и не размножая записи.
--
-- ## ⚠⚠ `NULL` и БЕЗ умолчания
--
-- У всех существующих агентов пина нет, и они обязаны вести себя ровно как
-- сегодня — первая по приоритету ноды. Выдумывать умолчание нечем: «модель по
-- ноде» числом не выразишь, unknown нельзя притворять известным значением.
--
-- ## FK с ON DELETE SET NULL — чтобы удаление модели возвращало к ноде
--
-- Модель из справочника удалена — агенту не на что опираться, и `NULL`
-- возвращает его к поведению ноды, а не вешает битую ссылку. Идемпотентность:
-- колонка и ключ заводятся по условию через `information_schema` и `PREPARE` —
-- вторым прогоном миграция видит их на месте и ничего не делает (тот же приём,
-- что в `20260911180339_agent_variable.sql`).

-- ── 1. Колонка ────────────────────────────────────────────────────────────────

SET @has_column := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent'
       AND COLUMN_NAME = 'llm_id'
);

SET @sql := IF(@has_column = 0,
    'ALTER TABLE `agent`
        ADD COLUMN `llm_id` INT NULL DEFAULT NULL
            COMMENT ''Модель по умолчанию для этого агента; NULL — брать по приоритету ноды''
            AFTER `workflow_id`',
    'SELECT ''колонка уже есть'' AS пропуск');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 2. Ключ: удалённая модель возвращает агента к ноде ─────────────────────────

SET @has_fk := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent'
       AND CONSTRAINT_NAME = 'ag_llm'
);

SET @sql := IF(@has_fk = 0,
    'ALTER TABLE `agent`
        ADD CONSTRAINT `ag_llm` FOREIGN KEY (`llm_id`) REFERENCES `llm` (`id`)
            ON DELETE SET NULL',
    'SELECT ''ключ уже есть'' AS пропуск');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
