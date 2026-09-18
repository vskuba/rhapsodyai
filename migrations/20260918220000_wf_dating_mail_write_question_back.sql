-- `dating_mail_write`: вопрос снова просят всегда — жребий уехал на сборку (2026-09-18)
--
-- ЧТО БЫЛО НЕ ТАК. Сегодня утром здесь появилась развилка `%if mail_question%`:
-- панель бросала жребий и говорила шаблону, кончаться ему вопросом или нет.
--
-- Жребий стоял не в том месте, и заказчик назвал это точно: доля означала «в
-- скольких ШАБЛОНАХ», а читается она как «в скольких ПИСЬМАХ» — и читается
-- правильно. Настройка про деньги: персональный вопрос считает
-- `dating_mail_question` **отдельным вызовом на каждого адресата**. Выпало на
-- шаблоне — платит каждое письмо по нему; не выпало — не платит ни одно.
--
-- Замер на проде, 48 писем одним заходом: без вопроса 0 секунд на письмо, с
-- вопросом 11. Вот это и есть цена, и распоряжаться ею надо по письму.
--
-- ЧТО СТАЛО. Шаблон несёт метку `[[question_to_companion]]` ВСЕГДА, как и до
-- утренней затеи. Решение принимается при сборке письма: выпало — панель
-- спрашивает вопрос у агента, не выпало — вырезает абзац с меткой и не платит
-- ничего (`mailing._body`, `mail.mail_mark_drop`).
--
-- ⚠ Поэтому развилка отсюда убирается, а на её месте — прямое правило: вопрос
-- ставится ПЕРЕМЕННОЙ и своими словами не пишется. Иначе вышло бы два вопроса в
-- одном письме: свой в тексте и подставленный в абзаце.
--
-- ⚠ Переменная `mail_question` в базе остаётся — привязка к workflow снимается.
-- Заводить её обратно, если жребий однажды вернётся сюда, дешевле, чем искать,
-- куда она делась.
--
-- Идемпотентность: правка точечная, по наличию развилки.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_question%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS развилка_есть;

-- ------------------------------------------- Развилка → прямое правило
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 CONCAT(
                   '%if mail_question%ВОПРОС: письмо кончается одним вопросом к ',
                   'нему. Не тремя: три вопроса это анкета, а не письмо.\n\n',
                   '%else%⚠ ВОПРОСА НЕ НУЖНО — ни переменной, ни своими словами. ',
                   'Не «what do you enjoy?», не «what made you smile today?», не ',
                   'вопрос в конце и не вопрос в середине. Закончи утверждением, ',
                   'признанием или рассказом: на такое отвечают не хуже, а ',
                   'человеку, которому пишут первыми, допрос ни к чему.\n\n%endif%'),
                 CONCAT(
                   'ВОПРОС: письмо кончается переменной-вопросом отдельным ',
                   'абзацем — той, чья подпись про вопрос. Своими словами вопроса ',
                   'НЕ пиши: ни «what do you enjoy?», ни «what made you smile ',
                   'today?», ни в конце, ни в середине. Иначе вопросов выйдет два ',
                   '— твой и подставленный, — и письмо превратится в анкету.\n\n')))
 WHERE `workflow_id` = @wf AND `position` = 0;

-- ------------------------------------------- Переменная отвязывается
DELETE vw FROM `agent_workflow_variable_workflow` vw
  JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
 WHERE vw.`workflow_id` = @wf AND v.`name` = 'mail_question';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_question%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS развилка_осталась,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%переменной-вопросом отдельным абзацем%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS правило_есть,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @wf AND v.`name` = 'mail_question') AS привязка_осталась;
