-- Тема: три текста сведены в один — `instructions` (2026-10-08)
--
-- ЗАЧЕМ. У темы было три поля — `acceptance` / `direction` / `restriction`, — и
-- на форме они стояли вкладками: видно одно, два спрятаны. Деление оказалось
-- вымышленным: человек пишет инструкцию целиком, а разложить её по трём
-- коробкам может только гадая, в какую из них ляжет «соглашайся, но не обещай
-- часа». Вкладки при этом прятали написанное — заполненность приходилось
-- показывать точкой.
--
-- ⚠ Сводятся ТЕКСТЫ, а не смысл: поля склеиваются в том же порядке, в каком их
-- читал промпт, и с подписями вместо заголовков, которые в промпте стояли
-- отдельными строками. Ответы ветки от этого не меняются.
--
-- ⚠⚠ Старые три колонки здесь НЕ сносятся. Миграции накатывает новый контейнер
-- ДО переключения слота, а трафик в этот момент держит ещё старый код, который
-- их читает (`deploy.md`). Снос — второй выкладкой, как у
-- `agent_workflow_branch.workflow_id`.
--
-- Устройство слоя — `.claude/docs/workflow_branch.md`.

-- ── 1. Колонка ──────────────────────────────────────────────────────────────

SET @has_instructions = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_branch_topic'
       AND COLUMN_NAME = 'instructions'
);

SET @sql = IF(@has_instructions = 0,
    "ALTER TABLE `agent_workflow_branch_topic` ADD COLUMN `instructions` TEXT NULL AFTER `tags`",
    "SELECT 'Колонка instructions уже есть' AS пропуск");

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 2. Склейка трёх текстов в один ──────────────────────────────────────────
--
-- ⚠ Подписи на английском: тексты тем на установке английские и уезжают в
-- английский промпт. Русская подпись посреди английского абзаца читалась бы
-- моделью как смена темы.
--
-- ⚠⚠ Пустые части не дают пустых заголовков: у темы `money` из тестов заполнен
-- только запрет, и «Direction:» над пустотой был бы указанием в никуда.
--
-- ⚠ Условие `instructions IS NULL OR = ''`: повторный накат не должен
-- склеивать поверх уже склеенного и не должен затирать правку человека.

SET @gap = CONCAT(CHAR(10), CHAR(10));

UPDATE `agent_workflow_branch_topic`
   SET `instructions` = TRIM(CONCAT(
           IFNULL(NULLIF(TRIM(`acceptance`), ''), ''),
           IF(NULLIF(TRIM(`direction`), '') IS NULL, '',
              CONCAT(@gap, 'Where to lead the conversation:', CHAR(10),
                     TRIM(`direction`))),
           IF(NULLIF(TRIM(`restriction`), '') IS NULL, '',
              CONCAT(@gap, 'What is forbidden:', CHAR(10),
                     TRIM(`restriction`)))))
 WHERE (`instructions` IS NULL OR `instructions` = '')
   AND (NULLIF(TRIM(IFNULL(`acceptance`, '')), '') IS NOT NULL
        OR NULLIF(TRIM(IFNULL(`direction`, '')), '') IS NOT NULL
        OR NULLIF(TRIM(IFNULL(`restriction`, '')), '') IS NOT NULL);

-- ── 3. Промпт, который читал три переменные ─────────────────────────────────
--
-- ⚠⚠ Правка промпта здесь — не вольность движка, а продолжение этой же замены:
-- переменных `%topic_accept%`, `%topic_restrict%`, `%topic_direction%` после неё
-- не существует, и оставленный как был промпт уронил бы шаг сторожем меток
-- («метка без значения», `workflow.md` §4a-bis). Три блока сводятся в один тем
-- же порядком, в каком стояли.
--
-- `\n` — как последовательность символов: в колонке лежит JSON строкой, и
-- перенос в нём записан двумя знаками.

SET @nl = CONCAT(CHAR(92), 'n');

SET @was = CONCAT(
    'The text must based on follow accepted criteria:', @nl, '%topic_accept%', @nl, @nl,
    'The text must based on follow restriction criteria:', @nl, '%topic_restrict%', @nl, @nl,
    'The text must based on follow direction criteria:', @nl, '%topic_direction%');

SET @now = CONCAT(
    'The text must based on follow instructions:', @nl, '%topic_instructions%');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE LOCATE(@was, `metadata`) > 0) AS шагов_с_тремя_блоками,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE LOCATE('%topic_accept%', `metadata`) > 0
            OR LOCATE('%topic_direction%', `metadata`) > 0
            OR LOCATE('%topic_restrict%', `metadata`) > 0) AS шагов_со_старыми_метками;

UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(`metadata`, @was, @now)
 WHERE LOCATE(@was, `metadata`) > 0;

-- ── Итог ────────────────────────────────────────────────────────────────────
--
-- ⚠ «Осталось со старыми метками» обязано быть нулём. Не ноль — промпт собран
-- иначе, чем ожидала замена, и его правит человек руками: сторож меток уронит
-- шаг на первом же прогоне.

SELECT 'ГОТОВО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_branch_topic`) AS тем,
       (SELECT COUNT(*) FROM `agent_workflow_branch_topic`
         WHERE NULLIF(TRIM(IFNULL(`instructions`, '')), '') IS NOT NULL) AS тем_с_инструкцией,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE LOCATE('%topic_accept%', `metadata`) > 0
            OR LOCATE('%topic_direction%', `metadata`) > 0
            OR LOCATE('%topic_restrict%', `metadata`) > 0) AS осталось_со_старыми_метками;
