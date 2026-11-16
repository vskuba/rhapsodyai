-- Шаблон рассылки: день девушки и эмоциональная нить вместо пересказа анкеты (2026-11-16)
--
-- ЗАЧЕМ. Операторы назвали шаблоны рассылки самым слабым местом проекта. На проде
-- 16.11.2026 три шаблона одной анкеты за сутки (Solomia, Ladadate) пересказывали
-- анкету абзацем почти дословно и держались на одних образах: свисток чайника,
-- «light doing that soft gold thing», «forgot sugar in my tea».
--
-- Причины были в самом workflow, а не в нехватке жребиев:
--   * промпт запрещал выдумывать что-либо сверх анкеты — рассказывать модели было
--     не о чем, кроме анкеты;
--   * писателю отдавались целиком десять прошлых писем, и он брал из них образы;
--   * судье прямо разрешено пропускать повтор анкеты.
--
-- ЧТО МЕНЯЕТСЯ.
--   1. Подпоток `girl_day_invent` (по образцу `girl_fact_invent`): сочиняет обычный
--      день девушки по теме из жребия и кладёт из него 2–3 факта в коллекцию
--      `dating_girl` под её ключом `girl_id_girl_name` — тем же, по которому ищет
--      агент чата. Мужчина ответит «а что за кафе?» — агент про это кафе знает.
--   2. Главный жребий — ВИД письма `dice_mail_kind`: день, новость, эмоции
--      (усталость, жалоба на жизнь, «размять плечи»), мечта, провокация, интерес к
--      нему. Мы не знаем, что зацепит незнакомого человека, — письма обязаны быть
--      разными по сути, а не по зачину (решение владельца 16.11.2026). Подпоток
--      дня зовётся только видам day и news. Для всех видов: абзацы вырастают один
--      из другого, анкета — не тема письма.
--   3. Места — обобщённые («набережная», «кафе у работы»): переписка с иностранцами,
--      им названия парков и улиц ничего не скажут, а маленькая модель их путает.
--   4. Вместо прошлых писем целиком писатель видит их зачины (`mail_avoid_brief`,
--      шлёт панель), судья — по-прежнему письма целиком, плюс три новых признака.
--
-- ⚠⚠ ПОРЯДОК ВЫКЛАДКИ: сперва эта миграция, потом панель DatingAi. Панель начнёт
-- слать `girl_id`/`girl_name`/`girl_title`/`mail_avoid_brief`, а необъявленную
-- переменную сосед отвечает 400 на весь прогон. Без них (старая панель) шаг дня
-- пропускается (`girl_id` пуст), и письмо пишется по теме `dice_mail_story`.
--
-- Идемпотентность: всё по условию отсутствия, сдвиг позиций — только пока шага
-- дня нет.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow` WHERE `name` = 'girl_day_invent') AS подпоток,
       (SELECT COUNT(*) FROM `agent_workflow_step` s JOIN `agent_workflow` w ON w.`id` = s.`workflow_id`
         WHERE w.`name` = 'dating_mail_write') AS шагов_письма
;

SET @mw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @node = (SELECT `node_id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

-- ================================================= Подпоток girl_day_invent
INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`, `subflow`)
SELECT @node, 'girl_day_invent', 'День девушки',
       'Обычный день девушки — фон письма рассылки. Факты из него ложатся в dating_girl, чтобы агент чата помнил, о чём она писала',
       0, 1
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow` WHERE `name` = 'girl_day_invent');

