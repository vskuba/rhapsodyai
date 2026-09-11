-- `dating_mail_reply`: шаг проверки ответа (2026-09-09)
--
-- ЧТО БЫЛО. Workflow писал ответ и сразу отдавал его: два шага, «Ответ» и «Готово».
-- Что бы модель ни вернула, оно попадало в пул.
--
-- ⚠ ПОЧЕМУ ПРОМПТА МАЛО. Правила в нём есть — язык, длина, «не выдумывай контакты», —
-- но промпт **повышает вероятность, а не обещает**. На `dating_mail_write` это уже
-- было видно: правило «вставляй переменные» стояло первым и объяснено причиной, а три
-- прогона подряд дали две переменные, одну и ни одной. Поэтому там и появились шаги
-- проверки; здесь ровно та же нужда.
--
-- ЧТО ПРОВЕРЯЕМ. Одним шагом и одной моделью — четыре вещи, которые видно только в
-- готовом тексте:
--
--   язык         — ответ уходит англоязычному мужчине, а модель срывается на русский;
--   [[метки]]    — это **готовый текст**, а не шаблон: `[[companion_name]]` уедет
--                  человеку как есть, и он прочтёт скобки;
--   по существу  — ответ на «Moto is my life» про погоду означает, что письмо не
--                  прочли; это главное, ради чего шаг и заведён;
--   безопасность — обещания встреч, просьбы денег, контакты вне сайта.
--
-- ⚠ РЕШАЕТ МОДЕЛЬ, А НЕ РЕГУЛЯРКА. Три из четырёх вопросов нельзя задать проверкой
-- по образцу: «отвечает ли текст на письмо» — это про смысл. Метки можно было бы
-- ловить регуляркой, но заводить ради одного из четырёх второй механизм проверки
-- дороже, чем задать четвёртый вопрос там же.
--
-- ⚠ ТРИ ПОПЫТКИ, ПОТОМ ОТДАЁМ КАК ЕСТЬ. Тот же предел, что у `dating_mail_write`.
-- Бесконечный круг переписывания — это агент, который молчит навсегда; ответ,
-- прошедший не все проверки, всё равно лежит в пуле и ждёт человека, а не уходит
-- сам. Цена ошибки здесь ниже, чем цена молчания.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_reply');
SET @write = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Ответ');
SET @done = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'Готово');

SELECT 'ДО' AS этап, @wf AS workflow, @write AS шаг_ответа, @done AS шаг_готово,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ── Шаг «Проверка»: годится ли ответ ─────────────────────────────────────────
--
-- Ставим его между «Ответом» и «Готово»: позиции сдвинем ниже.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 2, 'Проверка', 1, CAST(CONCAT('{"prompt_user": ', JSON_QUOTE(CONCAT(
    'Проверь ЧУЖОЙ ответ перед отправкой. Отвечает девушка мужчине на сайте знакомств.',
    CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '=== Переписка ===', CHAR(10 USING utf8mb4),
    '%mail_history%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '=== Ответ на проверку ===', CHAR(10 USING utf8mb4),
    '%reply%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    'Ответь по каждому пункту 1 (годится) или 0 (нет):', CHAR(10 USING utf8mb4),
    'reply_lang_ok — ответ целиком на языке %user_language%? Имена и города не в счёт.',
    CHAR(10 USING utf8mb4),
    'reply_clean_ok — в ответе НЕТ переменных в квадратных скобках вида [[имя]]? Это готовый текст, а не шаблон: скобки уедут человеку как есть.',
    CHAR(10 USING utf8mb4),
    'reply_topic_ok — ответ по существу ПОСЛЕДНЕГО письма? Он должен подхватывать то, о чём человек написал или спросил, а не отвечать общими словами мимо темы.',
    CHAR(10 USING utf8mb4),
    'reply_safe_ok — в ответе НЕТ обещаний встречи, просьб о деньгах, ссылок и контактов вне сайта (почта, мессенджеры, телефон)?',
    CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '⚠ Суди строго, но не придирайся к стилю: короткий или простой ответ — это нормально. Ноль ставь только там, где правило нарушено.',
    CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    'Верни JSON: {"reply_lang_ok": 1, "reply_clean_ok": 1, "reply_topic_ok": 1, "reply_safe_ok": 1}')),
    ', "transitions_after": [',
    -- ⚠ Любое «нет» уводит на счётчик попыток; он решит, переписывать или сдаться.
    '  {"value": "0", "step_id": "%TRY%", "operator": "==", "variable": "reply_lang_ok"},',
    '  {"value": "0", "step_id": "%TRY%", "operator": "==", "variable": "reply_clean_ok"},',
    '  {"value": "0", "step_id": "%TRY%", "operator": "==", "variable": "reply_topic_ok"},',
    '  {"value": "0", "step_id": "%TRY%", "operator": "==", "variable": "reply_safe_ok"}',
    '], "transitions_before": [],',
    ' "llm_to_json_variable": [',
    '  {"text": "1 — ответ на нужном языке", "variable": "reply_lang_ok"},',
    '  {"text": "1 — в ответе нет [[переменных]]", "variable": "reply_clean_ok"},',
    '  {"text": "1 — ответ по существу последнего письма", "variable": "reply_topic_ok"},',
    '  {"text": "1 — нет обещаний встреч, денег и контактов вне сайта", "variable": "reply_safe_ok"}',
    ']}') AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `id` FROM `agent_workflow_step`
                                   WHERE `workflow_id` = @wf AND `title` = 'Проверка') AS x);

