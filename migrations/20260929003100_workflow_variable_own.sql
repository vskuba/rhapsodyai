-- У переменной workflow появляется владелец: `agent_workflow_variable.workflow_id`
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека)
--
-- Правило: **входящие переменные у каждого workflow свои**. Родитель и подпоток
-- общаются только контрактом — `inputs_map` шага `workflow_invoke` и объявленные
-- `input`-переменные ребёнка. Общих записей между ними быть не должно.
--
-- Сейчас не так. Реестр `agent_workflow_variable` хранит строку, а
-- `agent_workflow_variable_workflow` привязывает её к скольким угодно workflow.
-- `girl_name` (строка 89) привязана и к `dating_talk`, и к подпотоку
-- `girl_fact_invent`: переименуй её в одном — переименуется в обоих. Удаление и
-- вовсе сносит строку целиком, то есть у всех сразу.
--
-- ⚠ Сам движок при этом **уже изолирован**: `ai_workflow_load` и
-- `ai_workflow_variables_input_get` берут переменные строго по связи с одним
-- workflow, а `workflow_invoke` собирает ребёнку чистый scope. Течёт только
-- реестр — то есть редактор и всё, что правит записи.
--
-- ## Что делаем
--
-- Связь M:N заменяется владением: у переменной появляется `workflow_id`, и он
-- один. `NULL` — ровно у `type='global'` (13 системных строк: `prompt_user`,
-- `user_id`, `session_uuid` и прочие, которые приносит каждый запрос).
--
-- Уникальность `(workflow_id, name)` — внутри workflow имя одно. Проверено на
-- данных перед написанием: конфликтов нет ни одного, разбирать завалы не
-- придётся.
--
-- ## ⚠⚠ Строки размножаются, и это и есть починка
--
-- Переменная, привязанная к трём workflow, станет тремя строками с одинаковым
-- именем и умолчанием. Локально таких 51 (`planning_project_id` — на 18
-- workflow), и после разбора реестр вырастет примерно на сотню записей.
--
-- Это не раздувание, а цена изоляции: именно общая строка и была бедой. Первый
-- по номеру workflow занимает исходную запись — так у переменной сохраняется её
-- прежний `id`, а значит и ссылки из открытых вкладок редактора.
--
-- ## ⚠⚠ Сироты удаляются (указание человека)
--
-- Строки типа `input`/`workflow` без единой связи не читает **ни один** запрос:
-- и движок, и редактор, и экспорт спрашивают переменные через связь. Локально их
-- 98 — остатки удалённых workflow: связи при удалении снимал `CASCADE`, а сами
-- записи оставались. С появлением внешнего ключа такое больше не накопится —
-- удаление workflow уносит его переменные.
--
-- ## ⚠⚠ Глобальные владельца не получают, хотя связи у них бывают
--
-- `type='global'` — переменная установки: движок отдаёт **все** глобальные
-- каждому workflow (`ai_workflow_variables_global_get`), владельца у неё нет и
-- быть не может. Связи у четырёх глобальных прода тем не менее есть — их
-- наставила старая точка `POST /workflow/{id}/variable`, которая вешала связь
-- на что угодно, включая `global`. На работу движка они не влияли никак.
--
-- ⚠ Проверено репетицией на копии прода: без этой оговорки четыре глобальные
-- получали бы владельца, а с ним и `ON DELETE CASCADE` — удаление одного
-- workflow сносило бы `prompt_user` **всей установке**. Локально этого не
-- видно: там связей у глобальных нет ни одной.
--
-- ## ⚠ Порядок внутри файла обязателен
--
-- Владельца сперва получают те, у кого связь одна (и первая из нескольких), и
-- только потом размножаются остальные: шаг размножения отличает «уже разобранную»
-- связь от оставшейся сравнением `l.workflow_id <> v.workflow_id`. Поменяй шаги
-- местами — сравнивать будет не с чем, и строки задвоятся.
--
-- Идемпотентность: `ADD COLUMN IF NOT EXISTS` MySQL не поддерживает, поэтому
-- через `information_schema` и `PREPARE` — тем же приёмом, что в `20260903100320`.
-- Шаги переноса данных висят на признаке «таблица связей ещё жива»: второй заход
-- по разобранным данным ничего не меняет — владелец уже стоит, размножать нечего,
-- сирот нет.
--
-- ## ⚠⚠ Таблицу связей эта миграция НЕ удаляет — и это не забывчивость
--
-- Удалять её здесь нельзя: миграции накатывает **новый** контейнер uvicorn при
-- старте, а трафик в это время держит **старый** слот, и `telegram` с
-- `worker_task` деплой перезапускает уже после переключения
-- (`.claude/docs/deploy.md`, «Что ещё перезапускается»). Старый код спрашивает
-- переменные через `JOIN agent_workflow_variable_workflow` — в том числе
-- `ai_workflow_load`, то есть **каждый** прогон workflow. Снеси таблицу в этой
-- же выкладке, и от наката до перезапуска телеграма (минуты, не секунды) любой
-- запрос к агенту падает с «Table doesn't exist».
--
-- Поэтому расширение и сужение разнесены по двум выкладкам:
--
-- | Выкладка | Что происходит |
-- |----------|----------------|
-- | эта      | появляется `workflow_id`, данные разбираются, **связи остаются** |
-- | следующая | `20260929134932_workflow_variable_link_drop.sql` убирает таблицу |
--
-- ⚠ В промежутке обе картины живы и обе верны: старый код читает связи (их
-- никто не менял), новый — колонку. Размноженные строки старый код не видит
-- (связей у них нет), и его собственные записи новый код не замечает — но
-- промежуток длится одну выкладку, а править переменные в эту минуту некому.
--
-- ⚠⚠ Вторая миграция **не должна** уехать в том же коммите: yoyo применяет
-- всё, что лежит в папке, и порядок имён от этого не спасает.

