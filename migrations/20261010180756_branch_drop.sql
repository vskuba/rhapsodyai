-- Старый род шага «Ветка разговора» снят целиком (2026-10-10)
--
-- ЗАЧЕМ. Отбор темы переехал на `topic_action`: метки ищет код в тексте
-- разговора, вопросы темы задаёт подпоток, «yes» считает код. Старый приём —
-- развилка, называвшая метки моделью, — не читает больше никто, но его род
-- шага стоял в выпадающем списке редактора и путал.
--
-- ⚠⚠ ПЕРЕВОД ШАГОВ ИДЁТ ПЕРВЫМ, И БЕЗ НЕГО СНОС РОНЯЕТ ЧАТ. Движок берёт имя
-- рода из базы: удали строку раньше — и шаг, который на ней стоит, свалит
-- каждый ответ в чат. На проде такой шаг есть (#811), и локальной правкой его
-- не достать: данные доезжают туда только миграцией.
--
-- ⚠⚠ ПОСЛЕ ПЕРЕВОДА ТЕМА НА ПРОДЕ НЕ ПОДНИМЕТСЯ, пока человек не доделает две
-- вещи руками. Это НЕ поломка — чат отвечает как обычно, — но и не «всё
-- готово»:
--   1. у шага пусто поле «Переменная с историей общения»: подставить переменную
--      с текстом беседы, включая пришедшую реплику (`workflow_branch.md`, §6.3,
--      грабля про `talk_history_chat`);
--   2. метки тем переписать из фраз в слова-иглы, завести вопросы и пороги —
--      вкладка «Topic & Action».
-- Пустая история значит «меток не нашлось»: ни одна тема не поднимается, и
-- разговор идёт обычным путём. Падать нечему.
--
-- Полный перечень того, что здесь снимается, — `.claude/docs/workflow_branch.md`, §8.

-- ── 0. Что было до ──────────────────────────────────────────────────────────

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
         WHERE t.`name` = 'branch') AS шагов_branch,
       (SELECT COUNT(*) FROM `agent_workflow_step_type`
         WHERE `name` = 'branch') AS род_branch,
       (SELECT COUNT(*) FROM information_schema.VIEWS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME IN ('agent_workflow_branch', 'agent_workflow_branch_topic')
       ) AS мостов;

-- ── 1. Перевод оставшихся шагов на новый род ────────────────────────────────
--
-- ⚠ Переносятся карты вызова и подпоток — всё, что у пары «шаг + подпоток»
-- настроено руками. `branch_id` становится `topic_group_id`: это та же группа,
-- только таблица переименована.
--
-- ⚠⚠ Ключ `tags` НЕ переносится: он держал имя переменной, в которую прежняя
-- развилка клала названные моделью метки. Новый шаг метки не получает, а ищет
-- сам — ему нужен текст беседы, и это другое поле (`history`). Подставить его
-- может только человек: какая переменная несёт нужный срез, из метаданных не
-- выводится.

SET @topic_type = (SELECT `id` FROM `agent_workflow_step_type`
                    WHERE `name` = 'topic_action');

SET @sql = IF(@topic_type IS NULL,
    "SELECT 'Рода topic_action нет — переводить некуда' AS пропуск",
    "UPDATE `agent_workflow_step` s
        SET s.`type_id` = @topic_type,
            s.`metadata` = JSON_REMOVE(
                JSON_SET(s.`metadata`, '$.topic_action', JSON_OBJECT(
                    'topic_group_id', JSON_EXTRACT(s.`metadata`, '$.branch.branch_id'),
                    'history',        '',
                    'inputs_map',     COALESCE(JSON_EXTRACT(s.`metadata`, '$.branch.inputs_map'), JSON_OBJECT()),
                    'outputs_map',    COALESCE(JSON_EXTRACT(s.`metadata`, '$.branch.outputs_map'), JSON_OBJECT()),
                    'workflow_id',    JSON_EXTRACT(s.`metadata`, '$.branch.workflow_id')
                )),
                '$.branch')
      WHERE JSON_VALID(s.`metadata`)
        AND JSON_CONTAINS_PATH(s.`metadata`, 'one', '$.branch')");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 2. Род шага ─────────────────────────────────────────────────────────────
--
-- ⚠ Сносится только когда на нём не осталось ни одного шага: ссылка из
-- `agent_workflow_step.type_id` внешним ключом не прикрыта, и осиротевший шаг
-- получил бы `step_type_name` пустым — движок не узнал бы его вовсе.

SET @branch_steps = (
    SELECT COUNT(*) FROM `agent_workflow_step` s
      JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
     WHERE t.`name` = 'branch'
);

SET @sql = IF(@branch_steps = 0,
    "DELETE FROM `agent_workflow_step_type` WHERE `name` = 'branch'",
    "SELECT 'На роде branch ещё есть шаги — не сношу' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 3. Мосты на старые имена таблиц ─────────────────────────────────────────
--
-- ⚠ Их заводила `20261010120024_topic_action_rename.sql` ровно на окно
-- выкладки: старый код читал таблицы по прежним именам на каждом ответе в чат.
-- Кода, который их знает, больше нет.

DROP VIEW IF EXISTS `agent_workflow_branch_topic`;
DROP VIEW IF EXISTS `agent_workflow_branch`;

-- ── 4. Мёртвые колонки ──────────────────────────────────────────────────────
--
-- `match_min` — общий порог группы; пороги уехали к теме, по два на каждую.
-- `workflow_id` у группы — дорога переехала на шаг (§5).
-- `acceptance` / `direction` / `restriction` — три текста темы, сведённые в
-- один `instructions` миграцией `20261008144351`.

SET @has = (SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'agent_workflow_topic_group' AND COLUMN_NAME = 'match_min');
SET @sql = IF(@has = 1,
    "ALTER TABLE `agent_workflow_topic_group` DROP COLUMN `match_min`",
    "SELECT 'match_min уже снят' AS пропуск");
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has = (SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'agent_workflow_topic_group' AND COLUMN_NAME = 'workflow_id');
SET @sql = IF(@has = 1,
    "ALTER TABLE `agent_workflow_topic_group` DROP COLUMN `workflow_id`",
    "SELECT 'workflow_id у группы уже снят' AS пропуск");
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has = (SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'agent_workflow_topic' AND COLUMN_NAME = 'acceptance');
SET @sql = IF(@has = 1,
    "ALTER TABLE `agent_workflow_topic` DROP COLUMN `acceptance`, DROP COLUMN `direction`, DROP COLUMN `restriction`",
    "SELECT 'три текста темы уже сняты' AS пропуск");
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ── 5. Глобальная переменная словаря меток ──────────────────────────────────
--
-- ⚠ `branch_topic_catalog` показывался развилке, чтобы модель выбирала метки из
-- закрытого словаря. Развилки нет, метки ищет код — читателей не осталось.

DELETE FROM `agent_workflow_variable`
 WHERE `name` = 'branch_topic_catalog' AND `type` = 'global';

-- ── 6. Что стало ────────────────────────────────────────────────────────────

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step_type`
         WHERE `name` = 'branch') AS род_branch,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
         WHERE t.`name` = 'topic_action') AS шагов_topic_action,
       (SELECT COUNT(*) FROM information_schema.VIEWS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME IN ('agent_workflow_branch', 'agent_workflow_branch_topic')
       ) AS мостов,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'branch_topic_catalog') AS словарей;
