-- Ветка про фото: в `inputs_map` только объявленные входы (2026-09-27)
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека)
--
-- Правило: **`inputs_map` содержит ровно входящие переменные подпотока** — ни больше,
-- ни меньше. Сейчас у шага «Ветка: письма и фото» их восемь, а подпоток
-- `dating_talk_about_photo` объявляет входами две.
--
-- Разошлось это в обе стороны, и лечится тоже в обе:
--
--     передаём, а подпоток не использует:   girl_name, companion_name
--     используется, но не объявлено входом: prompt_user, companion_title,
--                                           user_language, datetime_current_get
--
-- ## ⚠⚠⚠ ОДНО БЕЗ ДРУГОГО ЛОМАЕТ
--
-- Обрежь `inputs_map` до двух объявленных — и три метки в промптах подпотока не
-- раскроются. Молча это не пройдёт: `ai_workflow_marks_check` бросит
-- `AiWorkflowMarkError` на первом же прогоне ветки. Поэтому объявление
-- расширяется **первым**, а лишнее убирается после.
--
-- ⚠ Проверено по метаданным подпотока: `photo_response`, `photo_deal`, `photo_fixed`
-- кладут его собственные шаги — их объявлять входами не надо.
--
-- ## ⚠⚠ Откуда взялись лишние: их положила миграция, а не редактор
--
-- Виджет `widget_workflow_invoke` спрашивает у подпотока его входы
-- (`/workflow/{id}/variables`, фильтр `type='input'`) и рисует **строку на каждый**;
-- собирает обратно только из нарисованных. Лишнего туда руками не положить.
--
-- А вот миграция `20260921100000_wf_dating_talk_about_photo` записала `JSON_OBJECT`
-- из семи пар вручную — включая `girl_name` и `companion_name`.
--
-- ⚠ Следствие, которое стоит знать: открой этот шаг в редакторе и тронь что-нибудь —
-- виджет молча перепишет карту, выкинув лишние. То есть беда самоисправляющаяся, но
-- в непредсказуемый момент, и до тех пор она держит **живой риск падения**: движок на
-- отсутствующую родительскую переменную отвечает `ValueError`, а не пропуском
-- (`ai_framework_manager`, сборка `child_scope`). В день, когда панель перестанет
-- слать `girl_name`, этот шаг уронил бы весь прогон — ради переменной, которая
-- подпотоку не нужна.
--
-- ## ⚠⚠⚠ `user_language` — НОВАЯ строка, а не смена типа у существующей
--
-- Человек попросил объявить её входом. Строка `user_language` уже есть, но с типом
-- `global`, и это **не украшение**: `_workflow_variables_protected` собирает имена
-- всех `global` и защищает их от восстановления из снимка `continue_workflow` —
-- значения таких переменных приносит каждый новый запрос, а не память прошлого.
--
-- Смени мы тип у той строки — `user_language` выпала бы из защиты **во всех**
-- workflow установки, и язык мог бы подтянуться из снимка вместо запроса. Поэтому
-- заводится отдельная строка с типом `input`, привязанная только к этому подпотоку;
-- прежняя `global` остаётся нетронутой, и защита с ней.
--
-- ⚠ Обе строки видны подпотоку: ручка переменных отдаёт связанные с workflow **плюс**
-- все `global`. Дубль имени здесь не новость — у `companion_title` строк три.
--
-- ## ⚠⚠ Номера не зашиты: базы разошлись
--
-- `dating_talk_about_photo` — 2044 локально и 74 на проде; `companion_title` строкой
-- 72 привязан к трём workflow на проде и к одному локально. Поэтому всё ищется
-- **по имени**, а строка переменной выбирается правилом: самая ранняя с типом
-- `input`, а нет такой — заводим. Правило детерминированное и на обеих базах даёт
-- одно и то же.
--
-- ⚠⚠ И поэтому же `inputs_map` **правится точечно** (`JSON_REMOVE`), а не пишется
-- заново: в нём лежит `datetime_current_get_45_result_str` локально и
-- `…_720_result_str` на проде — номер шага, свой у каждой базы. Перепиши мы карту
-- целиком, на одной из баз ссылка уехала бы в никуда.
--
-- Идемпотентность: строки заводятся через `WHERE NOT EXISTS`, привязка —
-- `INSERT IGNORE`, `JSON_REMOVE` несуществующего ключа ничего не делает.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM agent_workflow_variable v
          JOIN agent_workflow_variable_workflow vw ON vw.variable_id = v.id
          JOIN agent_workflow w ON w.id = vw.workflow_id
         WHERE w.name = 'dating_talk_about_photo' AND v.type = 'input')
         AS объявлено_входов,
       (SELECT JSON_LENGTH(JSON_EXTRACT(s.metadata, '$.workflow_invoke.inputs_map'))
          FROM agent_workflow_step s JOIN agent_workflow w ON w.id = s.workflow_id
         WHERE w.name = 'dating_talk' AND s.title = 'Ветка: письма и фото')
         AS передаём;

