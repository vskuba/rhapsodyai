-- Придуманные факты ложатся под ключ девушки, а не под имя агента (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ: подпрогон писал в одно место, а искал в другом
--
-- `girl_fact_invent` придумывает факты о девушке, когда собеседник спросил её о
-- прошлом или увлечениях. Смысл занятия — придумать **один раз** и запомнить:
-- иначе на тот же вопрос завтра придумается другое, и девушка начнёт себе
-- противоречить.
--
-- Запоминания не было. Промпт велел модели помечать факты так:
--
--     используй для document_id: значение '%girl_name%'
--
-- А поиск в том же подпрогоне идёт по другому ключу:
--
--     {"document_id":"%girl_id%"}
--
-- ⚠⚠ И `%girl_name%` внутри подпрогона — это **имя агента**, а не девушки:
-- родитель шлёт `girl_name: agent_name` (`dating_talk`, шаг `girl_fact_create`).
-- То есть все придуманные факты всех девушек ложились в один документ с ключом
-- `dating_girl_universal` — и не находились ничем.
--
-- ## Доказательство из прода
--
-- Среди пяти документов фактов на проде был **`dating_girl_universal` с двумя
-- фактами** — ровно эти сироты. Я счёл их «именем агента, а не девушки» и удалил
-- при переносе; это был симптом, а не мусор.
--
-- Два факта — вся работа занятия за всё время. Остальные 114 написал
-- `dating_girl_create` из биографии, и у него ключ верный.
--
-- ## Что меняется
--
--     было   document_id: '%girl_name%'   → dating_girl_universal
--     стало  document_id: '%girl_id%'     → 1430354_renata
--
-- ⚠ `girl_id` внутри подпрогона — это склеенный ключ: родитель шлёт туда
-- `girl_unique_id` (`…_wf_talk_girl_key`). То есть ровно то, чем ищет фильтр.
--
-- ## ⚠ Человеческое имя в промпте не трогаем
--
-- Там же есть `%girl_title%` — «на этот вопрос %girl_title% должна ответить», — и
-- это подпись для модели, а не ключ. Оба вхождения `%girl_name%` относятся
-- **только** к `document_id`, и меняются только они.
--
-- ## ⚠⚠ Старые сироты не переносятся
--
-- Их два, они лежат под `dating_girl_universal` и принадлежат неизвестно какой
-- девушке: имя агента одно на всех. Приписать их кому-то значило бы отдать одной
-- анкете выдумки другой.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_fact_invent');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%document\_id: значение ''\%girl\_name\%''%') AS шагов_с_именем_агента;

-- ── Ключ вместо имени ───────────────────────────────────────────────────────
--
-- ⚠⚠ Заменяем **обе** метки одной правкой, и обе они про `document_id`: первая в
-- указании, вторая в примере рядом. Поправь одну — модель получила бы указание с
-- одним ключом и пример с другим, а это худший вид промпта: она выберет тот, что
-- ближе к концу.
--
-- ⚠ Замена идёт по **распакованной строке** (`JSON_UNQUOTE` → `REPLACE` →
-- `JSON_SET`): метка сидит внутри JSON-строки, и лесенка экранирования в
-- SQL-литерале здесь уже дважды не сошлась — замена проходила «удачно», не
-- изменив ничего (`…_wf_talk_companion_key`).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%girl_name%', '%girl_id%'))
 WHERE `workflow_id` = @wf
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       LIKE '%\%girl\_name\%%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%\%girl\_name\%%') AS осталось_имени_агента,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%document\_id: значение ''\%girl\_id\%''%') AS шагов_с_ключом,
       -- ⚠⚠ Главная проверка: **чем помечаем, тем и ищем**. Разойдись эти два
       -- ключа снова — записанное перестанет находиться, и молча: ошибки нет,
       -- поиск честно вернёт пусто.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Переменные'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.variable_conversion[0].text'))
               = '{"document_id":"%girl_id%"}') AS фильтр_тем_же_ключом,
       -- ⚠ Подпись для модели обязана уцелеть: `%girl_title%` — это «кто
       -- отвечает», а не ключ.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%\%girl\_title\%%') AS подпись_цела,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND NOT JSON_VALID(`metadata`)) AS битых_метаданных;
