-- Промпт письма чинится после порчи в base64 и переписывается коротко (2026-09-07)
--
-- ЧТО СЛУЧИЛОСЬ. Миграция цикла проверок (`20260907110000`) собирала новый промпт
-- из старого:
--
--     'prompt_user', CONCAT('%if write_hint%…', JSON_UNQUOTE(JSON_EXTRACT(…)), …)
--
-- ⚠ `JSON_UNQUOTE` возвращает значение с **бинарной** сортировкой. `CONCAT`,
-- смешав его с utf8mb4-литералами, дал `VARBINARY`, а `JSON_OBJECT`, получив
-- двоичное значение, закодировал его по правилам MySQL — в `base64:type251:…`.
--
-- Промпт стал строкой base64 длиной 5182 знака. Модель исправно получала её и
-- отвечала отказом «request (3940 tokens) exceeds the available context size
-- (2048 tokens)» — я принял это за нехватку контекста и пошёл ужимать текст,
-- хотя ужимать надо было не текст, а собственную ошибку.
--
-- ⚠ ПРО 2048 ОТДЕЛЬНО, ПОТОМУ ЧТО ЭТО ПРАВДА. Сервер поднят с `--ctx-size 8192
-- --parallel 4`, а llama.cpp делит контекст между слотами: 8192 ÷ 4 = 2048 на
-- запрос. Модель умеет больше, слоту достаётся четверть. Промпт письма должен
-- укладываться в это, и короткая версия ниже — не только починка, но и посадка в
-- реальный предел.
--
-- ЧТО ВМЕСТО. Промпт пишется **целиком, литералом**, без чтения прежнего значения.
-- Так нечему становиться двоичным, а заодно видно глазами, что именно уходит
-- модели.
--
-- ⚠ УСЛОВИЯ В `WHERE` НЕТ НАМЕРЕННО. Оно ловило бы текст в испорченном значении —
-- то есть не сработало бы ровно там, где нужно (так и вышло с миграцией
-- `20260907120000`, которая искала `ДВА УСЛОВИЯ` в base64 и ничего не нашла).
-- Присвоение одного и того же значения дважды безвредно, и это надёжнее любого
-- условия.
--
-- Порядок правил сохранён: язык и переменные впереди — на этом уже обжигались
-- (`20260907100000`), модель держит первые пункты лучше. Объяснения причин убраны:
-- они писались для большой модели, а здесь занимают место, вытесняя ответ.

-- ---------------------------------------------------------------- До
SET @nl = CONCAT(CHAR(92), 'n');
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);
SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);

SELECT 'ДО' AS этап, @a AS шаг_письма,
       (SELECT CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
          FROM `agent_workflow_step` WHERE `id` = @a) AS знаков_было,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS испорчен;

-- ------------------------------------------- Промпт письма целиком
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter', 'text', 'текст письма целиком')),
        'prompt_user', CONCAT(
          '%if write_hint%НЕ ГОДИТСЯ: %write_hint%', @nl,
          'Перепиши, устранив это.', @nl, @nl, '%endif%',
          'Напиши первое письмо от девушки мужчине на сайте знакомств.', @nl, @nl,
          'От кого:', @nl, '%girl_card%', @nl, @nl,
          'Кому:', @nl, '%companion_card%', @nl, @nl,
          'Переменные (вставляй как [[имя]]):', @nl, '%mail_vars%', @nl, @nl,
          'Пожелание: %mail_hint%', @nl, @nl,
          'Обязательно:', @nl,
          '- язык письма: %user_language%;', @nl,
          '- имена и город — только переменной [[имя]] из списка, не словами;', @nl,
          '- если есть переменная про вопрос (question_to_companion) — поставь её ',
          'вместо вопроса, свой текст не пиши.', @nl, @nl,
          'Ещё:', @nl,
          '- до четырёх абзацев;', @nl,
          '- задай вопрос про его интересы;', @nl,
          '- обращайся к получателю, а не к себе;', @nl,
          '- живо и просто, без признаний в любви.', @nl, @nl,
          'Верни JSON: {"letter": "текст письма"}'))
 WHERE `id` = @a;

-- ------------------------------------------- Проверка языка тоже короче
--
-- Ей на вход идёт всё письмо целиком, и своих слов у неё должно быть немного.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_EXTRACT(`metadata`, '$.transitions_after'),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter_lang_ok',
                      'text', '1 — письмо на нужном языке, 0 — на другом')),
        'prompt_user', CONCAT(
          'Требуемый язык (код): %user_language%', @nl, @nl,
          'Письмо:', @nl, '%letter%', @nl, @nl,
          'Письмо целиком на требуемом языке? Имена, города и [[переменные]] не в счёт.',
          @nl, 'Верни JSON: {"letter_lang_ok": 1} или {"letter_lang_ok": 0}'))
 WHERE `id` = @c;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
          FROM `agent_workflow_step` WHERE `id` = @a) AS знаков_письма,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS всё_ещё_испорчен,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after'))
          FROM `agent_workflow_step` WHERE `id` = @c) AS переходы_языка_целы;
