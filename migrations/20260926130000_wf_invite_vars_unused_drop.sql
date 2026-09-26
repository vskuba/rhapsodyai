-- Инвайты: снимаем входящие переменные, которых промпты больше не читают (2026-09-26)
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека)
--
-- Прошлая миграция (`…120000_wf_invite_one_dice`) перенесла вероятности в шаг
-- жребия, и пять входящих переменных осиротели: панель их присылает, обёртка
-- передаёт в подвызов, а **ни один промпт их не читает**.
--
--     invite_angle    приём — бросает dice_invite_angle
--     invite_length   длина — dice_invite_length
--     invite_slots    метки имён — dice_invite_man_name и dice_invite_girl_name
--     invite_time     время — dice_invite_time
--     invite_country  «Откуда ты» — этой секции в промпте нет вовсе
--
-- ⚠ Объявленная, но не читаемая переменная — не безвредный мусор: она обещает
-- влияние, которого нет. Человек, увидев её в реестре, будет искать, чем её
-- задать, и задаст — а в промпте ничего не изменится.
--
-- ## ⚠ Что НЕ убирается, хотя выглядит похоже
--
-- `invite_name_percent`, `invite_time_percent`, `invite_girl_name_percent`
-- **остаются**: их читает сам жребий — они стоят долями в его `spec`. Это и есть
-- граница правила «удаляем то, чего не читают»: читает не промпт, а инструмент.
--
-- `invite_avoid`, `invite_done`, `datetime_current_get_zone` остаются — читаются.
--
-- ## ⚠⚠ Убирать надо по ВСЕЙ цепочке, иначе половина останется
--
--     панель → dating_invite_write → шаг «Цикл» (workflow_invoke.inputs_map)
--            → dating_invite_one
--
-- Мест, где переменная упомянута, три: объявление у ребёнка, объявление у обёртки
-- и **карта доводов подвызова**. Сними только объявления — карта продолжит гнать
-- значения в ребёнка, где их никто не ждёт; сними только карту — реестр будет
-- врать про влияние. Поэтому три шага ниже, и порядок в них обратный цепочке:
-- сперва карта, потом объявления.
--
-- ## ⚠ Сами переменные из справочника НЕ удаляются
--
-- Только их привязка к этим двум workflow. `agent_workflow_variable` — общий
-- справочник: та же строка может быть привязана к чужому workflow, о котором эта
-- миграция ничего не знает. Осиротевшую строку уберёт общая чистка, если
-- понадобится; молча снести её отсюда значило бы решать за чужой workflow.

SET @one = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_one');
SET @wrap = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');

SELECT 'ДО' AS этап, @one AS ребёнок, @wrap AS обёртка,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` IN (@one, @wrap)
           AND v.`name` IN ('invite_angle', 'invite_length', 'invite_slots',
                            'invite_time', 'invite_country')) AS привязок,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wrap
           AND JSON_EXTRACT(`metadata`, '$.workflow_invoke') IS NOT NULL
         LIMIT 1) AS доводов_подвызова;

-- ── 1. Карта доводов подвызова ──────────────────────────────────────────────
--
-- ⚠ `JSON_REMOVE` умеет несколько путей за раз, и это важно: убирай их по одному
-- отдельными запросами — после первого удаления ключи не сдвигаются (это объект, а
-- не массив), но каждый запрос читал бы и писал весь документ заново.
--
-- ⚠⚠ Ключи объекта, а не элементы массива — порядок не важен, промаха «удалили не
-- то, потому что сдвинулось» здесь не бывает. У массива он был бы (этим уже
-- ошибались с позициями шагов).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REMOVE(`metadata`,
         '$.workflow_invoke.inputs_map.invite_angle',
         '$.workflow_invoke.inputs_map.invite_length',
         '$.workflow_invoke.inputs_map.invite_slots',
         '$.workflow_invoke.inputs_map.invite_time',
         '$.workflow_invoke.inputs_map.invite_country')
 WHERE `workflow_id` = @wrap
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map') IS NOT NULL;

-- ── 2. Объявления у обоих workflow ──────────────────────────────────────────
DELETE vw FROM `agent_workflow_variable_workflow` vw
  JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
 WHERE vw.`workflow_id` IN (@one, @wrap)
   AND v.`name` IN ('invite_angle', 'invite_length', 'invite_slots',
                    'invite_time', 'invite_country');

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Привязок не остаётся ни одной — это и есть цель.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` IN (@one, @wrap)
           AND v.`name` IN ('invite_angle', 'invite_length', 'invite_slots',
                            'invite_time', 'invite_country')) AS привязок,
       -- ⚠ И в карте подвызова их нет: осталось три довода из восьми.
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wrap
           AND JSON_EXTRACT(`metadata`, '$.workflow_invoke') IS NOT NULL
         LIMIT 1) AS доводов_подвызова,
       -- ⚠⚠ Доли жребия уцелели: они читаются инструментом, а не промптом, и под
       -- правило «убрать нечитаемое» не попадают. Потеряй их — жребий отказал бы
       -- на первом же заходе («доля не число»).
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @one
           AND v.`name` IN ('invite_name_percent', 'invite_time_percent',
                            'invite_girl_name_percent')) AS доли_жребия,
       -- ⚠ Читаемые входящие на месте.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @one
           AND v.`name` IN ('invite_avoid', 'datetime_current_get_zone')) AS читаемые;
