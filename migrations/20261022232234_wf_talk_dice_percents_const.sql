-- Три доли жребия переезжают в сам шаг: панель их больше не присылает (2026-10-22)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- У `dating_talk` три оси жребия брали долю **снаружи**, меткой:
--
--     "dice_mail_name":     {"say his name once…": "%dice_mail_name_percent%",     "…": "rest"}
--     "dice_mail_question": {"end the letter with a question…": "%dice_mail_question_percent%", "…": "rest"}
--     "dice_mail_story_on": {"0": "rest", "1": "%dice_mail_story_percent%"}
--
-- Значения ехали из DatingAi переменными вызова, а крутились там настройками
-- сайта `favorite_mail_name_percent`, `_question_percent`, `_story_percent`.
-- Выходило, что одна грань разнообразия стоит **четырёх мест**: реестр настроек,
-- код панели, объявление входящей переменной, описание жребия. Разойтись они
-- могли молча — ровно та беда, ради которой жребий и заводился рядом с промптом.
--
-- ⚠⚠ Разделение не окупилось ни разу: на проде **ни один из трёх живых сайтов**
-- эти ручки не трогал, и панель слала умолчания — те же 10, 25 и 40, что стоят
-- в `default` самих объявлений. Поэтому числа ниже — не новое решение, а ровно
-- то, что работало; поведение жребия этой миграцией не меняется.
--
-- ## ⚠⚠ Порядок: эта миграция идёт ПОСЛЕ выкладки DatingAi
--
-- Сторож `chat.py:_variables_allowed` отвергает **весь** вызов `/chat/ask` с
-- `400` по любому необъявленному имени. Сними объявления раньше, чем панель
-- перестанет их слать, — встанут все четыре ветки `dating_talk`, включая обычный
-- ответ в чат. Это уже случалось: 03.10.2026 — 91 отказ за 35 минут.
--
-- Правок у переезда три, и эта последняя:
--     1. DatingAi: `answer.py` не шлёт доли, `site_setting.py` не держит ключей;
--     2. RhapsodyAi: `tests/test_chat_variables_allowed.py`, список `DATING_SENDS`;
--     3. эта миграция: числа в шаг, объявления вон.
--
-- ## ⚠ Почему заменой по метке, а не переписыванием спецификации
--
-- Спецификация жребия — 15 КБ с десятком осей, и правили её руками в панели: на
-- проде и локально тексты вариантов расходятся. Замена трёх меток на числа ведёт
-- себя одинаково в обеих базах и не везёт чужую незаконченную работу. Повтор
-- миграции безвреден: метки после первого прогона уже нет.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @dice = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'dice' LIMIT 1);

SELECT 'ДО' AS этап,
       COALESCE(@dice, 0) AS шаг_жребия,
       (SELECT LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')))
          FROM `agent_workflow_step` WHERE `id` = @dice) AS длина_спецификации,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `workflow_id` = @wf
           AND `name` IN ('dice_mail_name_percent', 'dice_mail_question_percent',
                          'dice_mail_story_percent')) AS объявлений;

-- ── 1. Доли становятся числами ──────────────────────────────────────────────
--
-- ⚠ Заменяется метка **вместе с кавычками**: доля вправе быть и числом, и
-- строкой, но числом она честнее — видно, что снаружи её больше никто не
-- подставляет.
--
-- ⚠⚠ Три `UPDATE`, а не один вложенный `REPLACE(REPLACE(REPLACE(…)))`: при
-- отказе видно, какая ось не переехала, а повтор каждой стоит ровно ничего.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.spec',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                   '$.tool_invoke.inputs_map.spec')),
                 '"%dice_mail_name_percent%"', '10'))
 WHERE `id` = @dice AND @dice IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.spec',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                   '$.tool_invoke.inputs_map.spec')),
                 '"%dice_mail_question_percent%"', '25'))
 WHERE `id` = @dice AND @dice IS NOT NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.spec',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                   '$.tool_invoke.inputs_map.spec')),
                 '"%dice_mail_story_percent%"', '40'))
 WHERE `id` = @dice AND @dice IS NOT NULL;

-- ── 2. Объявления входящих уходят — но только если метки вправду заменились ──
--
-- ⚠ Только у `dating_talk`: имя `dice_mail_*_percent` могло бы завестись и у
-- соседнего workflow, и чужое объявление не наше дело.
--
-- ⚠⚠ **Условие обязательно, и оно про расхождение баз.** Спецификацию шага
-- правят руками в панели, и прод от локальной отличается: не совпади текст
-- метки — замена выше не сделает ничего, а объявления уйдут, и метка останется
-- без значения. Жребий ответил бы отказом на каждом заходе — то есть молчанием
-- всех четырёх веток. С условием неудачная замена безвредна: объявления на
-- месте, доли по-прежнему приезжают их умолчаниями, а `SELECT` ниже покажет
-- `метки_остались` и `объявлений = 3`.
DELETE FROM `agent_workflow_variable`
 WHERE `workflow_id` = @wf
   AND `name` IN ('dice_mail_name_percent', 'dice_mail_question_percent',
                  'dice_mail_story_percent')
   AND (SELECT INSTR(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 'dice_mail_name_percent')
             + INSTR(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 'dice_mail_question_percent')
             + INSTR(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 'dice_mail_story_percent')
          FROM `agent_workflow_step` WHERE `id` = @dice) = 0;

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Меток не осталось ни одной: уцелевшая значит «такой переменной в
       -- заходе нет», и жребий отвечает отказом прямо на заходе.
       --
       -- ⚠ Считаем `INSTR`-ом по трём именам, а не `LIKE '%_percent%'`:
       -- подчёркивание в `LIKE` — подстановочный знак, и такое условие нашлось
       -- бы на любом тексте.
       (SELECT INSTR(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 'dice_mail_name_percent')
             + INSTR(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 'dice_mail_question_percent')
             + INSTR(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 'dice_mail_story_percent')
          FROM `agent_workflow_step` WHERE `id` = @dice) AS метки_остались,
       -- ⚠ Длина спецификации — что ничего, кроме трёх меток, не уехало.
       (SELECT LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')))
          FROM `agent_workflow_step` WHERE `id` = @dice) AS длина_спецификации,
       -- ⚠ Сама спецификация обязана остаться годным JSON: `JSON_VALID` по
       -- тексту без приставки `_const_`.
       (SELECT JSON_VALID(SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')), 8))
          FROM `agent_workflow_step` WHERE `id` = @dice) AS спецификация_годна,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `workflow_id` = @wf
           AND `name` IN ('dice_mail_name_percent', 'dice_mail_question_percent',
                          'dice_mail_story_percent')) AS объявлений;
