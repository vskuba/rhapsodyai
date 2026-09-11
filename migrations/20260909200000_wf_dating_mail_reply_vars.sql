-- `dating_mail_reply`: объявление переменных workflow (2026-09-09)
--
-- ЧТО СЛОМАЛОСЬ. Прошлая миграция добавила шаг проверки со счётчиком попыток, и
-- первый же прогон упал:
--
--     int() argument must be ... not 'NoneType'
--
-- `counter_increment` читает `reply_try`, а её нет: переменные workflow объявляются
-- отдельно, в `agent_workflow_variable`, и без объявления движок отдаёт `NULL`.
--
-- ⚠ ПОЧЕМУ ЭТО НЕ ВИДНО БЫЛО РАНЬШЕ. До шага проверки workflow обходился теми
-- переменными, что кладёт вызывающий (`mail_history`, `girl_card`, `companion_card`):
-- их движок берёт из запроса, и объявления им не нужно. Счётчик же и замечание —
-- **внутренние**: их не передаёт никто, они рождаются посреди прогона. У
-- `dating_mail_write` они объявлены с умолчаниями (`write_try` = 0, `write_hint` =
-- пусто) — там на этих же граблях уже стояли.
--
-- ⚠ УМОЛЧАНИЯ ЗДЕСЬ НЕСУТ СМЫСЛ, А НЕ ФОРМАЛЬНОСТЬ:
--
--   `reply_try` = 0     — первый заход это нулевая попытка, а не первая;
--   `reply_hint` пусто  — «замечаний нет», и `%if reply_hint%` в промпте молчит;
--   `*_ok` = 1          — «пока не проверяли, считаем годным»: ноль означал бы, что
--                         ответ забракован до того, как его прочли, и первый же
--                         прогон уходил бы на переписывание.
--
-- Прочие три объявляем ради умолчаний на случай, когда вызывающий их не передал:
-- пустой блок промпта хуже честного «ничего не известно» — во втором случае модель
-- знает, что сведений нет, и не выдумывает их.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_reply');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;

-- ⚠ Заводим только те, которых ещё нет: имя переменной в этой базе общее на все
-- workflow, и `dating_mail_reply` мог бы наткнуться на чужую.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT t.name, 'workflow', t.def, t.descr FROM (
    SELECT 'reply_try'      AS name, '0'  AS def,
           'Счётчик попыток переписать ответ; три — и отдаём как есть' AS descr
    UNION ALL SELECT 'reply_hint', '',
           'Что не так с ответом — собирается шагом «Что не так» для переписывания'
    UNION ALL SELECT 'reply_lang_ok', '1',
           '1 — ответ на нужном языке. Умолчание 1: не проверяли — не браковали'
    UNION ALL SELECT 'reply_clean_ok', '1',
           '1 — в ответе нет [[переменных]]: это готовый текст, а не шаблон'
    UNION ALL SELECT 'reply_topic_ok', '1',
           '1 — ответ по существу последнего письма, а не общими словами мимо темы'
    UNION ALL SELECT 'reply_safe_ok', '1',
           '1 — нет обещаний встреч, просьб о деньгах и контактов вне сайта'
    UNION ALL SELECT 'mail_history', '(переписки нет)',
           'Переписка, старые сверху: «Он: …» / «Она: …». Режет её вызывающий'
) AS t
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `name` FROM `agent_workflow_variable`) AS v
                    WHERE v.`name` = t.name);

-- Привязываем к workflow — и те, что завели сейчас, и те, что уже были в базе.
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('reply_try', 'reply_hint', 'reply_lang_ok', 'reply_clean_ok',
                    'reply_topic_ok', 'reply_safe_ok', 'mail_history',
                    -- Эти две уже объявлены для письма и вопроса; здесь нужна
                    -- только связь с нашим workflow.
                    'girl_card', 'companion_card')
   AND NOT EXISTS (SELECT 1 FROM (SELECT `variable_id`, `workflow_id`
                                    FROM `agent_workflow_variable_workflow`) AS x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = @wf);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;

SELECT v.`name`, v.`default`
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow_variable_workflow` vw ON vw.`variable_id` = v.`id`
 WHERE vw.`workflow_id` = @wf ORDER BY v.`name`;
