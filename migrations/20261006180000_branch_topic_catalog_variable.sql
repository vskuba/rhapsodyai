-- Словарь меток тем — глобальной переменной в реестре (2026-10-06)
--
-- ЗАЧЕМ. `%branch_topic_catalog%` кладёт движок на старте прогона: это весь
-- список меток включённых тем ноды, из которого шаг-развилка выбирает подходящие.
-- Значение приходит из реестра веток, а не из этой записи.
--
-- ⚠⚠ Но без записи переменной **не видно в списках редактора**, и человек пишет
-- метку вслепую. Ровно это и случилось: промпт развилки `dating_talk` просил
-- модель придумать метки свободно, она и придумала — `photo request`,
-- `personal boundaries`, `deflection`, — а в теме лежат `send photos`,
-- `show photo`. Совпадений ноль, тема не выбиралась ни разу, и девушка
-- отказывала прислать фото, хотя тема велит соглашаться.
--
-- ⚠ Приём не новый: `user_language`, `node_languages`, `session_uuid` — такие же
-- служебные значения движка, и у всех есть объявление `type = 'global'` с пустым
-- `workflow_id`. Здесь то же самое.
--
-- ⚠ Имя с приставкой `branch_`: в списке переменных рядом с `topic_*` шага ветки
-- «topic_catalog» читался бы как восьмая переменная темы, а он про весь реестр
-- ноды и живёт раньше любой ветки.

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT NULL, 'branch_topic_catalog', 'global', '',
       'Метки всех включённых тем ноды через запятую. Кладёт движок на старте прогона; из этого списка шаг-развилка выбирает подходящие, своих не придумывая'
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) x
                    WHERE x.`name` = 'branch_topic_catalog' AND x.`workflow_id` IS NULL);

SELECT 'ГОТОВО' AS этап,
       (SELECT `id` FROM `agent_workflow_variable`
         WHERE `name` = 'branch_topic_catalog' AND `workflow_id` IS NULL) AS номер;
