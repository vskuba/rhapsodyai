-- Анкета девушки, когда фактов о ней не нашлось (2026-09-23)
--
-- ЗАЧЕМ. То же, что `companion_bio` сделал для собеседника, только про неё саму.
--
-- Агент узнаёт о девушке из фактов в Qdrant — их придумывает `girl_fact_invent` и
-- накапливает от разговора к разговору. У новой анкеты их нет: документ пуст,
-- поиск возвращает пустоту, и девушка отвечает, не зная о себе ничего. А анкета у
-- нас есть — имя, возраст, город, рассказ о себе с сайта.
--
-- Переменная `girl_bio` подставляется **вместо** фактов, а не вместе с ними: два
-- источника об одном человеке расходятся, и модель возьмёт удобный фразе. Факты
-- свежее по устройству — их кладёт разговор.
--
-- ## ⚠⚠ Условие сложнее, чем у собеседника: поисков ДВА
--
-- Факты о собеседнике ищет один шаг. О девушке — два: сперва по тегам реплики
-- (позиция 7, `qdrant_fact_search_girl_tags`), не нашлось — откатом без тегов
-- (позиция 8, `qdrant_fact_search_girl`). Второй **пропускается**, когда сработал
-- первый.
--
-- ⚠⚠⚠ И на этом в промпте уже есть ошибка, которую эта миграция заодно чинит.
-- Условие блока стоит **только на обычном поиске**:
--
--     %if qdrant_fact_search_25_result_str%
--     === Информация о %agent_name% в базе данных ===
--     %qdrant_fact_search_25_result_str%%qdrant_fact_search_1529_result_str%
--     %endif%
--
-- Нашлось по тегам — шаг 25 не выполнялся, его переменная пуста, и блок скрыт
-- **целиком**, хотя факты найдены. То есть удачный поиск по тегам работал хуже
-- неудачного: при неудаче хотя бы откат показывал найденное.
--
-- Отсюда три ветки: обычный поиск → поиск по тегам → анкета. Проверено на
-- движке, все четыре исхода верны.
--
-- ⚠ Вложенность тройная, и это законно: `ai_workflow_if_blocks_render`
-- разворачивает блоки изнутри наружу в цикле.
--
-- ⚠ Номера шагов (25, 1529) в именах переменных — часть имени, а не ссылка:
-- движок так их и зовёт. Они одинаковы в обеих базах, потому что пришли из
-- одного дампа; заводись шаг заново, номер был бы другим.
--
-- ## ⚠⚠ Переменная НЕ заводится заново — она уже есть
--
-- `girl_bio` (id 265) живёт с `dating_girl_create`: «краткая биография, из неё
-- LLM соберёт факты». Смысл тот же самый, и источник тот же — `agent_bio(card)`
-- в DatingAi, который уже кладёт её при заведении агента.
--
-- Поэтому `INSERT` проходит вхолостую (`WHERE NOT EXISTS`), а работу делает
-- привязка к workflow 5. Завести вторую с тем же именем было бы хуже всего:
-- одно понятие в двух строках реестра расходится при первой же правке описания.
--
-- ⚠ Тип у неё уже `input`, умолчание — `NULL`. Не трогаем: сборка превращает
-- `None` в пустую строку сама (`ai_workflow_variables_defaults_apply`), а правка
-- общей переменной задела бы и `dating_girl_create`.
--
-- Идемпотентность: переменная — проверкой на наличие, промпт переписывается
-- только там, где новой ветки ещё нет.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'girl_bio') AS переменная_есть,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%girl_bio%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 12) AS есть_в_промпте;

-- ── Переменная ──────────────────────────────────────────────────────────────

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'girl_bio', 'input', '',
       'Анкета девушки одним текстом: имя, возраст, город, рассказ о себе. Кладёт DatingAi (agent_bio). Идёт в промпт, только если фактов о ней не нашлось ни одним из двух поисков'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'girl_bio');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'girl_bio'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ── Шаг 12: три ветки вместо одной ──────────────────────────────────────────

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(
           JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
           CONCAT(
             '%if qdrant_fact_search_25_result_str%\n',
             '=== Информация о %agent_name% в базе данных ===\n',
             '%qdrant_fact_search_25_result_str%%qdrant_fact_search_1529_result_str%\n',
             '%endif%'),
           CONCAT(
             '%if qdrant_fact_search_25_result_str%\n',
             '=== Информация о %agent_name% в базе данных ===\n',
             '%qdrant_fact_search_25_result_str%%qdrant_fact_search_1529_result_str%\n',
             '%else%%if qdrant_fact_search_1529_result_str%\n',
             '=== Информация о %agent_name% в базе данных ===\n',
             '%qdrant_fact_search_1529_result_str%\n',
             '%else%%if girl_bio%\n',
             '=== Твоя анкета на сайте знакомств ===\n',
             '⚠ Это то, что о тебе написано в профиле. Фактов о себе в базе пока нет — держись анкеты и не придумывай того, что ей противоречит.\n',
             '%girl_bio%\n',
             '%endif%%endif%%endif%')))
 WHERE `workflow_id` = @wf AND `position` = 12
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%girl_bio%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `type` FROM `agent_workflow_variable`
         WHERE `name` = 'girl_bio') AS тип,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%girl_bio%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 12) AS анкета_в_промпте,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%else%%if qdrant_fact_search_1529_result_str%%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 12) AS ветка_тегов;