SET @photo = (SELECT id FROM agent_workflow WHERE name = 'dating_talk_about_photo');
SET @talk = (SELECT id FROM agent_workflow WHERE name = 'dating_talk');

-- ── 1. Недостающие входы: заводим строку, если её нет ────────────────────────
--
-- ⚠ `prompt_user` и `companion_title` уже существуют строками типа `input` — их не
-- трогаем и **не правим описания**: строки общие, и правка задела бы соседние
-- workflow. `user_language` и `datetime_current_get` заводятся впервые.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'user_language', 'input', NULL,
       'Язык переписки. ⚠ Отдельная строка от одноимённой global: та защищена от '
       'восстановления из снимка, и менять ей тип нельзя'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'user_language' AND `type` = 'input');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'datetime_current_get', 'input', NULL,
       'Текущее время строкой. Приходит из родителя результатом шага '
       '`datetime_current_get` — номер шага у каждой базы свой'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'datetime_current_get' AND `type` = 'input');

-- ── 2. Привязка к подпотоку ──────────────────────────────────────────────────
--
-- ⚠ Строка выбирается **самой ранней** среди одноимённых с типом `input`: у
-- `companion_title` их три, и «любая» означала бы разный выбор на разных базах.
INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT one.id, @photo FROM (
    SELECT MIN(`id`) AS id FROM `agent_workflow_variable`
     WHERE `name` = 'prompt_user' AND `type` = 'input'
    UNION ALL
    SELECT MIN(`id`) FROM `agent_workflow_variable`
     WHERE `name` = 'companion_title' AND `type` = 'input'
    UNION ALL
    SELECT MIN(`id`) FROM `agent_workflow_variable`
     WHERE `name` = 'user_language' AND `type` = 'input'
    UNION ALL
    SELECT MIN(`id`) FROM `agent_workflow_variable`
     WHERE `name` = 'datetime_current_get' AND `type` = 'input'
) one
 WHERE one.id IS NOT NULL AND @photo IS NOT NULL;

-- ── 3. Лишнее из карты вызова ────────────────────────────────────────────────
--
-- ⚠ Точечно двумя ключами, всё прочее остаётся как есть — см. ⚠⚠ про номера шагов.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REMOVE(`metadata`,
                                '$.workflow_invoke.inputs_map.girl_name',
                                '$.workflow_invoke.inputs_map.companion_name')
 WHERE `workflow_id` = @talk
   AND `title` = 'Ветка: письма и фото'
   AND @talk IS NOT NULL;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM agent_workflow_variable v
          JOIN agent_workflow_variable_workflow vw ON vw.variable_id = v.id
         WHERE vw.workflow_id = @photo AND v.type = 'input') AS объявлено_входов,
       (SELECT JSON_LENGTH(JSON_EXTRACT(s.metadata, '$.workflow_invoke.inputs_map'))
          FROM agent_workflow_step s
         WHERE s.workflow_id = @talk AND s.title = 'Ветка: письма и фото')
         AS передаём;

-- ⚠⚠ Сверка по существу: имена в карте и объявленные входы обязаны совпасть.
-- «Шесть и шесть» — ещё не «те же шесть».
SELECT 'сверка имён' AS проверка,
       (SELECT GROUP_CONCAT(v.name ORDER BY v.name SEPARATOR ', ')
          FROM agent_workflow_variable v
          JOIN agent_workflow_variable_workflow vw ON vw.variable_id = v.id
         WHERE vw.workflow_id = @photo AND v.type = 'input') AS объявлено,
       (SELECT GROUP_CONCAT(one.k ORDER BY one.k SEPARATOR ', ') FROM (
           SELECT JSON_UNQUOTE(JSON_EXTRACT(
                      JSON_KEYS(JSON_EXTRACT(s.metadata,
                                             '$.workflow_invoke.inputs_map')),
                      CONCAT('$[', n.i, ']'))) AS k
             FROM agent_workflow_step s
             JOIN (SELECT 0 AS i UNION ALL SELECT 1 UNION ALL SELECT 2
                   UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
                   UNION ALL SELECT 6 UNION ALL SELECT 7) n
            WHERE s.workflow_id = @talk AND s.title = 'Ветка: письма и фото'
              AND n.i < JSON_LENGTH(JSON_EXTRACT(s.metadata,
                                                 '$.workflow_invoke.inputs_map'))
       ) one) AS передаём;

-- ⚠ И отдельно то, ради чего всё затевалось: мёртвых передач не осталось.
SELECT 'мёртвые передачи' AS проверка,
       JSON_CONTAINS_PATH(s.metadata, 'one',
                          '$.workflow_invoke.inputs_map.girl_name',
                          '$.workflow_invoke.inputs_map.companion_name') AS остались
  FROM agent_workflow_step s
 WHERE s.workflow_id = @talk AND s.title = 'Ветка: письма и фото';
