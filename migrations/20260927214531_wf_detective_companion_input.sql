-- Детектив получает `companion_title` входящей: сосед больше не подставляет троицу
-- из запроса по умолчанию (`remove_companion`, 2026-09-27)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `20260924220000` снимал с троицы пометку `global`, но значения читателям всё
-- ещё клал `ai_workflow_variables_base`. Правка `remove_companion` убирает и
-- подстановку: теперь что workflow не получит запросом — то получит пустой
-- default. Значит каждому читателю, кого зовут запросом, троицу надо объявить
-- входящей — иначе его шаги читают сырой `%companion_title%`.
--
-- Детектив читает только `companion_title` (шаг 141 бота: «игрок пишет», шаг 136
-- допроса: «=== %companion_title% спрашивает ===`; имя и номер игрока шагам не
-- нужны) — поэтому связываем с 12 и 13 только запись 72, не всю троицу.
-- Подозреваемые (14) объявляли свою (158) и получают значение через
-- `inputs_map` родителя (шаг 140) — её не трогаем.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` = 72 AND `workflow_id` IN (12, 13)) AS связей_с_детективом;

-- ⚠ По номеру записи (72), а не по имени: `companion_title` живёт в реестре
-- несколькими записями (72, 80, 158) и правка по имени задела бы чужие.
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT one.`vid`, one.`wid` FROM (
             SELECT 72 AS vid, 12 AS wid
    UNION SELECT 72     AS vid, 13 AS wid
) AS one
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = one.`vid` AND x.`workflow_id` = one.`wid`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` = 72 AND `workflow_id` IN (12, 13)) AS связей_с_детективом,
       -- Чужим (5, 6, 7, 14, 2044) объявлений правка не прибавила.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` = 72 AND `workflow_id` NOT IN (12, 13)) AS связей_с_остальными;
