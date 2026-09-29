-- Подпоток `girl_fact_invent` получает вопрос собеседника: `prompt_user` в контракте
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека)
--
-- Шаг «Новый факты» подпотока `girl_fact_invent` пользуется в промпте меткой
-- `%prompt_user%`, а родитель `dating_talk` её не передавал: в `inputs_map` шага
-- `girl_fact_create` (позиция 35) стояли только `girl_id`, `girl_name`,
-- `girl_title` и `companion_title`. Метка оставалась без значения, и движок
-- отказывал: «в промпте шага „Новый факты“ остались метки без значения».
--
-- ⚠ Раньше отказа не было, но и вопроса не было тоже. У глобальной `prompt_user`
-- сохранилась связь с этим workflow — её наставила старая точка
-- `POST /workflow/{id}/variable`, — а прежний `ai_workflow_load` не фильтровал по
-- типу и отдавал глобальную подпотоку вместе с её `default`. `default` у неё
-- `NULL`, поэтому подпоток получал пустоту: метка подставлялась пустой строкой,
-- шаг проходил, а дальше пустота доезжала до `qdrant_fact_search` и роняла
-- прогон целиком (`TextEncodeInput must be Union[…]`, 99 попаданий в журнале
-- ошибок с 26.09). То есть факты «по вопросу» сочинялись **без вопроса**.
--
-- Теперь вопрос передаётся честно — контрактом входа, как и остальные четыре
-- переменные этого же шага.
--
-- ## Что делаем, по образцу соседей
--
-- У четырёх переменных, которые родитель уже передаёт, ровно две записи на
-- каждую: строка в `inputs_map` шага и своя `input`-переменная у ребёнка. Пятая
-- заводится так же:
--
-- | Где | Что добавляется |
-- |-----|-----------------|
-- | `inputs_map` шага `girl_fact_create` | `"prompt_user": "prompt_user"` |
-- | реестр переменных workflow `girl_fact_invent` | `prompt_user`, тип `input` |
--
-- ⚠ Имя совпадает с глобальной, и это не конфликт: у глобальной владельца нет
-- (`workflow_id IS NULL`), а `UNIQUE (workflow_id, name)` считает пару. Так уже
-- живут `prompt_user` у workflow 74 и `user_id` у workflow 14.
--
-- ⚠⚠ Шаг ищется по **имени** родителя и ребёнка, а не по номерам: номера
-- одинаковы на этой установке и на проде, но полагаться на это в миграции незачем.
-- `JSON_VALID` обязателен: у части шагов `metadata` не JSON, и `JSON_EXTRACT` на
-- них падает, обрывая миграцию на середине.

-- ── 0. Что было ───────────────────────────────────────────────────────────────

SET @child := (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_fact_invent');
SET @parent := (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SET @step := (
    SELECT s.`id` FROM `agent_workflow_step` s
     WHERE s.`workflow_id` = @parent
       AND JSON_VALID(s.`metadata`)
       AND JSON_EXTRACT(s.`metadata`, '$.workflow_invoke.workflow_id') = @child
     LIMIT 1
);

SELECT 'ДО' AS этап, @parent AS родитель, @child AS подпоток, @step AS шаг,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step) AS входы,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `workflow_id` = @child AND `name` = 'prompt_user') AS переменная_есть;

-- ── 1. Вопрос собеседника в контракте входа ───────────────────────────────────

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
           '$.workflow_invoke.inputs_map.prompt_user', 'prompt_user')
 WHERE `id` = @step
   AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map.prompt_user') IS NULL;

-- ── 2. Объявленная входящая переменная у ребёнка ───────────────────────────────
--
-- ⚠ `default` оставляем `NULL`, как у соседних четырёх: значение приходит входом,
-- а умолчание у обязательного входа обещало бы, что без него можно обойтись.

-- ⚠ `FROM DUAL` — не украшение: `WHERE` без `FROM` MySQL не разбирает вовсе.

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `description`)
SELECT @child, 'prompt_user', 'input',
       'Вопрос собеседника: по нему шаг «Новый факты» сочиняет факты о девушке'
  FROM DUAL
 WHERE @child IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `workflow_id` = @child AND `name` = 'prompt_user');

-- ── 3. Что стало ──────────────────────────────────────────────────────────────
--
-- `входы` обязаны содержать `prompt_user`, `переменная_есть` — единицу.

SELECT 'ПОСЛЕ' AS этап, @step AS шаг,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step) AS входы,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `workflow_id` = @child AND `name` = 'prompt_user') AS переменная_есть;