SET @dw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'girl_day_invent');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'girl_id', 'input', '', 'Ключ фактов девушки girl_id_girl_name — тот же, что у агента чата'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'girl_id');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'girl_title', 'input', '', 'Имя девушки, как его видит человек'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'girl_title');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'girl_bio', 'input', '', 'Её карточка — день не должен ей противоречить'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'girl_bio');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'girl_day_theme', 'input', '', 'Тема дня — ось dice_mail_day у dating_mail_write'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'girl_day_theme');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'user_language', 'input', 'English', 'Язык даты для datetime_current_get'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'user_language');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'datetime_current_get_zone', 'workflow', 'Europe/Kyiv', 'Пояс текущей даты: время года и погода дня'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'datetime_current_get_zone');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'fact_collection_girl_name', 'workflow', 'dating_girl', 'Коллекция фактов девушки — та же, что ищет dating_talk'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'fact_collection_girl_name');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'fact_day_filter', 'workflow', NULL, 'Фильтр поиска её прежних фактов'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'fact_day_filter');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'fact_day_limit', 'workflow', '12', 'Сколько прежних фактов показать модели'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'fact_day_limit');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'girl_day', 'workflow', '', 'Сочинённый день — уходит родителю'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'girl_day');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @dw, 'girl_day_facts', 'workflow', '', 'Факты дня для fact_collection_add'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @dw AND `name` = 'girl_day_facts');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 3, 'Текущая дата', 0, CAST('{"tool_invoke": {"tool_name": "datetime_current_get", "inputs_map": {"timezone": "datetime_current_get_zone", "language": "user_language"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 0);

SET @p0 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 0);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 3, 'Формат фактов', 1, CAST('{"tool_invoke": {"tool_name": "fact_collection_output_format", "inputs_map": {"collection_name": "fact_collection_girl_name"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 1);

SET @p1 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 1);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 5, 'Фильтр её фактов', 2, CAST('{"variable_conversion": [{"variable": "fact_day_filter", "text": "{\\"document_id\\":\\"%girl_id%\\"}"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 2);

SET @p2 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 2);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 3, 'Её прежние факты', 3, CAST('{"tool_invoke": {"tool_name": "qdrant_fact_search", "inputs_map": {"limit": "fact_day_limit", "query_text": "girl_day_theme", "collection_name": "fact_collection_girl_name", "metadata_filter": "fact_day_filter"}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 3);

SET @p3 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 3);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 2, 'День', 4, CAST(REPLACE(REPLACE(REPLACE('{"prompt_user": "=== Current date ===\\n%datetime_current_get_{{P0}}_result_str%\\n\\n[<if girl_bio>]=== Your profile on a dating site ===\\n%girl_bio%\\n[<endif>]\\n\\n[<if qdrant_fact_search_{{P3}}_result_str>]=== Already existing facts about the girl %girl_title% ===\\n%qdrant_fact_search_{{P3}}_result_str%\\n[<endif>]\\n\\n=== Theme of the day ===\\n%girl_day_theme%\\n\\n=== What need to write ===\\nYou are %girl_title%. Invent what just happened in your life on the theme below — today or these days — so that a letter you write tonight has something real to tell, and so that you remember it later when a man asks about it.\\n\\nRules:\\n- the theme is the core of the story — build it around the theme.\\n- 3–5 small moments in order: where you went, what you saw, what small thing happened, how you felt. Sensory touches: weather, sounds, smells, the feel of the cold or of warm hands around a cup.\\n- ordinary everyday events only: a walk, a café, the market, a girlfriend, the way to work, weather, a small mishap. No people with names, no family members, no children, no pets, no trips to other cities, no romance with anyone.\\n- places — the way you would describe them to a foreigner who has never been to your city: «the river embankment», «the old market», «a little café on the corner», «the park near my office». ⚠ NO proper names of parks, streets, squares, rivers, cafés or shops: they mean nothing to him.\\n- the season and weather must fit the current date. ⚠ NEVER write a weekday, a month, a date or a clock time in the story. Say «today», «this morning», «in the evening».\\n- it must not contradict the profile or the existing facts, and must not repeat a place or an event from the existing facts.\\n- your job, hobbies, appearance may appear only if they naturally belong to the day (you took photos because you love photography), never as a self-introduction.\\n\\nReturn JSON with keys:\\n- \\"girl_day\\": what happened, as a short first-person story, 90–150 words, English, plain text without markdown.\\n- \\"girl_day_facts\\": 2–3 facts about the girl taken from this story — each one or two short sentences, third person and timeless («%girl_title% likes …», «Once %girl_title% …»), tags in English, lower case. For document_id use ''%girl_id%''.\\n\\nExample of JSON response:\\n{\\n  \\"girl_day\\": \\"…\\",\\n  \\"girl_day_facts\\": %fact_collection_output_format_{{P1}}_result_str%\\n}\\n", "llm_to_json_variable": [{"variable": "girl_day", "text": ""}, {"variable": "girl_day_facts", "text": ""}], "transitions_before": [], "transitions_after": [], "to_next_step": true, "thinking_enable": true}', '{{P0}}', @p0), '{{P1}}', @p1), '{{P3}}', @p3) AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 4);

