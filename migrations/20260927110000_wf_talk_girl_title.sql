-- Разговор: имя девушки отдельной входящей `girl_title` (2026-09-27)
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека)
--
-- У девушки две разные величины, и до сих пор их изображала одна переменная:
--
--     girl_name   техническое имя — латиница в нижнем регистре, ключ
--     girl_title  имя, которым её видит человек: «Elena»
--
-- Так уже сделано у собеседника (`companion_name` — ключ `dating_343_128282`,
-- `companion_title` — «Gerard»), и по той же причине: слей их в одно, и агент либо
-- обращается «привет, dating_343_128282», либо ключует факты по имени, которое на
-- сайте носят десятки людей.
--
-- ## Что меняется
--
-- 1. `girl_title` объявляется входящей у `dating_talk` — она уже есть у
--    `girl_fact_invent`, и это **та же** переменная, а не вторая с тем же именем.
-- 2. Шаг «Девушка регистрация» (`companion_create`) берёт `title` из `girl_title`,
--    а не из `girl_name`: запись собеседника-девушки подписывается человеческим
--    именем, как и запись мужчины рядом (шаг «Собеседник регистрация»).
--
-- ## ⚠ Переменная переиспользуется, а не заводится второй
--
-- `agent_workflow_variable` **не имеет** уникального ключа по имени: строк с одним
-- именем в базе несколько, и они живут своей жизнью. Здесь берётся существующая
-- (`girl_title`, `input`) и лишь привязывается к ещё одному workflow — как это
-- сделано у `girl_bio`, одной на четыре. Завести вторую значило бы, что правка
-- описания в редакторе видна в одном workflow и не видна в другом.
--
-- ⚠ Если строк с этим именем окажется больше одной, миграция **ничего не делает** и
-- говорит об этом: выбрать «любую» значило бы привязать наугад.
--
-- ## ⚠⚠⚠ ЧЕГО ЭТА МИГРАЦИЯ НЕ ДЕЛАЕТ, И ЧТО БЕЗ ЭТОГО СЛОМАЕТСЯ
--
-- **Панель должна начать присылать `girl_title`.** Сейчас DatingAi шлёт только
-- `girl_name` (`agent_vars`), и до его правки шаг регистрации получит **пустое**
-- имя: `companion_create` заведёт запись девушки без подписи. Сама переменная
-- необязательна, отказа не будет — будет тихая пустота.
--
-- **И `girl_name` ещё не стал техническим.** Сегодня панель кладёт в него имя с
-- сайта («Elena»), а не латиницу в нижнем регистре. Пока так, смысл двух переменных
-- совпадает.
--
-- ⚠⚠ Когда `girl_name` действительно станет `elena`, **сменится ключ фактов**: шаг
-- «Переменные» собирает `girl_unique_id` как `%girl_id%_%girl_name%`, то есть
-- `89_Elena` превратится в `89_elena` — новый документ в Qdrant. Факты, лежащие под
-- прежним ключом, окажутся сиротами: агент их не найдёт, а место они занимать
-- будут. Это не довод против — это то, что надо сделать осознанно и одним заходом с
-- правкой панели.
--
-- Идемпотентность: привязка через `INSERT IGNORE`, подстановка в шаге проверяется
-- по текущему значению — второй прогон ничего не меняет.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM agent_workflow_variable
         WHERE name = 'girl_title') AS строк_girl_title,
       (SELECT COUNT(*) FROM agent_workflow_variable v
          JOIN agent_workflow_variable_workflow vw ON vw.variable_id = v.id
         WHERE v.name = 'girl_title' AND vw.workflow_id = 5) AS привязана_к_talk,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.tool_invoke.inputs_map.title'))
          FROM agent_workflow_step
         WHERE workflow_id = 5 AND title = 'Девушка регистрация') AS title_берётся_из;

-- ── 1. Переменная: одна и та же, привязываем ко второму workflow ─────────────
--
-- ⚠ Номер ищем **по имени**, а не зашиваем: автономера у баз свои. Здесь они
-- совпали (88 и там, и там), но полагаться на это нельзя — ровно так ломаются
-- переносы «по номеру из редактора».
SET @girl_title = (SELECT v.id FROM agent_workflow_variable v
                    WHERE v.name = 'girl_title' AND v.type = 'input'
                    ORDER BY v.id LIMIT 1);

SET @many = (SELECT COUNT(*) FROM agent_workflow_variable
              WHERE name = 'girl_title');

SET @sql = IF(@many = 1 AND @girl_title IS NOT NULL,
    'INSERT IGNORE INTO `agent_workflow_variable_workflow` (variable_id, workflow_id)
     SELECT @girl_title, 5',
    'SELECT ''girl_title не одна или её нет — привязка пропущена'' AS пропуск');

PREPARE st FROM @sql;
EXECUTE st;
DEALLOCATE PREPARE st;

-- Описания: чем одна отличается от другой. ⚠ Пишем **обе**, иначе человек в
-- редакторе видит две похожие переменные и должен угадывать, какая из них ключ.
UPDATE `agent_workflow_variable`
   SET `description` = 'Имя девушки для человека: им агент подписывает её запись и '
                       'зовёт её в тексте. Приходит запросом от панели'
 WHERE `id` = @girl_title AND @many = 1;

UPDATE `agent_workflow_variable`
   SET `description` = 'Техническое имя девушки — латиница в нижнем регистре. Часть '
                       'ключа фактов (girl_unique_id). Человеческое имя — girl_title'
 WHERE `name` = 'girl_name' AND `type` = 'input';

-- ── 2. Шаг «Девушка регистрация»: подпись из человеческого имени ─────────────
--
-- ⚠ Ищем **по названию шага плюс инструменту**: шагов `companion_create` в этом
-- workflow два — «Собеседник регистрация» и «Девушка регистрация», — и правка «по
-- инструменту» задела бы оба, переписав мужчине подпись девушкиной переменной.
--
-- ⚠ Условие `... .title = 'girl_name'` держит идемпотентность: второй прогон видит
-- уже `girl_title` и не трогает строку.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.title',
                             'girl_title')
 WHERE `workflow_id` = 5
   AND `title` = 'Девушка регистрация'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
       = 'companion_create'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.title'))
       = 'girl_name';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM agent_workflow_variable v
          JOIN agent_workflow_variable_workflow vw ON vw.variable_id = v.id
         WHERE v.name = 'girl_title' AND vw.workflow_id = 5) AS привязана_к_talk,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.tool_invoke.inputs_map.title'))
          FROM agent_workflow_step
         WHERE workflow_id = 5 AND title = 'Девушка регистрация') AS title_берётся_из,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.tool_invoke.inputs_map.title'))
          FROM agent_workflow_step
         WHERE workflow_id = 5 AND title = 'Собеседник регистрация')
         AS у_мужчины_осталось,
       (SELECT COUNT(*) FROM agent_workflow_variable
         WHERE name = 'girl_title') AS строк_girl_title;

-- ⚠⚠ Сторож: ключ фактов девушки собирается из `girl_name`, и эта миграция его не
-- меняла. Если строка ниже вдруг покажет `girl_title`, значит правка ушла не в тот
-- шаг — и факты всех девушек поехали бы в новые документы.
SELECT 'ключ фактов девушки' AS проверка,
       JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.variable_conversion')) AS сборка
  FROM agent_workflow_step
 WHERE workflow_id = 5 AND position = 0;