SET @check = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Проверка');

-- ── Шаг «Попытка»: считает заходы ────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 3, 'Попытка', 2,
       CAST('{"tool_invoke": {"tool_name": "counter_increment",
                              "inputs_map": {"value": "reply_try"}, "outputs_map": {}},
              "transitions_after": [], "transitions_before": []}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `id` FROM `agent_workflow_step`
                                   WHERE `workflow_id` = @wf AND `title` = 'Попытка') AS x);

SET @try = (SELECT `id` FROM `agent_workflow_step`
             WHERE `workflow_id` = @wf AND `title` = 'Попытка');

-- ── Шаг «Что не так»: собирает замечание и возвращает на переписывание ───────
--
-- ⚠ Замечание собирается **из тех же переменных**, что проверял шаг выше: модель
-- получает не «перепиши лучше», а список того, что именно не сошлось. Пустое
-- замечание («перепиши») даёт второй такой же ответ — это уже проверено на письмах.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 5, 'Что не так', 3, CAST(CONCAT(
    '{"transitions_after": [{"value": "3", "step_id": "', @write,
    '", "operator": "<", "variable": "reply_try"}],',
    ' "transitions_before": [],',
    ' "variable_conversion": [',
    '  {"text": "%counter_increment_', @try, '_result_int%", "variable": "reply_try"},',
    '  {"text": ', JSON_QUOTE(CONCAT(
        '%if !reply_lang_ok%ответ написан не на языке %user_language%. %endif%',
        '%if !reply_clean_ok%в ответе остались [[переменные]] в скобках — это готовый текст, впиши слова вместо них. %endif%',
        '%if !reply_topic_ok%ответ не по существу последнего письма — подхвати то, о чём он написал, а не отвечай общими словами. %endif%',
        '%if !reply_safe_ok%убери обещания встречи, просьбы о деньгах и любые контакты вне сайта. %endif%')),
    ', "variable": "reply_hint"}]}') AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `id` FROM `agent_workflow_step`
                                   WHERE `workflow_id` = @wf AND `title` = 'Что не так') AS x);

-- Подставляем настоящий номер шага «Попытка» в переходы проверки: при вставке его
-- ещё не существовало.
UPDATE `agent_workflow_step`
   SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR), '%TRY%', @try) AS JSON)
 WHERE `id` = @check;

-- «Готово» уезжает в конец: между ним и «Ответом» теперь три шага.
UPDATE `agent_workflow_step` SET `position` = 4 WHERE `id` = @done;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' → ')
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS порядок,
       (SELECT CAST(`metadata` AS CHAR) LIKE '%"step_id": "%'
          FROM `agent_workflow_step` WHERE `id` = @check) AS переходы_на_месте;