SET @p4 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 4);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 3, 'Факты дня в базу', 5, CAST('{"tool_invoke": {"tool_name": "fact_collection_add", "inputs_map": {"collection_name": "fact_collection_girl_name", "data": "girl_day_facts", "document_title": "girl_title", "user_id": "user_id"}, "outputs_map": {}}, "transitions_before": [{"variable": "girl_day_facts", "operator": "empty", "value": "", "step_id": "{{P7}}"}], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 5);

SET @p5 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 5);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 3, 'Синхронизация Qdrant', 6, CAST('{"tool_invoke": {"tool_name": "qdrant_fact_sync", "inputs_map": {}, "outputs_map": {}}, "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 6);

SET @p6 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 6);

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @dw, 4, 'Вернуть день', 7, CAST('{"prompt_user": "%girl_day%", "continue_workflow": false, "transitions_before": [], "transitions_after": []}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 7);

SET @p7 = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @dw AND `position` = 7);

-- Переход «фактов нет — к возврату» знает номер шага возврата только теперь.
UPDATE `agent_workflow_step` SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR), '{{P7}}', @p7) AS JSON)
 WHERE `id` = @p5;

-- ================================================= dating_mail_write
-- Входы от панели. ⚠ Объявить до выкладки панели: необъявленная переменная — 400.

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'girl_id', 'input', '', 'Номер анкеты на сайте (agent_vars.girl_id) — половина ключа фактов'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'girl_id');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'girl_name', 'input', '', 'Имя латиницей строчными (agent_vars.girl_name) — вторая половина ключа'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'girl_name');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'girl_title', 'input', '', 'Имя девушки, как его видит человек'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'girl_title');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'mail_avoid_brief', 'input', '', 'Зачины её прошлых писем — писателю вместо писем целиком'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'mail_avoid_brief');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'girl_unique_id', 'workflow', '', 'Ключ фактов girl_id_girl_name — как у dating_talk'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'girl_unique_id');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'girl_day', 'workflow', '', 'День девушки от girl_day_invent. Пусто — шаг пропущен (вид письма без сырья или старая панель)'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'girl_day');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @mw, 'girl_day_theme', 'workflow', '', 'Тема подпотока: dice_mail_day у вида day, dice_mail_news у вида news'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @mw AND `name` = 'girl_day_theme');

