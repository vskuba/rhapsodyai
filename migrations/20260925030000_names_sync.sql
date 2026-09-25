-- Названия workflow, агентов и шагов — как в редакторе (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ: переименования делают руками, и они никуда не едут
--
-- Заголовок workflow, агента или шага правят прямо в админке. Миграции об этом не
-- знают, и прод остаётся с прежними именами: локально список слева читается
-- «Девушка: создание», «Факты: собеседник: сохранить», а там по-прежнему
-- «Создание девушки» и «Сохранить факты собеседника».
--
-- Вреда работе нет — это подписи. Но человек ищет workflow по имени, которое
-- видел, и не находит; а сверяя прод с локальным, каждый раз спотыкается о
-- «вроде то же самое, но названо иначе».
--
-- ## Что выравнивается
--
--     workflow  #2   Dating bot                   → Dating: bot
--     workflow  #5   Чат с девушкой               → Чат
--     workflow  #6   Придумать факты девушки      → Факты: девушка: придумать
--     workflow  #7   Сохранить факты собеседника  → Факты: собеседник: сохранить
--     workflow  #58  Создание девушки             → Девушка: создание
--     агент     #43  Planning Bot                 → Bot
--
-- ## ⚠⚠ Шаги по номеру не сравниваются, и это стоило ложной правки
--
-- Сперва в этой миграции стояло переименование шагов #621 и #622: локально они
-- зовутся «Сжать ответ шага» и «Вернуть строку», на проде — «Значения» и
-- «Письмо». Выглядело переименованием, которое не доехало.
--
-- На копии прода оказалось, что это **разные шаги с совпавшими номерами**:
--
--     локально  #621, #622  → task_log_summarizer
--     на проде  #621        → dating_mail_vars,  #622 → dating_mail_write
--
-- Номер шага — автоинкремент, свой в каждой базе. Правка переименовала бы два
-- живых почтовых шага чужими именами: «Значения» в наборе переменных стало бы
-- «Сжать ответ шага», и никто бы не понял, откуда это.
--
-- ⚠ Отсюда правило для всей миграции: workflow и агентов ищем по `name`, шаги —
-- по устройству (тип, инструмент, доводы). По номеру — никогда.
--
-- ## ⚠⚠ Чего здесь НЕТ, и это намеренно
--
-- `blog_writer` (#61) потерял заголовок **локально** — там пусто, на проде
-- «Blog writer». Это не переименование, а потеря: кто-то стёр поле в редакторе.
-- Затирать им прод нельзя, поэтому workflow здесь не упомянут вовсе.
--
-- Шаги `dating_talk`, заведённые сегодняшними миграциями («Разговор: чат» →
-- «История: чат»), выравниваются **ниже отдельным запросом**: их номера на проде
-- и локально разные, и по `id` их не найти.
--
-- ## ⚠ Ищем по системному имени, а не по номеру
--
-- Номера workflow и агентов у баз совпадают, но опираться на это незачем:
-- `name` — то, по чему их находит код, и он же не меняется при переименовании.

SELECT 'ДО' AS этап,
       (SELECT `title` FROM `agent_workflow` WHERE `name` = 'dating_talk') AS чат,
       (SELECT `title` FROM `agent_workflow` WHERE `name` = 'dating_girl_create') AS девушка,
       (SELECT `title` FROM `agent` WHERE `name` = 'planning_bot') AS агент_бота;

-- ── Workflow ────────────────────────────────────────────────────────────────
UPDATE `agent_workflow` SET `title` = 'Dating: bot' WHERE `name` = 'dating_bot';
UPDATE `agent_workflow` SET `title` = 'Чат' WHERE `name` = 'dating_talk';
UPDATE `agent_workflow` SET `title` = 'Факты: девушка: придумать'
 WHERE `name` = 'girl_fact_invent';
UPDATE `agent_workflow` SET `title` = 'Факты: собеседник: сохранить'
 WHERE `name` = 'companion_fact_extract';
UPDATE `agent_workflow` SET `title` = 'Девушка: создание'
 WHERE `name` = 'dating_girl_create';

-- ── Агент ───────────────────────────────────────────────────────────────────
UPDATE `agent` SET `title` = 'Bot' WHERE `name` = 'planning_bot';

-- ── Шаги чтения лент в `dating_talk` ───────────────────────────────────────
--
-- ⚠⚠ Заводятся миграцией `…_wf_talk_companion_session` под именами «Разговор:
-- чат» и «Разговор: письма», а в редакторе их переименовали в «История: …».
-- Прогон не сломается ни при каком имени — в обеих базах их ищут по устройству, —
-- но подписи должны сойтись, иначе сверка прода с локальным каждый раз спотыкается.
--
-- ⚠ Отличаем по каналу в доводах, а не по номеру: номера свои у каждой базы.
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

UPDATE `agent_workflow_step`
   SET `title` = 'История: чат'
 WHERE `workflow_id` = @wf
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
       = 'companion_session_history'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.kind'))
       = '_const_chat';

UPDATE `agent_workflow_step`
   SET `title` = 'История: письма'
 WHERE `workflow_id` = @wf
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
       = 'companion_session_history'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.inputs_map.kind'))
       = '_const_mail';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `title` FROM `agent_workflow` WHERE `name` = 'dating_talk') AS чат,
       (SELECT `title` FROM `agent_workflow` WHERE `name` = 'dating_girl_create') AS девушка,
       (SELECT `title` FROM `agent` WHERE `name` = 'planning_bot') AS агент_бота,
       -- ⚠ Шаги лент обязаны найтись оба: не найдись — значит миграция, их
       -- заводящая, ещё не прошла, и порядок сломан.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` LIKE 'История: %') AS шагов_лент,
       -- ⚠⚠ `blog_writer` обязан сохранить свой заголовок: локально он пуст, и
       -- случайное выравнивание «по локальному» стёрло бы его на проде.
       (SELECT COUNT(*) FROM `agent_workflow`
         WHERE `name` = 'blog_writer' AND COALESCE(`title`, '') <> '') AS блог_цел;
