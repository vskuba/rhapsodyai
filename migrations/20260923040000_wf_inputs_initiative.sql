-- Переменные инициативы: их не было в реестре вовсе (2026-09-23)
--
-- ЗАЧЕМ. `20260923030000_wf_inputs_declared` объявил входящими то, что шлют
-- вызывающие, — но он умел только **менять тип** уже существующим. А
-- `make_initiative` и `initiative_kind` в реестре не значились никогда: их
-- клали в запрос, они молча ложились в сборку и работали.
--
-- Ровно та дыра, которую закрывает эта пара миграций: переменная работает, не
-- будучи объявленной нигде. Промпт шага 12 её читает (`%if make_initiative%`),
-- а в реестре её нет — то есть на странице workflow она невидима.
--
-- ⚠⚠ Нашёл это **тест**, а не чтение кода: `test_chat_variables_allowed.py`
-- сверяет список, который шлёт DatingAi, со списком объявленного. Без него
-- запрет из `chat.py` отверг бы живой вызов инициативы, и узналось бы это на
-- проде — молчанием круга, который «почему-то перестал писать первым».
--
-- Идемпотентность: заведение проверкой на наличие.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('make_initiative', 'initiative_kind')) AS есть;

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'make_initiative', 'input', '',
       'Заговорить первой: 1 — это не ответ, а обращение после молчания; пусто или 0 — обычный ответ. Кладёт DatingAi'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'make_initiative');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'initiative_kind', 'input', '',
       'Приём инициативы, выбранный панелью жребием: «будь разной» модель не понимает, и три текста из трёх выходят на один лад'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'initiative_kind');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('make_initiative', 'initiative_kind')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

SELECT 'ПОСЛЕ' AS этап, v.`name`, v.`type`
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow_variable_workflow` vw ON vw.`variable_id` = v.`id`
 WHERE vw.`workflow_id` = @wf AND v.`name` IN ('make_initiative', 'initiative_kind');