-- Новые оси жребия: тема дня и эмоциональная нить письма.
UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON),
         '$.dice_mail_day', CAST('{"a slow walk along the river embankment, and one small thing that caught your eye": 4, "coffee with a girlfriend and a walk afterwards": 4, "the way home after work, and what you noticed on it": 4, "a trip to the market for something simple, and a little scene there": 3, "an errand that went a little wrong, and how the evening turned out cozy anyway": 3, "a sudden change of weather that caught you outside": 3, "a lunch break outside the office, ten quiet minutes in the fresh air": 3, "cooking something new in the evening, and how it turned out": 3, "an evening walk in the park near home, alone with your thoughts": 3, "a small kindness from a stranger today": 2, "a busy, tiring day at work and the first quiet moment after it": 4, "a lazy morning that refused to start, and how the day finally got going": 2, "taking photos of ordinary things on the way and one picture you liked": 2, "a bookshop or a little shop you wandered into without a plan": 2, "music you heard on the street or in a café, and the mood it brought": 2, "an evening at home: tea, a blanket, the window, and thoughts before sleep": 3, "a short trip out of the centre on a bus or a tram, looking out of the window": 2, "a girlfriend''s small problem you helped with today": 2, "the first cold morning that made you look for warm clothes": 2, "a café where you sat longer than planned, watching people": 2}' AS JSON),
         '$.dice_mail_feel', CAST('{"life has been tiring lately — work, routine, the same days — and she wants to complain a little to someone who will understand": 4, "a bad day: everything went wrong, and she wishes for someone to tell her it was not her fault": 3, "tired after a long day: the shoulders ache, she wishes someone would knead them — and catches herself imagining his hands": 5, "cold outside, cold fingers: she wants someone to warm her hands in his — and wonders what his hands are like": 4, "a quiet, slightly lonely evening: everything is fine, but there is no one to tell about the day — so she tells him": 5, "a good mood she cannot keep to herself: she wants to share it with someone who would smile back": 4, "sleepy and soft at the end of the day: she wishes for a calm voice to fall asleep to": 3, "a little restless: she wants to walk somewhere together without a plan, just talking": 3, "she cooked or baked something and wishes there were someone to taste it and say it is good": 3, "a long week behind: she dreams of a lazy morning with no alarm, coffee in bed, someone next to her": 4, "she misses simple touch — a hug from behind, a hand on her back — and admits it a little shyly": 4, "curiosity about him that would not let her go today: she keeps guessing what kind of man he is": 3, "a light sadness after the day: she does not want advice, just someone to listen": 3, "a small victory today and no one to celebrate it with — a wish to share it with him": 3, "she felt pretty today and secretly wished someone had noticed": 3, "stress and a heavy head: she wishes someone would just say «it is okay, come here»": 3, "playful: she wants to tease him a little and see if he can play along": 3, "she wants to be taken care of for once — someone to bring her tea and cover her with a blanket": 4, "the day reminded her how much she wants someone to come home to": 3, "she laughed at something silly today and wishes he had been there to laugh with her": 3}' AS JSON),
         '$.dice_mail_kind', CAST('{"day": 22, "feel": 22, "dream": 14, "news": 14, "tease": 16, "him": 12}' AS JSON),
         '$.dice_mail_news', CAST('{"she finally started something she had been putting off for months": 3, "a small change at work — new tasks, a new project, a new desk": 3, "she bought something small for herself and is happier about it than she expected": 3, "she signed up for something new: a class, a course, a dance or a language": 3, "she rearranged her room and it feels like a new home": 2, "she got good news from a close girlfriend and is still smiling": 2, "she made a decision about her life she is proud of": 2, "she found an old photo or a letter of hers that brought back memories": 2, "she tried a new recipe and it became her new favourite": 2, "the first real cold (or the first warm days) arrived and changed her routine": 2, "she had a funny small adventure on the way somewhere": 2, "she finished a book or a series and cannot stop thinking about the ending": 2}' AS JSON),
         '$.dice_mail_dream', CAST('{"the sea: a quiet morning on a beach somewhere warm, nobody in a hurry": 3, "a little house of her own with a garden, a porch and evenings outside": 3, "to travel far, to a country she has only seen in pictures": 3, "a slow Sunday together with someone — breakfast, a walk, no phones": 3, "to dance with someone who leads well, in a place where nobody knows her": 2, "to learn something she always wanted but never dared to": 2, "a road trip with music, stops in small towns and no plan": 2, "to wake up next to someone who is genuinely glad she is there": 3, "a big family dinner at a long table, with laughter and too much food": 2, "to see snow in the mountains, or the northern lights, at least once": 2, "simple things: to be someone''s priority, not an option": 3}' AS JSON)) AS CHAR)
 WHERE `workflow_id` = @mw AND `name` = 'dice_mail_spec'
   AND NOT JSON_CONTAINS_PATH(CAST(`default` AS JSON), 'one', '$.dice_mail_day');

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.outputs_map.dice_mail_day', 'dice_mail_day',
         '$.tool_invoke.outputs_map.dice_mail_feel', 'dice_mail_feel',
         '$.tool_invoke.outputs_map.dice_mail_kind', 'dice_mail_kind',
         '$.tool_invoke.outputs_map.dice_mail_news', 'dice_mail_news',
         '$.tool_invoke.outputs_map.dice_mail_dream', 'dice_mail_dream')
 WHERE `workflow_id` = @mw AND `position` = 0
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name')) = 'dice'
;

-- Два новых шага сразу за жребием: позиции остальных сдвигаются на два.
SET @has_day = (SELECT COUNT(*) FROM `agent_workflow_step`
                 WHERE `workflow_id` = @mw AND `title` = 'День девушки');

UPDATE `agent_workflow_step` SET `position` = `position` + 2
 WHERE `workflow_id` = @mw AND `position` >= 1 AND @has_day = 0
 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @mw, 5, 'Ключ девушки и тема', 1, CAST('{"variable_conversion": [{"variable": "girl_unique_id", "text": "%girl_id%_%girl_name%"}, {"variable": "girl_day_theme", "text": "[<if dice_mail_kind == ''news''>]%dice_mail_news%[<else>]%dice_mail_day%[<endif>]"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE @has_day = 0;

SET @next = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @mw AND `position` = 3);