-- ── 0. Что было ───────────────────────────────────────────────────────────────
--
-- ⚠ Колонки `workflow_id` здесь ещё может не быть, поэтому замер только по тому,
-- что есть на любой базе: сама таблица переменных.

SELECT 'ДО' AS этап,
       COUNT(*) AS переменных,
       SUM(`type` = 'global') AS глобальных,
       SUM(`type` <> 'global') AS своих_у_workflow
  FROM `agent_workflow_variable`;

-- ── 1. Колонка владельца ──────────────────────────────────────────────────────

SET @has_column := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_variable'
       AND COLUMN_NAME = 'workflow_id'
);

SET @sql := IF(@has_column = 0,
    'ALTER TABLE `agent_workflow_variable`
        ADD COLUMN `workflow_id` INT NULL DEFAULT NULL
            COMMENT ''Владелец переменной. NULL — только у type=global''
            AFTER `id`',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 2. Первая связь переезжает в исходную строку ──────────────────────────────

SET @has_link := (
    SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_variable_workflow'
);

SET @sql := IF(@has_link = 1,
    'UPDATE `agent_workflow_variable` v
       JOIN (SELECT `variable_id`, MIN(`workflow_id`) AS `workflow_id`
               FROM `agent_workflow_variable_workflow`
              GROUP BY `variable_id`) o
         ON o.`variable_id` = v.`id`
        SET v.`workflow_id` = o.`workflow_id`
      WHERE v.`workflow_id` IS NULL AND v.`type` <> ''global''',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 3. Остальные связи становятся своими строками ─────────────────────────────

-- ⚠ `LEFT JOIN … IS NULL` — не украшение, а страховка от второго прогона.
-- Таблица связей после этой миграции жива (шапка, «расширение и сужение»), и
-- признак `@has_link` её больше не отсекает: без проверки «такая пара уже есть»
-- повторный накат попытался бы вставить те же строки снова и упал бы на
-- `uq_workflow_variable_name`.

SET @sql := IF(@has_link = 1,
    'INSERT INTO `agent_workflow_variable`
            (`workflow_id`, `name`, `type`, `default`, `description`)
     SELECT l.`workflow_id`, v.`name`, v.`type`, v.`default`, v.`description`
       FROM `agent_workflow_variable_workflow` l
       JOIN `agent_workflow_variable` v ON v.`id` = l.`variable_id`
       LEFT JOIN `agent_workflow_variable` e
              ON e.`workflow_id` = l.`workflow_id` AND e.`name` = v.`name`
      WHERE l.`workflow_id` <> v.`workflow_id` AND v.`type` <> ''global''
        AND e.`id` IS NULL',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 4. Сироты: тип не global, владельца нет, читателей тоже ───────────────────

SET @sql := IF(@has_link = 1,
    'DELETE FROM `agent_workflow_variable`
      WHERE `type` <> ''global'' AND `workflow_id` IS NULL',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 5. Ключ владения и уникальность имени внутри workflow ─────────────────────

SET @has_index := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_variable'
       AND INDEX_NAME = 'uq_workflow_variable_name'
);

SET @sql := IF(@has_index = 0,
    'ALTER TABLE `agent_workflow_variable`
        ADD UNIQUE KEY `uq_workflow_variable_name` (`workflow_id`, `name`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_fk := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_variable'
       AND CONSTRAINT_NAME = 'fk_workflow_variable_workflow'
);

SET @sql := IF(@has_fk = 0,
    'ALTER TABLE `agent_workflow_variable`
        ADD CONSTRAINT `fk_workflow_variable_workflow`
            FOREIGN KEY (`workflow_id`) REFERENCES `agent_workflow` (`id`)
            ON DELETE CASCADE',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 6. Таблица связей остаётся жить до следующей выкладки ─────────────────────
--
-- Её удаление и вычистку имени из `seed_table_config` несёт
-- `20260929134932_workflow_variable_link_drop.sql` — причина в шапке.

-- ── 7. Что стало ──────────────────────────────────────────────────────────────
--
-- `без_владельца` обязан быть нулём: непустое значение значит, что строку не
-- подобрала ни связь, ни удаление сирот, — и её `NULL` теперь ничей.

SELECT 'ПОСЛЕ' AS этап,
       COUNT(*) AS переменных,
       SUM(`workflow_id` IS NOT NULL) AS с_владельцем,
       SUM(`type` = 'global') AS глобальных_без_владельца,
       SUM(`workflow_id` IS NULL AND `type` <> 'global') AS без_владельца,
       @has_link AS таблица_связей_жива
  FROM `agent_workflow_variable`;
