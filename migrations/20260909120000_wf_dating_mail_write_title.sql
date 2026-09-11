-- `dating_mail_write` придумывает шаблону название (2026-09-09)
--
-- ЧТО БЫЛО. Workflow возвращал только текст письма, а имя шаблона собирал вызывающий
-- (DatingAi): `Draft 2026-09-09 #1`. В списке из десятка таких заготовок различить их
-- нельзя вовсе — три письма одного дня отличаются только номером, а по номеру не
-- видно, чем письмо отличается от соседнего. Человек и сказал: «названия шаблонов
-- непонятные».
--
-- ⚠ ПОЧЕМУ ЭТО ЗАДАЧА МОДЕЛИ, А НЕ ВЫЗЫВАЮЩЕГО. Имя должно говорить о **тексте** —
-- «Short and direct», «About his hobbies». Знает текст только тот, кто его написал;
-- вызывающий получает готовую строку и может разве что взять из неё первые слова, а
-- это будет «Hi [[companion_name]], I came across…» — то есть снова не название.
--
-- ЧТО ВМЕСТО. Первый шаг возвращает два поля вместо одного, а последний отдаёт их
-- вместе: строка `TITLE: …`, затем пустая строка, затем письмо.
--
-- ⚠ РАЗДЕЛИТЕЛЬ СТРОКОЙ, А НЕ JSON. В письме есть переносы строк, и упаковка его в
-- JSON на последнем шаге потребовала бы экранирования, которого шаблонизатор
-- `%letter%` не делает: первый же перенос порвал бы разбор. Строка-метка разбирается
-- одним `startswith` и не ломается ни от чего внутри письма.
--
-- ⚠ Разбор терпим к отсутствию метки: не вернёт модель `TITLE:` — DatingAi возьмёт
-- имя по дате, как раньше. Шаблон без названия хуже, чем с невнятным, но письмо без
-- шаблона хуже вдвойне.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ── Шаг «Письмо»: просим ещё и название ──────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
           `metadata`,
           '$.prompt_user',
           CONCAT(
               '%if write_hint%НЕ ГОДИТСЯ: %write_hint%', CHAR(10 USING utf8mb4),
               'Перепиши, устранив это.', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               '%endif%Напиши ШАБЛОН первого письма от девушки мужчине на сайте знакомств.',
               CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               '⚠ Это заготовка для рассылки: одним и тем же текстом напишут разные девушки разным мужчинам. Ты не знаешь, кто именно, — и знать не должен.',
               CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               'Переменные (вставляй как [[имя]]):', CHAR(10 USING utf8mb4),
               '%mail_vars%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               'Пожелание: %mail_hint%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               'Обязательно:', CHAR(10 USING utf8mb4),
               '- язык письма И НАЗВАНИЯ: %user_language%;', CHAR(10 USING utf8mb4),
               '- НИКАКОЙ конкретики: ни имён, ни городов, ни профессий, ни возраста. Всё это подставится переменными. Придумаешь «Diana из Kyiv» — шаблон станет годен одной анкете из сорока;',
               CHAR(10 USING utf8mb4),
               '- переменная, чья подпись говорит про вопрос (question_to_companion), ставится ОТДЕЛЬНЫМ абзацем: её значение — целый вопрос, и внутри фразы выйдет «What are What do you enjoy??».',
               CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               'Ещё:', CHAR(10 USING utf8mb4),
               '- до четырёх абзацев;', CHAR(10 USING utf8mb4),
               '- обращайся к получателю, а не к себе;', CHAR(10 USING utf8mb4),
               '- живо и просто, без признаний в любви;', CHAR(10 USING utf8mb4),
               '- о себе — общими словами, которые подойдут любой: не «я хореограф», а «я люблю своё дело».',
               CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               'НАЗВАНИЕ (title): 2–4 слова о том, ЧЕМ это письмо отличается от других — тон, приём, о чём спрашивает. «Short and direct», «Curious about his hobbies», «Warm and playful». НЕ «Letter 1», не «Template», не первые слова письма, никаких [[переменных]] в названии.',
               CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
               'Верни JSON: {"letter": "текст письма", "title": "название"}'),
           '$.llm_to_json_variable',
           CAST('[{"text": "текст письма целиком", "variable": "letter"},
                  {"text": "короткое название шаблона, 2-4 слова", "variable": "letter_title"}]' AS JSON))
 WHERE `workflow_id` = @wf AND `title` = 'Письмо';

-- ── Шаг «Готово»: отдаём название и письмо вместе ────────────────────────────
--
-- ⚠ `CHAR(10 USING utf8mb4)`, а не `CHAR(10)`: без указания набора MySQL отдаёт
-- VARBINARY, и склейка превращает всю строку в двоичную — наружу она уезжает как
-- `base64:type251:` и разбирается уже не текстом. Грабли известные, см. `api.md`.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
                             CONCAT('TITLE: %letter_title%', CHAR(10 USING utf8mb4),
                                    CHAR(10 USING utf8mb4), '%letter%'))
 WHERE `workflow_id` = @wf AND `title` = 'Готово';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.llm_to_json_variable'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Письмо') AS полей_в_ответе,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Готово') AS что_отдаём;
