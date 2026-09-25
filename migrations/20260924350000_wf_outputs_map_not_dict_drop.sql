-- `outputs_map` снимается там, где инструмент словаря не возвращает (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `outputs_map` отвечает на вопрос **«какое из полей словаря куда положить»**:
--
--     инструмент вернул   {"list": [...], "qty": 3, "str": "a,b,c"}
--     движок положил      text_marks_missing_1321_result_list
--                         text_marks_missing_1321_result_qty
--                         text_marks_missing_1321_result_str
--     outputs_map         «возьми тот, что под ключом str, назови letter_marks_missing»
--
-- У инструмента, возвращающего строку, число или логическое, полей нет. Выбирать
-- не из чего, и движок такое объявление не читает вовсе — раздача имён написана
-- внутри ветки словаря (`ai_framework_manager.py`).
--
-- ⚠ Это **не изъян движка**, и правкой его чинить не надо: механизм и задуман
-- для словарей. Изъян в объявлениях — их писали по образцу соседнего шага, не
-- глядя, что возвращает функция.
--
-- ## Почему это не «мёртвый код, пусть лежит»
--
-- Лежащее объявление выглядит работающим. Пятнадцать шагов обещают переменную,
-- которой никогда не будет, и следующий, кто станет её читать, получит пустоту
-- без единого признака ошибки: шаг зелёный, значение есть — просто под машинным
-- именем.
--
-- Именно так и вышло: шаги «Разговор: чат» и «Разговор: письма» просили
-- `talk_history_chat` и `talk_history_mail`, их читают по семь шагов каждую, и
-- агент получил бы пустую историю.
--
-- ## ⚠ Отбор по данным, а не по списку номеров
--
-- Номера шагов у нас и на проде разные. Правило смотрит в реестр инструментов:
-- знаем тип ответа и он не `dict` — объявление снимаем. Инструмента в реестре
-- нет (`planning_*` заводятся иначе) — не трогаем: тип неизвестен, а гадать тут
-- нечего.
--
-- ⚠ Реестр сверен с кодом по всем одиннадцати задетым инструментам: `args`
-- собирает сканер из сигнатуры, и расхождений нет.
--
-- ## ⚠⚠ Два намерения при этом теряются, и это надо знать
--
--     dating_bot #22        text_translit_cyr_to_lat → agent_name
--     dating_girl_create #546  agent_create_or_update → girl_agent_id
--
-- Первое хотело подменить имя агента латиницей — `agent_name` читают три шага, и
-- все три сейчас видят имя из справочника, а не переложенное. Второе печатается
-- в строке итога «Агент X создан (#%girl_agent_id%)», то есть выходит как «(#)».
--
-- Ни то ни другое эта миграция не ломает — оба не работали с самого начала. Но
-- если они нужны, их надо делать заново и по-другому: шагом-конверсией из
-- машинной переменной. Снятие объявления лишь перестаёт обещать несделанное.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
          JOIN `tool` k ON k.`name` = JSON_UNQUOTE(
                 JSON_EXTRACT(s.`metadata`, '$.tool_invoke.tool_name'))
         WHERE t.`name` = 'tool_invoke' AND JSON_VALID(s.`metadata`)
           AND JSON_LENGTH(JSON_EXTRACT(s.`metadata`, '$.tool_invoke.outputs_map')) > 0
           AND JSON_UNQUOTE(JSON_EXTRACT(k.`args`, '$.output.type')) <> 'dict')
         AS объявлений_у_не_словаря;

-- ── Снятие ──────────────────────────────────────────────────────────────────
--
-- ⚠ `JSON_REMOVE` по пути, а не замена по тексту: ключ лежит внутри JSON, и
-- лесенка экранирования в SQL-литерале здесь уже однажды не сошлась — замена
-- прошла «удачно», не изменив ничего (`…_wf_talk_companion_key`).
--
-- ⚠ Повторный прогон безвреден: условие требует непустого `outputs_map`, и
-- второй раз под него никто не попадёт.
UPDATE `agent_workflow_step` s
  JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
  JOIN `tool` k ON k.`name` = JSON_UNQUOTE(
         JSON_EXTRACT(s.`metadata`, '$.tool_invoke.tool_name'))
   SET s.`metadata` = JSON_REMOVE(s.`metadata`, '$.tool_invoke.outputs_map')
 WHERE t.`name` = 'tool_invoke' AND JSON_VALID(s.`metadata`)
   AND JSON_LENGTH(JSON_EXTRACT(s.`metadata`, '$.tool_invoke.outputs_map')) > 0
   AND JSON_UNQUOTE(JSON_EXTRACT(k.`args`, '$.output.type')) <> 'dict';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
          JOIN `tool` k ON k.`name` = JSON_UNQUOTE(
                 JSON_EXTRACT(s.`metadata`, '$.tool_invoke.tool_name'))
         WHERE t.`name` = 'tool_invoke' AND JSON_VALID(s.`metadata`)
           AND JSON_LENGTH(JSON_EXTRACT(s.`metadata`, '$.tool_invoke.outputs_map')) > 0
           AND JSON_UNQUOTE(JSON_EXTRACT(k.`args`, '$.output.type')) <> 'dict')
         AS осталось_у_не_словаря,
       -- ⚠ У словарей объявления обязаны уцелеть все до одного: там механизм
       -- работает, и снятие сломало бы живые workflow.
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
          JOIN `tool` k ON k.`name` = JSON_UNQUOTE(
                 JSON_EXTRACT(s.`metadata`, '$.tool_invoke.tool_name'))
         WHERE t.`name` = 'tool_invoke' AND JSON_VALID(s.`metadata`)
           AND JSON_LENGTH(JSON_EXTRACT(s.`metadata`, '$.tool_invoke.outputs_map')) > 0
           AND JSON_UNQUOTE(JSON_EXTRACT(k.`args`, '$.output.type')) = 'dict')
         AS цело_у_словарей,
       -- ⚠ Подпрогоны не задеты вовсе: у `workflow_invoke` свой `outputs_map`,
       -- он перекладывает переменные ребёнка родителю и со словарями не связан.
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
         WHERE t.`name` = 'workflow_invoke'
           AND s.`metadata` LIKE '%outputs_map%') AS цело_у_подпрогонов;
