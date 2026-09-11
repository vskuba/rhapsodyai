-- Корень порчи промпта: `CHAR(92)` возвращает двоичное значение (2026-09-07)
--
-- ЧТО БЫЛО. Прошлая починка (`20260907130000`) писала промпт литералом, без
-- чтения прежнего значения, — и всё равно получила `base64:type251:…`. Длина
-- упала с 5182 до 1433 знаков (короткий текст закодировался короче), но кодировка
-- осталась.
--
-- ⚠ ПРИЧИНА — `CHAR(92)`. Им я собирал перенос строки: `SET @nl = CONCAT(CHAR(92),
-- 'n')`. В MySQL `CHAR(N)` возвращает **VARBINARY**, а не текст. Любой `CONCAT` с
-- участием такого значения даёт двоичный результат, и `JSON_OBJECT`, получив
-- двоичное значение, кодирует его по своим правилам — в base64.
--
-- То есть заражал результат не `JSON_UNQUOTE`, как я решил прошлый раз, а
-- переменная `@nl`, которую я сам же и завёл — в миграции `20260907050000`, чтобы
-- обойти двойное экранирование обратного слэша. Там она работала (тот `REPLACE`
-- писал в `LONGTEXT`, минуя `JSON_OBJECT`) и потому не вызывала подозрений.
--
-- ЧТО ВМЕСТО. `CHAR(92 USING utf8mb4)` — та же цель, текстовый тип. Заодно
-- `CONVERT(… USING utf8mb4)` вокруг всего собранного промпта: страховка на случай,
-- если двоичное значение придёт из другого места.
--
-- ⚠ ПРОВЕРКА В КОНЦЕ СМОТРИТ НА ПРИЗНАК ПОРЧИ, А НЕ НА ДЛИНУ. Длина обманула:
-- 1433 знака выглядели как удачно ужатый промпт, а были base64 от него.

-- ---------------------------------------------------------------- До
-- ⚠ Вот оно, отличие: `USING utf8mb4`.
SET @nl = CHAR(10 USING utf8mb4);
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');
SET @a = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0);
SET @c = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2);

SELECT 'ДО' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS письмо_испорчено,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @c) AS проверка_испорчена;

-- ------------------------------------------- Промпт письма
--
-- ⚠ Перенос строки теперь **настоящий** (`CHAR(10)`), а не пара символов `\` + `n`.
-- Прежде она была нужна, потому что текст лежал внутри JSON-строки и требовал
-- экранирования; здесь строку собирает сам `JSON_OBJECT` и экранирует её сам.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_ARRAY(),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter', 'text', 'текст письма целиком')),
        'prompt_user', CONVERT(CONCAT(
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
          'Верни JSON: {"letter": "текст письма"}') USING utf8mb4))
 WHERE `id` = @a;

-- ------------------------------------------- Проверка языка
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_OBJECT(
        'transitions_before', JSON_ARRAY(),
        'transitions_after', JSON_EXTRACT(`metadata`, '$.transitions_after'),
        'llm_to_json_variable', JSON_ARRAY(
          JSON_OBJECT('variable', 'letter_lang_ok',
                      'text', '1 — письмо на нужном языке, 0 — на другом')),
        'prompt_user', CONVERT(CONCAT(
          'Требуемый язык (код): %user_language%', @nl, @nl,
          'Письмо:', @nl, '%letter%', @nl, @nl,
          'Письмо целиком на требуемом языке? Имена, города и [[переменные]] не в счёт.',
          @nl, 'Верни JSON: {"letter_lang_ok": 1} или {"letter_lang_ok": 0}')
          USING utf8mb4))
 WHERE `id` = @c;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE 'base64:%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS письмо_испорчено,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%user_language%'
          FROM `agent_workflow_step` WHERE `id` = @a) AS язык_на_месте,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after'))
          FROM `agent_workflow_step` WHERE `id` = @c) AS переходы_целы;