-- ⚠ Подпоток — только видам day и news: у прочих сырья нет, и вызов модели был бы зря.
-- Пустой girl_id — старая панель: день пропускается, письмо идёт прежней дорогой.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @mw, 6, 'День девушки', 2,
       CAST(REPLACE(REPLACE('{"workflow_invoke": {"workflow_id": "{{DW}}", "inputs_map": {"girl_id": "girl_unique_id", "girl_title": "girl_title", "girl_bio": "girl_bio", "girl_day_theme": "girl_day_theme", "user_language": "user_language"}, "outputs_map": {"girl_day": "girl_day"}}, "transitions_before": [{"variable": "girl_id", "operator": "empty", "value": "", "step_id": "{{NEXT}}"}, {"variable": "dice_mail_kind", "operator": "==", "value": "feel", "step_id": "{{NEXT}}"}, {"variable": "dice_mail_kind", "operator": "==", "value": "dream", "step_id": "{{NEXT}}"}, {"variable": "dice_mail_kind", "operator": "==", "value": "tease", "step_id": "{{NEXT}}"}, {"variable": "dice_mail_kind", "operator": "==", "value": "him", "step_id": "{{NEXT}}"}], "transitions_after": [], "to_next_step": true}', '"{{DW}}"', @dw), '{{NEXT}}', @next) AS JSON)
 WHERE @has_day = 0;

-- Писатель: новый промпт целиком (прежний — в бэкапе выкладки).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', '[<if letter_draft and letter_draft_decline_cause>]=== Previous letter draft (was declined) ===
    Letter draft: %letter_draft%

    Draft declined cause: %letter_draft_decline_cause%
[<endif>]

[<if girl_bio>]=== My card, what I wrote on my site profile ===
    %girl_bio%

    ⚠ This card is for YOU, not for the letter. He has already seen it on the site. Do NOT retell it: no paragraph «I''m 31, I live in …, I work as …, long hair, green eyes, my hobbies are …». At most ONE fact from it, and only where it naturally belongs to what you are telling (you took photos because you love photography, you were tired after work at the office).
[<endif>]

[<if girl_day>]=== What just happened in my life ===
    %girl_day%

    This really happened to me. It is the material of the letter: tell it in your own words, the way you would tell a man you would like to know better — the alive moments and how you felt, not a report. Do not copy the sentences above. Do not add events, people or places that are not there.
[<endif>]

=== What this letter is about ===
[<if dice_mail_kind == ''day''>]    How your day went — the story above is its material. Let him into your day as if he had walked next to you.
[<endif>][<if dice_mail_kind == ''news''>]    A small piece of news from your life — the story above. Share it the way one shares news with someone one wants to be closer to: what changed, how you feel about it.
[<endif>][<if dice_mail_kind == ''feel''>]    Your emotions right now: %dice_mail_feel%. Simple, human, a little vulnerable — tiredness, a complaint about life, a wish to be held or cared for — and how he appears in that wish. No specifics he could check.
[<endif>][<if dice_mail_kind == ''dream''>]    Your dream: %dice_mail_dream%. Tell why it matters to you and leave a little place in it for him.
[<endif>][<if dice_mail_kind == ''tease''>]    Provoke him a little: the admission below is your move. Challenge him, tease him, dare him to answer — playful, never rude.
[<endif>][<if dice_mail_kind == ''him''>]    Him. He is a stranger, and you are curious what kind of man is behind the profile: wonder about him, guess, ask — the admission below sets how. Say little about yourself this time.
[<endif>][<if !dice_mail_kind>][<if dice_mail_story>]    Tell about yourself — about this: %dice_mail_story%
[<endif>][<endif>]
[<if mail_vars>]=== Variables inside letter ===
    Variables (insert as [[...]] — all that is known about it, they possess):

    [<for k,v in mail_vars>][[%k%]] — %v%
    [<endfor>]
[<endif>]

[<if dice_mail_greeting>]=== How to Start ===
    %dice_mail_greeting%
[<endif>]

[<if dice_mail_angle>]=== Admission this time ===
    %dice_mail_angle%
