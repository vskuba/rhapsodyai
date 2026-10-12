-- Нода DATING: переменная `girl_title` без префикса затирала входящую (2026-10-12)
--
-- ## ⚠⚠ ЧТО СЛОМАЛОСЬ
--
-- `dating_talk` объявляет `girl_title` входящей (`…_wf_talk_girl_title.sql`), и
-- панель её шлёт: `agent_vars` в DatingAi отдаёт «Elena». До агента доезжала
-- **пустота**, а при обычном ответе — текст реплики собеседника:
--
--     прогон 112877  girl_title = 'You remember my guitar only?'
--     прогон 114246  girl_title = ''            (инициатива: prompt_user пуст)
--
-- Из 156 сохранённых прогонов `dating_talk`/`girl_fact_invent` испорчены **все**:
-- 148 пустых, 8 с чужим текстом. Журнал живёт сутки, так что это нижняя оценка.
--
-- Читают `%girl_title%` семь шагов: «Анализ сообщения», «Ответ в чат», «Письмо
-- фавориту», «Ответ на письмо», «Инициатива», «Валидация ответа» и
-- `girl_fact_invent` → «Новый факты». То есть во всех ветках агент не знал, как
-- девушку зовут.
--
-- ## Отчего
--
-- У ноды 2 шесть переменных, и три из них заведены руками **без префикса**:
--
--     id 1  node_girl_title           proxy    %girl_title%      ← правило
--     id 2  node_girl_prompt_system   public   …%node_girl_title%…
--     id 3  node_girl_bio             public   …%node_girl_title%…
--     id 4  girl_title                proxy    %prompt_user%     ← нарушитель
--     id 5  girl_prompt_system        public   …%girl_title%…
--     id 6  girl_bio_example          public   …%girl_title%…
--
-- Префикс `node_` — единственное, что держит переменные ноды от столкновения с
-- переменными workflow: `/chat/ask` накладывает их **после** присланных
-- (`chat.py`, «переменные ноды» после `**json_request.variables`), и имя без
-- префикса молча побеждает. Порядок наложения — `position ASC, name ASC`
-- (`ai_workflow_variables_node_get`), у id 1 и id 4 позиция одна, и `girl_title`
-- идёт раньше `node_girl_title` — потому пустыми оказывались обе.
--
-- ⚠ Привязка к workflow (`node_variable_workflow`) тут не спасала: у id 1–3 она
-- есть (`dating_bot`), у id 4–6 нет вовсе, но **на прогоне её не спрашивают** —
-- таблица читается только импортом и экспортом ноды. Это отдельная работа, и
-- миграция её не делает.
--
-- ## ⚠⚠⚠ ПОЧЕМУ НЕЛЬЗЯ ПРОСТО УДАЛИТЬ `girl_title`
--
-- Через неё идёт имя девушки у `dating_bot`, где его **печатает человек**:
--
--     %prompt_user%  →  girl_title (id 4)  →  node_girl_title (id 1)
--                    →  node_girl_prompt_system (id 2), node_girl_bio (id 3)
--                    →  шаг 9 «agent_create_or_update»
--
-- Снеси id 4 первой — и та же порча переедет к `dating_bot`: новая девушка
-- получит системный промпт «You are a girl .». Поэтому цепочка сперва
-- укорачивается (шаг 1), и лишь затем убирается лишнее (шаг 2).
--
-- ## Что делает миграция
--
-- 1. `node_girl_title` читает `%prompt_user%` напрямую — для `dating_bot` ничего
--    не меняется, значение то же самое и с тем же порядком раскрытия.
-- 2. Убирает три строки без префикса. Точных читателей у них нет: `%girl_title%`
--    ждут от панели, а `%girl_prompt_system%` и `%girl_bio_example%` не
--    спрашивает ни один шаг и ни один агент — проверено по `agent_workflow_step`,
--    `agent.prompt_system` и `agent.greeting`. Ролей и привязок у них тоже нет.
--
-- ⚠ Имя `girl_title` после этого свободно, и присланное панелью доезжает до шагов.
--
-- Идемпотентность: правка значения условна по текущему, удаление — по имени.
-- Второй прогон ничего не меняет.

SET @node = (SELECT `node_id` FROM `node_variable`
              WHERE `name` = 'node_girl_title' ORDER BY `id` LIMIT 1);

SELECT 'ДО' AS этап,
       @node AS нода,
       (SELECT `default` FROM `node_variable`
         WHERE `node_id` = @node AND `name` = 'node_girl_title') AS имя_берётся_из,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `node_id` = @node
           AND `name` IN ('girl_title', 'girl_prompt_system',
                          'girl_bio_example')) AS без_префикса;

-- ── 1. Цепочка имени у `dating_bot` укорачивается ───────────────────────────
--
-- ⚠ Условие по текущему значению, а не просто по имени: прогнанная второй раз
-- миграция не должна переписывать то, что человек успел поправить руками.
UPDATE `node_variable`
   SET `default` = '%prompt_user%'
 WHERE `node_id` = @node
   AND `name` = 'node_girl_title'
   AND `default` = '%girl_title%';

-- ── 2. Строки без префикса уходят ───────────────────────────────────────────
--
-- ⚠ Сперва дети: внешних ключей на `node_variable` может не быть, и осиротевшая
-- строка роли пережила бы удаление молча.
DELETE FROM `node_variable_role`
 WHERE `node_variable_id` IN (
       SELECT `id` FROM (SELECT `id` FROM `node_variable`
                          WHERE `node_id` = @node
                            AND `name` IN ('girl_title', 'girl_prompt_system',
                                           'girl_bio_example')) AS x);

DELETE FROM `node_variable_workflow`
 WHERE `node_variable_id` IN (
       SELECT `id` FROM (SELECT `id` FROM `node_variable`
                          WHERE `node_id` = @node
                            AND `name` IN ('girl_title', 'girl_prompt_system',
                                           'girl_bio_example')) AS x);

DELETE FROM `node_variable`
 WHERE `node_id` = @node
   AND `name` IN ('girl_title', 'girl_prompt_system', 'girl_bio_example');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `default` FROM `node_variable`
         WHERE `node_id` = @node AND `name` = 'node_girl_title') AS имя_берётся_из,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `node_id` = @node
           AND `name` IN ('girl_title', 'girl_prompt_system',
                          'girl_bio_example')) AS без_префикса,
       (SELECT COUNT(*) FROM `node_variable` WHERE `node_id` = @node) AS всего_у_ноды;

-- ⚠⚠ Сторож: трио с префиксом обязано уцелеть целиком — на нём держится
-- заведение девушки в `dating_bot`. Ноль в любой строке значит, что удаление
-- захватило лишнее.
SELECT 'трио с префиксом' AS проверка,
       `id`, `name`, LEFT(`default`, 40) AS начало_значения
  FROM `node_variable`
 WHERE `node_id` = @node AND `name` LIKE 'node\\_%'
 ORDER BY `position`, `name`;
