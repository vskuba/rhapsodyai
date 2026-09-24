-- Собеседник перестаёт быть глобальным: это данные запроса (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `companion_id`, `companion_name`, `companion_title` стояли с пометкой
-- `global` — «одинаковы во всех workflow, и workflow на них рассчитывает».
-- Это неверно: **чат стейтлесс**. Значения берутся из **запроса** — движок
-- достаёт их по `companion_id`, который прислал вызывающий. Не пришли бы —
-- брать их неоткуда.
--
-- ## ⚠ Что пометка `global` вправду делает
--
-- Значение кладёт `ai_workflow_variables_base` **в любом случае**, независимо от
-- пометки. Она отвечает за два других вопроса:
--
--     chat.py:76    что вызывающему РАЗРЕШЕНО присылать (иначе 400)
--     chat.py:219   что ОБЯЗАНО быть в заходе у любого workflow
--
-- Отсюда и цена правки: читатели **не ломаются** — значения им по-прежнему
-- кладёт движок. Меняется одно: присылать их вправе только тот workflow, где они
-- объявлены входящими.
--
-- ## ⚠⚠ Почему входящими только у `dating_talk`
--
-- Он единственный, кому их **шлют**: `answer.py` кладёт их через
-- `companion_vars`, перебивая движковые, — потому что у дейтинга собеседник свой,
-- с сайта знакомств, а не запись в реестре соседа.
--
-- Остальные восемь workflow (`dating_invite_one`, `detective_bot`,
-- `girl_fact_invent`, `workflow_shell_test` и прочие) их только **читают** —
-- и продолжат читать. Заводить им объявление значило бы обещать то, чего никто
-- не присылает.
--
-- ⚠ У подпрогонов (`companion_fact_extract`, `girl_fact_invent`,
-- `detective_suspect_create`) свои `input`-записи с теми же именами (id 80, 81,
-- 158) — их не трогаем: подпрогон получает значение от родителя через
-- `inputs_map`, и это отдельный договор.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `id` IN (71, 72, 73) AND `type` = 'global') AS глобальных,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` IN (71, 72, 73) AND `workflow_id` = 5) AS связей_с_talk;

-- ── Больше не глобальные ────────────────────────────────────────────────────
--
-- ⚠ По номерам, а не по имени: имена не уникальны в реестре. `companion_title`
-- живёт тремя записями (72 глобальная, 80 и 158 входящие у подпрогонов), и
-- правка по имени задела бы чужие.
UPDATE `agent_workflow_variable`
   SET `type` = 'input',
       `description` = CASE `name`
         WHEN 'companion_id' THEN
           'Номер собеседника в реестре соседа. Приходит запросом: чат стейтлесс'
         WHEN 'companion_name' THEN
           'Системное имя собеседника — ключ фактов. Приходит запросом'
         WHEN 'companion_title' THEN
           'Отображаемое имя собеседника: им агент зовёт человека в тексте'
         ELSE `description` END
 WHERE `id` IN (71, 72, 73) AND `type` = 'global';

-- ── Связь с `dating_talk` ───────────────────────────────────────────────────
--
-- ⚠ `companion_id` (71) не был связан ни с кем — глобальной связь не нужна.
-- Теперь нужна: без неё панель получит `400` на попытке его прислать.
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT one.`vid`, 5 FROM (SELECT 71 AS vid UNION SELECT 72 UNION SELECT 73) AS one
 WHERE EXISTS (SELECT 1 FROM `agent_workflow_variable` v WHERE v.`id` = one.`vid`)
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = one.`vid` AND x.`workflow_id` = 5);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `id` IN (71, 72, 73) AND `type` = 'global') AS глобальных_осталось,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `id` IN (71, 72, 73) AND `type` = 'input') AS стали_входящими,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` IN (71, 72, 73) AND `workflow_id` = 5) AS связей_с_talk,
       -- ⚠ Проверка обратной стороны: у чужих workflow объявлений не появилось.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` IN (71, 72, 73) AND `workflow_id` <> 5) AS связей_с_чужими,
       -- ⚠ И записи подпрогонов целы: у них свой договор через `inputs_map`.
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `id` IN (80, 81, 158) AND `type` = 'input') AS записи_подпрогонов;
