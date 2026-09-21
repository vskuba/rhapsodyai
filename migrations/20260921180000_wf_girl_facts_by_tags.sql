-- Факты девушки ищутся сперва по тегам, без тегов — только если не нашлось
-- (2026-09-21)
--
-- ЗАЧЕМ. «Анализ сообщения» размечает реплику тегами (`prompt_user_tags`:
-- «travel,location,london»), и поиск фактов СОБЕСЕДНИКА и РАЗГОВОРА ими
-- пользуется. Поиск фактов самой девушки — нет: её фильтр собирался как
-- `{"document_id":"…"}`, без тегов вовсе. Замечено на прогоне #30393.
--
-- ⚠ ОДНИМ ПОИСКОМ НЕ РЕШАЕТСЯ. Инструмент теги умеет, но `tags` — поле `must`:
-- указал — и факты без этих тегов не найдутся вовсе. «С тегами и без» в одном
-- вызове не совместить, нужен второй шаг.
--
-- КАК УСТРОЕНО. Новый шаг встаёт ПЕРЕД прежним и ищет с тегами. Дальше решают
-- переходы, и порядок у них значащий — движок берёт первое совпавшее условие:
--
--   1. ничего не нашлось   → шаг 25 (прежний поиск, без тегов);
--   2. это вопрос о девушке → шаг 48 (сочинить факт), как было;
--   3. иначе                → шаг 38 (факты собеседника), минуя бестеговый поиск.
--
-- ⚠⚠ ПОЧЕМУ «ПУСТО» ПРОВЕРЯЕТСЯ ПЕРВЫМ. Поставь мы вопрос выше — и на вопросе о
-- девушке бестеговый поиск не отработал бы никогда: поток ушёл бы сочинять факт,
-- имея на руках пустоту. Сейчас откат случается и на этом пути.
--
-- ⚠⚠ ПОЧЕМУ ГЕНЕРАЦИЯ ЧИТАЕТ ДВЕ ПЕРЕМЕННЫЕ, А НЕ ОДНУ. Инструмент кладёт ответ
-- в имя, собранное из НОМЕРА ШАГА (`qdrant_fact_search_25_result_str`), и перебить
-- это через `outputs_map` нельзя: движок применяет карту только к результату-словарю,
-- а `qdrant_fact_search` возвращает строку — для строк карта молча игнорируется.
-- (Оттого и `outputs_map` у шага 25 мёртв: `qdrant_fact_search_result_girl` никто
-- не заполняет и никто не читает.) Чинить движок здесь нельзя: таких мёртвых карт
-- тринадцать в шести workflow, включая `agent_name` в заведении анкет, — оживут
-- все разом.
--
-- Поэтому оба поиска пишут каждый в своё имя, а «Генерация ответа» читает оба
-- подряд. Это безопасно: шаги взаимоисключающие — отработал один, второй пропущен,
-- и пустая переменная в тексте ничего не добавляет.
--
-- ⚠ ПРОВЕРКУ «ЭТО ВОПРОС» НА ШАГ 38 ПЕРЕНОСИТЬ НЕЛЬЗЯ, хотя туда сходятся обе
-- дороги: шаг 97 возвращается на 38 после сочинения факта, а `prompt_user_question`
-- никто не сбрасывает — поток ушёл бы сочинять по кругу.
--
-- ⚠ ШАГ 97 НЕ ПРАВИТСЯ. Он дописывает сочинённый факт в переменную шага 25, а
-- генерация читает её же вместе с новой: на вопросе о девушке поток либо прошёл
-- через 25 (и там лежит найденное), либо пришёл от нового шага (и найденное лежит
-- в новой переменной). Оба случая видны генерации целиком.
--
-- Идемпотентность: заведение — под флагом `@done`, прочее — `NOT EXISTS`/`REPLACE`.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @step_vars = (SELECT `id` FROM `agent_workflow_step`
                   WHERE `workflow_id` = @wf AND `title` = 'Переменные');
SET @step_gen = (SELECT `id` FROM `agent_workflow_step`
                  WHERE `workflow_id` = @wf AND `title` = 'Генерация ответа');
SET @done = (SELECT COUNT(*) FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'qdrant_fact_search_girl_tags');

