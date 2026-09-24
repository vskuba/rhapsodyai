-- Список переменных у веток лежал строкой вместо массива (2026-09-24)
--
-- ## ⚠⚠ ЧТО СЛОМАЛОСЬ
--
-- Три ветки сочинения — «Письмо первым», «Ответ на письмо», «Инициатива» — падали
-- на каждом заходе, с рождения:
--
--     AttributeError: 'str' object has no attribute 'get'
--     ai_framework_manager.py:502
--     expect_variables = [x.get('variable') for x in _llm_to_json_vars …]
--
-- Движок ждёт в `llm_to_json_variable` **массив** объектов. У этих трёх шагов там
-- лежала **строка** с тем же массивом внутри, и перебор строки дал буквы.
--
-- Видно это только по типу, не по глазам: в редакторе и в дампе значение
-- выглядит правильным, отличаясь лишь кавычками вокруг.
--
--     «Ответ в чат»      ARRAY   [{"text": "…", "variable": "girl_response"}]
--     «Письмо первым»    STRING  "[{\"text\": \"…\", \"variable\": …}]"
--
-- ## ⚠⚠ ОТКУДА ВЗЯЛОСЬ: пользовательская переменная не держит JSON
--
-- Ветки заведены миграцией `…010000_wf_talk_branches`, и она копировала список у
-- работающего шага чата — через промежуточную переменную:
--
--     SET @json = (SELECT JSON_EXTRACT(`metadata`, '$.llm_to_json_variable') …);
--     …  JSON_OBJECT('llm_to_json_variable', @json, …)
--
-- **Пользовательская переменная MySQL не хранит тип JSON.** `SET @json = …`
-- сворачивает значение в текст, и `JSON_OBJECT` кладёт его как обычную строку —
-- со всеми кавычками внутри. Ошибки при этом нет: обе стороны сделали ровно то,
-- о чём их попросили.
--
-- ⚠ Лечится `CAST(@json AS JSON)` на входе в `JSON_OBJECT` — либо тем, что
-- значение вовсе не проходит через переменную.
--
-- ⚠⚠ **Это родня той же ловушки, что и `Illegal mix of collations`**: там
-- `@переменная` теряла сличение, здесь теряет тип. Общее правило одно —
-- пользовательская переменная годится **перенести число или короткий текст**, а
-- всё, у чего есть тип, через неё возить нельзя.
--
-- ## ⚠ Почему сверка баз это пропустила
--
-- Снимок сравнивал `metadata` **как текст**, и обе базы были испорчены
-- одинаково: прод и рабочая совпали до знака. Совпадение баз не означает, что
-- обе верны, — оно означает только, что они одинаковы.
--
-- ## Цена
--
-- Ветки не работали ни разу с рождения: письма избранным не сочинялись вовсе, а
-- прогон кончался отказом (трасса #40192 на проде, 2026-09-24 10:14). Ветка чата
-- цела — её `llm_to_json_variable` никто не переписывал.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап, COUNT(*) AS строкой_вместо_массива
  FROM `agent_workflow_step`
 WHERE `workflow_id` = @wf
   AND `metadata` IS NOT NULL AND `metadata` <> '' AND JSON_VALID(`metadata`)
   AND JSON_TYPE(JSON_EXTRACT(`metadata`, '$.llm_to_json_variable')) = 'STRING';

-- ── Строку разворачиваем обратно в массив ───────────────────────────────────
--
-- ⚠ Содержимое берём **из самой строки**, а не у шага чата: там оно уже могло
-- разойтись правкой, и подстановка чужого списка молча сменила бы ветке выходную
-- переменную. Правим форму, а не смысл.
--
-- ⚠ `CAST(… AS JSON)` **после** `JSON_UNQUOTE`: без снятия кавычек приведение
-- вернуло бы ту же строку, только заново упакованную.
--
-- ⚠⚠ Условие по `JSON_TYPE` держит идемпотентность **и** страхует от порчи:
-- второй прогон видит `ARRAY` и не трогает ничего. Без него повтор попытался бы
-- развернуть уже развёрнутое и получил бы отказ приведения.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.llm_to_json_variable',
         CAST(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.llm_to_json_variable'))
              AS JSON))
 WHERE `workflow_id` = @wf
   AND `metadata` IS NOT NULL AND `metadata` <> '' AND JSON_VALID(`metadata`)
   AND JSON_TYPE(JSON_EXTRACT(`metadata`, '$.llm_to_json_variable')) = 'STRING'
   AND JSON_VALID(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                                            '$.llm_to_json_variable')));

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `metadata` IS NOT NULL AND JSON_VALID(`metadata`)
           AND JSON_TYPE(JSON_EXTRACT(`metadata`,
                                      '$.llm_to_json_variable')) = 'STRING')
         AS строкой_осталось,
       -- ⚠ Мало развернуть — надо убедиться, что развернулось в **список
       -- объектов с именем переменной**: движок читает `x.get('variable')`, и
       -- массив строк уронил бы его ровно так же.
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN JSON_TABLE(JSON_EXTRACT(s.`metadata`, '$.llm_to_json_variable'),
                          '$[*]' COLUMNS (nm VARCHAR(190) PATH '$.variable')) j
         WHERE s.`workflow_id` = @wf
           AND s.`title` IN ('Письмо первым', 'Ответ на письмо', 'Инициатива')
           AND j.nm IS NOT NULL AND j.nm <> '') AS выходов_у_веток;
