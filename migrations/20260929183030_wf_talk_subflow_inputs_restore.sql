-- Подпоткам `dating_talk` возвращаются входы, потерянные правкой в админке
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека: «передавать через inputs_map»)
--
-- Продолжение `20260929182043`, где `girl_fact_invent` получил обратно
-- `prompt_user`. Здесь — остальное, что потерялось тем же случаем.
--
-- ## Что случилось, по трассе прода
--
-- 28.09.2026 между 20:46 и 21:02 шаги `companion_fact_extract` (id 722) и
-- `girl_fact_create` (id 721) workflow `dating_talk` были переписаны **руками в
-- админке**: миграций в этом окне нет ни одной (`_yoyo_migration`), а
-- `inputs_map` у обоих похудел. Видно по `metadata_rendered` трассы — она хранит
-- вход шага на момент прогона:
--
--     20:46 шаг 722: user_id, user_name, companion_name, companion_title,
--                    prompt_user_facts_talk, prompt_user_facts_companion
--     21:02 шаг 722: user_name, companion_name, companion_title
--
--     20:46 шаг 721: girl_id, user_id, girl_name, girl_title, prompt_user,
--                    companion_title
--     позже шаг 721: girl_id, girl_name, girl_title, companion_title
--
-- ⚠ Часть правки была осмысленной и остаётся: `user_name` теперь берётся из
-- `girl_unique_id`, а не из `agent_name`, `girl_name` — из `girl_bio`. Эти
-- переименования не трогаем, возвращаем только **пропавшие** ключи.
--
-- ## Чем это оплачено
--
-- | Что сломалось | Как проявилось |
-- |---------------|----------------|
-- | `girl_fact_invent` без `prompt_user` | факты «по вопросу» сочинялись без вопроса, а прогон `dating_talk` обрывался на `qdrant_fact_search` |
-- | `companion_fact_extract` без `prompt_user_facts_*` | условие «фактов нет — запись обойти» (`== 0`) не срабатывало никогда: в Qdrant уходила пустота на каждой реплике «ок» |
-- | оба подпотока без `user_id` | шаги `fact_collection_add_*` пользуются `%user_id%`, а он не приезжал |
--
-- ⚠⚠ До 29.09 три из этих четырёх дыр закрывала случайность: у глобальных
-- `prompt_user` и `user_id` сохранились связи с workflow 6 и 7, а прежний
-- `ai_workflow_load` не фильтровал по типу и отдавал их подпотоку. Помогало это
-- слабо — `default` у глобальных `NULL`, то есть приезжала пустота, — но падало
-- иначе. `20260929003100` связи убрал, и дыры стали видны словами: «в промпте
-- шага остались метки без значения».
--
-- Идемпотентность: каждый ключ дописывается только если его нет
-- (`JSON_EXTRACT(...) IS NULL`). `JSON_VALID` обязателен — у части шагов
-- `metadata` не JSON, и `JSON_EXTRACT` на них обрывает миграцию.

-- ── 0. Что было ───────────────────────────────────────────────────────────────

SET @talk := (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @invent := (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_fact_invent');
SET @extract := (SELECT `id` FROM `agent_workflow` WHERE `name` = 'companion_fact_extract');

SET @step_invent := (
    SELECT s.`id` FROM `agent_workflow_step` s
     WHERE s.`workflow_id` = @talk AND JSON_VALID(s.`metadata`)
       AND JSON_EXTRACT(s.`metadata`, '$.workflow_invoke.workflow_id') = @invent
     LIMIT 1);

SET @step_extract := (
    SELECT s.`id` FROM `agent_workflow_step` s
     WHERE s.`workflow_id` = @talk AND JSON_VALID(s.`metadata`)
       AND JSON_EXTRACT(s.`metadata`, '$.workflow_invoke.workflow_id') = @extract
     LIMIT 1);

SELECT 'ДО' AS этап, @step_invent AS шаг_выдумывания, @step_extract AS шаг_сохранения,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step_invent) AS входы_выдумывания,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step_extract) AS входы_сохранения;

-- ── 1. Выдумывание фактов: `user_id` ──────────────────────────────────────────

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.workflow_invoke.inputs_map.user_id', 'user_id')
 WHERE `id` = @step_invent AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map.user_id') IS NULL;

-- ── 2. Сохранение фактов: `user_id` и два признака «есть ли что писать» ────────

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.workflow_invoke.inputs_map.user_id', 'user_id')
 WHERE `id` = @step_extract AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map.user_id') IS NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
           '$.workflow_invoke.inputs_map.prompt_user_facts_companion',
           'prompt_user_facts_companion')
 WHERE `id` = @step_extract AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`,
           '$.workflow_invoke.inputs_map.prompt_user_facts_companion') IS NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
           '$.workflow_invoke.inputs_map.prompt_user_facts_talk',
           'prompt_user_facts_talk')
 WHERE `id` = @step_extract AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`,
           '$.workflow_invoke.inputs_map.prompt_user_facts_talk') IS NULL;

-- ── 3. Что стало ──────────────────────────────────────────────────────────────
--
-- У шага выдумывания обязаны быть `prompt_user` и `user_id`, у шага сохранения —
-- `user_id` и оба `prompt_user_facts_*`.

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step_invent) AS входы_выдумывания,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map')
          FROM `agent_workflow_step` WHERE `id` = @step_extract) AS входы_сохранения;