[<if girl_day>]
    The admission is HOW you approach the topic above — not a second topic.
[<endif>]
[<endif>]

[<if dice_mail_length>]=== Length this time ===
    %dice_mail_length%
[<endif>]

[<if dice_mail_sign>]=== Tone of the sign-off this time ===
    %dice_mail_sign%

    ⚠ This is the TONE, not the words. Never put the line above into the letter: it says how the farewell should sound, not what it should say. Write your own short farewell in that tone.
[<endif>]

[<if mail_avoid_brief>]=== How her previous letters began — begin differently ===
    %mail_avoid_brief%
[<endif>]

=== What need to write ===
Write a TEMPLATE for the first email to a man — from a woman, in her own words.
⚠ The text belongs to ONE woman: she is both its author and its heroine. The recipient is an unknown man from another country: nothing is known about him except the variable signatures, and everything about him enters the letter only through them.

Rules of letter writing:
- writing language: %user_language%.
- allowed variables only: [<for k,v in mail_vars>][<if k != ''companion_name'' or dice_mail_name == ''yes''>][[%k%]] — %v%
    [<endif>][<endfor>].
[<if dice_mail_name == ''yes''>]- about the recipient ONLY as [[companion_name]], you do not know his name, neither his city nor profession in your own words. Addressing by name — exactly once per letter,[<endif>][<if dice_mail_name == ''no''>]- you do NOT know the recipient''s name this time and have no variable for it: do not address him by name at all — open the letter without a salutation, or greet him without any name. NEVER use your own name as an address: you are the author of this letter, not its recipient,[<endif>]
- about yourself in the first person, [[girl_name]] appears ONLY in the signature and nowhere else. Do not paste the raw girl name into the text.
- no self-introduction paragraph and no list of your qualities: he knows who you are from the profile — show yourself through the day, not through adjectives.
- ⚠ do NOT invent facts of your life beyond the card and the story above: no pets, no family members, no people with names, no events. Feelings, wishes, dreams and thoughts are yours to tell freely.
- ⚠ places as you would describe them to a foreigner — «the river embankment», «a little café near my office», NO proper names of streets, parks, squares, rivers or cafés.
- ⚠⚠ NEVER name a weekday, a month, a date or a clock time. «Today», «this evening», «this morning» are fine.
- the letter ENDS with a signature: a short warm farewell in your own words, in the tone set above, and [[girl_name]] on the last line — it stands only there.
- a variable whose signature speaks about a question (question_to_companion) is placed as a SEPARATE paragraph where a question would naturally stand, its value is the whole question.

⚠⚠ THE LETTER IS ONE THREAD. Every paragraph grows out of the previous one: it picks up its last thought, feeling or image and carries it further, and leads to him and to the question. If two paragraphs could be swapped without loss, the letter is broken. No paragraph starts a new topic from scratch.

The opening, length, and sign-off are set above — stick to them. Several drafts are written per day: if each comes out alike, the recipient sees a bot''s mass mail, not a real girl.

QUESTION: at the spot where a question is needed, place the variable on its own line — never in the greeting and never in the first sentence. Do NOT write out a question in your own words, otherwise there will be two questions and the letter turns into a questionnaire.

Return JSON: {"letter_draft": "text of the letter"}
')
 WHERE `workflow_id` = @mw AND `title` = 'Письмо'
;

-- Судья: три новых признака повтора перед оговоркой про настроения.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '⚠ Different moods in one send-out', '5. A retelling of her profile: a paragraph that lists who she is — age, city, job, looks, hobbies, «I am cheerful and sociable» — instead of showing her through the moment. Facts from the profile may appear one at a time inside the story, a list of them never.
6. The same picture of her evening or the same detail of her life as in a previous letter (the same kettle, the same light on the table, the same little ritual).
7. Paragraphs that do not follow from each other: each one starts a new topic from scratch, and they could be swapped without loss.

⚠ Different moods in one send-out'))
 WHERE `workflow_id` = @mw AND `title` = 'Судья: не повтор ли?'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) NOT LIKE '%5. A retelling of her profile%'
;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @dw) AS шагов_дня,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `workflow_id` = @dw) AS переменных_дня,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @mw) AS шагов_письма,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @mw AND `position` <= 4) AS начало_письма
;
