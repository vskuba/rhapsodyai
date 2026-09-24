-- Все запросы к Qdrant ходят склеенными ключами (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ: записываем одним ключом, ищем другим
--
-- Прошлые две миграции перевели на склейку **запись** фактов и один фильтр из
-- четырёх. Осталось три места, и каждое искало по старому ключу:
--
--     факты пары            пишем `%girl_unique_id%_%companion_unique_id%`
--                           ищем  `%girl_id%_%companion_name%`
--     факты девушки, теги   пишем `%girl_unique_id%`, ищем `%girl_id%`
--     придуманные факты     то же, в подпрогоне `girl_fact_invent`
--
-- Это худший вид поломки: **ошибки нет вовсе**. Записанное ложится под новый
-- ключ, поиск идёт под старым и честно возвращает пусто — агент просто «не
-- помнит» ничего, о чём говорили минуту назад, и в журнале всё зелено.
--
-- ⚠ Нашлось проверкой, а не прогоном: живой заход выглядел бы обычным.
--
-- ## Чем ключуется что
--
--     девушка       %girl_unique_id%
--     собеседник    %companion_unique_id%
--     их пара       %girl_unique_id%_%companion_unique_id%
--
-- ## ⚠ Теги в фильтре — не ключ, их не трогаем
--
-- `"tags":"%prompt_user_tags%"` сужает выборку внутри документа: ключ отвечает
-- «чьи факты», теги — «о чём». Оба фильтра с тегами (собеседник и девушка)
-- оставлены как есть.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @inv = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_fact_invent');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` IN (@wf, @inv)
           AND `metadata` LIKE '%document\_id%'
           AND (`metadata` LIKE '%\%girl\_id\%%'
             OR `metadata` LIKE '%\%companion\_name\%%')) AS шагов_со_старым;

-- ── Факты пары ──────────────────────────────────────────────────────────────
--
-- ⚠ Точечно по пути JSON: метка сидит внутри JSON-строки, и лесенка
-- экранирования в SQL-литерале уже однажды не сошлась — замена прошла «удачно»,
-- не изменив ничего (`…_wf_talk_companion_key`).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[2].text',
         '{"document_id":"%girl_unique_id%_%companion_unique_id%","tags":"%prompt_user_tags%"}')
 WHERE `workflow_id` = @wf AND `title` = 'Переменные'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.variable_conversion[2].variable')) = 'fact_collection_talk_filter';

-- ── Факты девушки по тегам ──────────────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[3].text',
         '{"document_id":"%girl_unique_id%","tags":"%prompt_user_tags%"}')
 WHERE `workflow_id` = @wf AND `title` = 'Переменные'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.variable_conversion[3].variable')) = 'fact_collection_girl_filter_tags';

-- ── Придуманные факты: подпрогон ────────────────────────────────────────────
--
-- ⚠⚠ Здесь правится **сам подпрогон**, а не его вызов: `girl_id` приходит в него
-- через `inputs_map`, и родитель уже шлёт туда склейку
-- (`…_wf_talk_girl_key`). То есть внутри `girl_id` — это уже `89_Elena`, и
-- фильтр верен. Но зовут подпрогон и другие: `dating_bot` кладёт туда своё.
-- Поэтому имя довода не меняем, а переименовываем только там, где договор наш.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.variable_conversion[0].text',
         '{"document_id":"%girl_id%"}')
 WHERE `workflow_id` = @inv AND `title` = 'Переменные'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.variable_conversion[0].variable')) = 'fact_invent_filter';

-- ── Имя девушки в описании ключей ──────────────────────────────────────────
--
-- ⚠⚠ Та же фраза, что уже правилась в промпте, живёт **вторым экземпляром** в
-- `llm_to_json_variable` — описании ключей, которое движок подклеивает к
-- промпту: «есть вопрос к девушке … и на этот вопрос %girl_id% должна
-- ответить». Модель читала «на этот вопрос 89 должна ответить».
--
-- ⚠ Промпт и описания ключей — **разные поля**, и правка одного не задевает
-- другое. Прошлая миграция поправила промпт и прошла проверку: в нём чисто. Это
-- нашлось только сплошным поиском по метаданным.
UPDATE `agent_workflow_step`
   SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR),
         'этот вопрос %girl_id% должна', 'этот вопрос %girl_name% должна') AS JSON)
 WHERE `workflow_id` = @wf AND `title` = 'Анализ сообщения';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Переменные'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.variable_conversion[2].text'))
               = '{"document_id":"%girl_unique_id%_%companion_unique_id%","tags":"%prompt_user_tags%"}')
         AS пара_склейкой,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Переменные'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.variable_conversion[3].text'))
               = '{"document_id":"%girl_unique_id%","tags":"%prompt_user_tags%"}')
         AS девушка_по_тегам,
       -- ⚠ Главная проверка: у `dating_talk` не осталось фильтров со старыми
       -- ключами. `girl_fact_invent` сюда не входит — там `girl_id` приходит
       -- доводом и уже несёт склейку.
       -- ⚠ Смотрим **все** метаданные, а не только фильтры: одна и та же фраза
       -- живёт и в промпте, и в описании ключей, и правка одного поля не
       -- задевает другое.
       --
       -- ⚠⚠ Шаг «Ключи» исключён, и это не поблажка: `%girl_id%` там — **сырьё
       -- склейки**, ровно то место, где ему и полагается быть. Без оговорки
       -- проверка вечно показывала бы единицу, и читающий отчёт искал бы
       -- несуществующую недоделку.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` <> 'Ключи'
           AND (`metadata` LIKE '%\%girl\_id\%%'
             OR `metadata` LIKE '%document\_id%\%companion\_name\%%')) AS осталось_старых,
       -- ⚠ Теги обязаны уцелеть: они отвечают «о чём факт», а не «чей».
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Переменные'
           AND `metadata` LIKE '%prompt\_user\_tags%') AS фильтры_с_тегами;
