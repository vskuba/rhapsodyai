-- `dating_mail_write`: зачин письма — тоже жребий (2026-09-18)
--
-- ЧТО ПОКАЗАЛ ЖИВОЙ ПУЛ. Восемь шаблонов подряд, написанных сегодня, начинались
-- одинаково: словом «Hi» с новой строки, дальше пустая строка и текст. Приём был
-- разный, длина разная, рассказ разный — а первое, что видит человек, одно и то
-- же во всех письмах сайта.
--
-- ⚠ ЭТО ТА ЖЕ БЕДА, ЧТО И «YOU'RE TROUBLE» У ИНВАЙТОВ, И ЛЕЧИТСЯ ТАК ЖЕ. Модель
-- зачин не выбирает: она берёт первый попавшийся и повторяет его, пока её не
-- попросят иначе — а «начинай по-разному» это просьба того же рода, что «будь
-- разной». Жребий бросает панель:
--
--   `mail_greeting`  приём зачина: приветствие с именем, без имени, имя внутри
--                    первой фразы, оклик, мысль вслух, признание о неловкости;
--   пусто            приветствия НЕТ вовсе — письмо начинается сразу с мысли.
--                    Доля настраивается, по умолчанию 15%.
--
-- ⚠ ОПИСЫВАЕТСЯ ПРИЁМ, А НЕ ТЕКСТ. Дай образец («начни с Hey») — получишь «Hey»
-- во всех письмах, где выпал этот пункт, то есть ту же беду в профиль.
--
-- ⚠ ЗАПРЕТ ФОРМУЛИРУЕТСЯ ПРЯМО, а не молчанием. Урок сегодняшнего дня: жребий
-- «без вопроса» сперва выключал вопрос, просто не упоминая его, — и модель
-- дописала вопрос сама, в трёх шаблонах из пяти. С приветствием то же самое:
-- пустая секция без запрета означала бы «Hi» по-прежнему.
--
-- Идемпотентность: промпт правится точечно, заменой одного места; переменная
-- заводится по условию отсутствия.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_greeting%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS правка_есть;

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'mail_greeting', 'workflow',
       'Приём зачина письма. Пусто — приветствия нет вовсе. Жребий бросает DatingAi'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_greeting');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'mail_greeting'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ------------------------------------------- Секция зачина в черновике
--
-- ⚠ Встаёт ПЕРЕД приёмом: зачин — первое, что модель пишет, и правило о нём
-- должно стоять раньше правил о содержании.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '=== Приём на этот раз ===\n%mail_angle%\n\n',
                 CONCAT(
                   '%if mail_greeting%=== Чем начать ===\n%mail_greeting%\n\n',
                   '%else%⚠ БЕЗ ПРИВЕТСТВИЯ. Никакого «Hi», «Hello», «Hey», ни с ',
                   'именем, ни без; ни отдельной строкой, ни внутри фразы. Письмо ',
                   'начинается сразу с мысли — так пишут тому, с кем разговор уже ',
                   'идёт, и это как раз располагает.\n\n%endif%',
                   '=== Приём на этот раз ===\n%mail_angle%\n\n')))
 WHERE `workflow_id` = @wf AND `position` = 0;

-- ------------------------------------------- Судья: одинаковый зачин — повтор
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '1. Тот же зачин: письмо начинается той же мыслью или почти теми же ',
                 CONCAT(
                   '0. Письмо начинается тем же словом, что и прошлые: «Hi» после ',
                   '«Hi», «Hello» после «Hello». Первое слово человек видит раньше ',
                   'всего остального, и одинаковое во всех письмах сайта оно ',
                   'заметнее любого повтора в теле.\n',
                   '1. Тот же зачин: письмо начинается той же мыслью или почти теми же ')))
 WHERE `workflow_id` = @wf AND `position` = 8;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_greeting%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS зачин_у_черновика,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%БЕЗ ПРИВЕТСТВИЯ%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS запрет_есть,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%тем же словом%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 8) AS зачин_у_судьи;