SELECT 'ДО' AS этап, @wf AS workflow, @done AS уже_заведено,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ── 1. Переменная фильтра с тегами ──────────────────────────────────────────
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'fact_collection_girl_filter_tags', 'workflow', NULL,
       'Фильтр фактов девушки с тегами реплики; не нашлось — откат к поиску без тегов'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'fact_collection_girl_filter_tags');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'fact_collection_girl_filter_tags'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ── 2. Шаг «Переменные» собирает её рядом с прочими ─────────────────────────
-- ⚠ В конец списка: он читается по порядку, и `%girl_id%` с `%prompt_user_tags%`
-- к этому моменту уже известны.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_ARRAY_APPEND(`metadata`, '$.variable_conversion',
       JSON_OBJECT('variable', 'fact_collection_girl_filter_tags',
                   'text', '{"document_id":"%girl_id%","tags":"%prompt_user_tags%"}'))
 WHERE `id` = @step_vars
   AND JSON_SEARCH(`metadata`, 'one', 'fact_collection_girl_filter_tags') IS NULL;

-- ⚠⚠ И ПУСТОЕ УМОЛЧАНИЕ ПЕРЕМЕННОЙ ШАГА 25. Прежде он отрабатывал всегда, и его
-- переменная существовала к моменту генерации сама собой. Теперь его можно
-- пропустить — и переменной не будет вовсе, а сторож меток (`ai_workflow_marks_check`)
-- роняет шаг, когда метка осталась без значения. Найдено живым прогоном: поиск по
-- тегам нашёл факт, бестеговый был пропущен, и «Генерация ответа» отказала.
--
-- ⚠ Пустая строка сторожа устраивает — он ловит ОТСУТСТВИЕ, а не пустоту. Шаг 25,
-- если отработает, перезапишет её своим ответом.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_ARRAY_APPEND(`metadata`, '$.variable_conversion',
       JSON_OBJECT('variable', 'qdrant_fact_search_25_result_str', 'text', ''))
 WHERE `id` = @step_vars
   AND JSON_SEARCH(`metadata`, 'one', 'qdrant_fact_search_25_result_str') IS NULL;

-- ── 3. Место под новый шаг ──────────────────────────────────────────────────
UPDATE `agent_workflow_step` SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= 7 AND @done = 0;

-- ── 4. Сам шаг ──────────────────────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, 3, 'qdrant_fact_search_girl_tags', 7, '{"tool_invoke": {"tool_name": "qdrant_fact_search", "inputs_map": {"limit": "fact_collection_limit", "query_text": "search_query", "collection_name": "fact_collection_girl_name", "metadata_filter": "fact_collection_girl_filter_tags"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [{"variable": "qdrant_fact_search___SELF___result_str", "operator": "empty", "value": "", "step_id": "25"}, {"variable": "prompt_user_question", "operator": "==", "value": "1", "step_id": "48"}, {"variable": "qdrant_fact_search___SELF___result_str", "operator": "!=", "value": "", "step_id": "38"}]}'
  FROM DUAL WHERE @done = 0;

-- ⚠ Номер шага известен только теперь, а имя его переменной из него и собрано.
SET @new = (SELECT `id` FROM `agent_workflow_step`
             WHERE `workflow_id` = @wf AND `title` = 'qdrant_fact_search_girl_tags');
SET @new_var = CONCAT('qdrant_fact_search_', @new, '_result_str');

UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(`metadata`, 'qdrant_fact_search___SELF___result_str',
                            @new_var)
 WHERE `id` = @new;

-- ── 5. Генерация читает обе переменные ──────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
       REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
               '%qdrant_fact_search_25_result_str%',
               CONCAT('%qdrant_fact_search_25_result_str%%', @new_var, '%')))
 WHERE `id` = @step_gen
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE CONCAT('%', @new_var, '%');

SELECT 'ПОСЛЕ' AS этап, @new AS новый_шаг, @new_var AS его_переменная,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE CONCAT('%', @new_var, '%')
          FROM `agent_workflow_step` WHERE `id` = @step_gen) AS генерация_читает,
       (SELECT `metadata` LIKE '%__SELF__%'
          FROM `agent_workflow_step` WHERE `id` = @new) AS остался_placeholder;

SELECT `position` AS поз, `id`, `title` AS шаг
  FROM `agent_workflow_step` WHERE `workflow_id` = @wf ORDER BY `position`;
