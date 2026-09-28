-- Тестер workflow обзавёлся своим собеседником: `test_companion_*` вместо чужой
-- троицы `companion_*` (2026-09-28)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `remove_companion` убрал подстановку `companion_id/name/title` из
-- `ai_workflow_variables_base`: теперь троицу присылает тот, кто зовёт агента.
-- Читателям, которых зовут запросом, её объявили входящей — детективу это сделала
-- `20260927214531`. А `workflow_shell_test` (id 9) остался ни с чем: он читает
-- троицу в трёх местах, но объявления не имеет, и её ему никто не шлёт.
--
-- ⚠ Объявить входящей его тоже было бы **неправильно**. Собеседника тестера
-- играет LLM внутри самого прогона — это его собственное действующее лицо, а не
-- данные вызывающего. Зовут тестер из админ-чата, и требовать от страницы знать
-- про собеседников значило бы тащить чужой поддомен в пульт разработчика.
--
-- Поэтому троица становится **своей**, по образцу соседней `target_agent_*`
-- (id/name/title с умолчаниями), которая описывает агента под тестом. Симметрия
-- полная: `target_agent_*` — кого тестируем, `test_companion_*` — кем
-- прикидываемся.
--
-- ## Три места, где она читается
--
--   * шаг 67 «Сообщение тестера» — промпт «играешь роль собеседника по имени …»;
--   * шаг 71 «Обновить контекст» — строка стенограммы `[имя]: сообщение`;
--   * шаг 68 «Вызов тестируемого workflow» — `inputs_map` прокидывает троицу в
--     дочерний workflow. ⚠ Это место легко пропустить: там не метки `%…%`, а
--     ключи отображения, и поиском по `%companion` оно не находится. Без него
--     `dating_talk` под тестером собирал бы ключ фактов
--     `%companion_id%_%companion_name%` из пустоты.
--
-- ## Собеседник тестов — отдельная запись, а не боевая
--
-- `test_llm_companion` / `Gerard` — та самая запись, которую заводила фикстура
-- `tests_llm/conftest.py` до `remove_companion`. Довод оттуда остаётся в силе:
-- факты разговора ложатся в Qdrant под ключ собеседника, и гонять тестер под
-- боевым `dating_person` значило бы засорять живой документ.
--
-- ⚠ Номер строки у каждой установки свой, поэтому умолчание `test_companion_id`
-- вычисляется здесь, а не пишется литералом.

-- ⚠ Считаем именно **чужую** троицу, а не любое упоминание собеседника: после
-- правки в шагах стоит `test_companion_*`, и счётчик по `%companion%` показывал
-- бы те же три шага — проверка, которая всегда зелёная, не проверка.
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` LIKE 'test_companion_%') AS переменных,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = 9
           AND (`metadata` LIKE '%\%companion_id\%%'
             OR `metadata` LIKE '%\%companion_name\%%'
             OR `metadata` LIKE '%\%companion_title\%%'
             OR `metadata` LIKE '%"companion_id":"companion_id"%'
             OR `metadata` LIKE '%"companion_name":"companion_name"%'
             OR `metadata` LIKE '%"companion_title":"companion_title"%')) AS шагов_с_чужой_троицей;

-- ------------------------------------------- Собеседник тестов в реестре
INSERT INTO `companion` (`unique_id`, `title`)
SELECT 'test_llm_companion', 'Gerard'
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `companion`) c
                    WHERE c.`unique_id` = 'test_llm_companion');

SET @cid := (SELECT `id` FROM `companion` WHERE `unique_id` = 'test_llm_companion');

-- ------------------------------------------- Три переменные тестера
--
-- Тип `workflow`, а не `input`: значение не приходит снаружи, его знает сам
-- тестер. Тем же типом объявлены соседние `target_agent_*`.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'test_companion_id', 'workflow',
       'Номер собеседника, которым тестер представляется тестируемому workflow',
       CAST(@cid AS CHAR)
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) v
                    WHERE v.`name` = 'test_companion_id');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'test_companion_name', 'workflow',
       'Ключ записи собеседника тестов (companion.unique_id)',
       'test_llm_companion'
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) v
                    WHERE v.`name` = 'test_companion_name');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'test_companion_title', 'workflow',
       'Как зовут собеседника, которого играет тестер: промпт и стенограмма',
       'Gerard'
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) v
                    WHERE v.`name` = 'test_companion_title');

-- ------------------------------------------- Связь с workflow 9
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, 9 FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('test_companion_id', 'test_companion_name', 'test_companion_title')
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = 9);

-- ------------------------------------------- Шаги переходят на свою троицу
--
-- ⚠ Замена по подстроке, а не переписывание метаданных целиком: в шагах лежит
-- JSON с промптами на несколько абзацев, и восстановление «как было» рядом с
-- правкой соседней миграции уже отменяло чужие изменения (см. `…100000`).
UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(`metadata`, '%companion_title%', '%test_companion_title%')
 WHERE `id` IN (67, 71) AND `metadata` LIKE '%\%companion_title\%%';

-- ⚠ Ключ слева — имя переменной у **дочернего** workflow, справа — у тестера.
-- Меняется только правая часть: договор дочернего не трогаем.
UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(REPLACE(REPLACE(`metadata`,
           '"companion_id":"companion_id"', '"companion_id":"test_companion_id"'),
           '"companion_title":"companion_title"', '"companion_title":"test_companion_title"'),
           '"companion_name":"companion_name"', '"companion_name":"test_companion_name"')
 WHERE `id` = 68;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` LIKE 'test_companion_%') AS переменных,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE v.`name` LIKE 'test_companion_%' AND x.`workflow_id` = 9) AS связей,
       -- Чужой троицы в шагах тестера остаться не должно ни одной.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = 9
           AND (`metadata` LIKE '%\%companion_id\%%'
             OR `metadata` LIKE '%\%companion_name\%%'
             OR `metadata` LIKE '%\%companion_title\%%'
             OR `metadata` LIKE '%"companion_id":"companion_id"%'
             OR `metadata` LIKE '%"companion_name":"companion_name"%'
             OR `metadata` LIKE '%"companion_title":"companion_title"%')) AS осталось_чужого;
