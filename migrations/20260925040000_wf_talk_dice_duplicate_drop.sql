-- Второй «Жребий» в `dating_talk` убирается: он затирал настройки сайта (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ: два шага бросали один и тот же жребий, и побеждал худший
--
-- В `dating_talk` стояли **два** шага с инструментом `dice`:
--
--     поз. 6   «Жребий»         кладёт 6 переменных, веса — из настроек сайта
--     поз. 19  «Жребий письма»  кладёт 4 из них, веса — числом в тексте шага
--
-- Второй идёт позже, а значит **перезаписывает** первый. Итог хуже простого
-- дублирования: настройки сайта `dice_mail_name_percent`,
-- `dice_mail_question_percent`, `dice_mail_story_percent` не работали вовсе —
-- человек крутил их на странице, а жребий всё равно бросался по числам
-- `10 / 25 / 40`, вписанным в шаг.
--
-- ## Откуда взялся второй
--
-- Это след **повторного прогона** миграций. `…150000_wf_talk_dice` заводит шаг
-- «Жребий письма», а следующая за ней `…160000_wf_talk_dice_common` переименовывает
-- его в «Жребий» и переносит в начало. Защита вставки смотрит на имя
-- («нет шага с названием „Жребий письма“»), и после переименования она снова
-- пропускает вставку — второй прогон заводит шаг заново.
--
-- ⚠ Поэтому на проде, где миграции прошли **по одному разу**, шага было 32, а
-- локально и на репетиционной копии (прогон дважды) — 33. Сверка «по числу шагов»
-- этого не показывала: обе стороны были одинаково неверны.
--
-- ## ⚠⚠ Ищем шаг по УСТРОЙСТВУ, а не по имени
--
-- По названию — нельзя, оно и есть источник беды: имена этих двух шагов менялись
-- миграциями и правились руками. Приметa лишнего надёжнее: он кладёт
-- `dice_mail_*`, но **не кладёт** `dice_initiative_kind` — тот появился только в
-- общем жребии.
--
-- ## ⚠ Переменные проверены: ничего не теряется
--
--     переменная               кладёт поз.6   кто читает
--     dice_mail_opening        да             поз.21
--     dice_mail_name           да             поз.21, 22
--     dice_mail_question       да             поз.21, 22
--     dice_mail_story          да             поз.21, 22
--     dice_mail_story_on       да             поз.21, 22
--     dice_initiative_kind     да             поз.23
--
-- Все шесть кладёт шаг 6, все читатели стоят **после** него. Ссылок на удаляемый
-- шаг нет ни в переходах (`step_id`), ни в именах переменных (`_<номер>_result`) —
-- проверено запросом до удаления.
--
-- ⚠ Позиции после удаления **не сдвигаются**: переходы прыгают по `step_id`, а не
-- по соседству, и сдвиг только создал бы повод для новой ошибки. Разрыв в нумерации
-- у этого workflow и так есть с прежних правок.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

-- ⚠ Лишний — тот, что кладёт `dice_mail_*` без `dice_initiative_kind`.
SET @dead = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'dice'
                AND JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.outputs_map.dice_mail_opening') IS NOT NULL
                AND JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.outputs_map.dice_initiative_kind') IS NULL
              LIMIT 1);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'dice') AS жребиев,
       COALESCE(@dead, 0) AS лишний;

-- ⚠⚠ Удаляем только убедившись, что общий жребий на месте: не найдись он, мы
-- снесли бы единственный источник `dice_mail_*`, и промпты остались бы с метками.
DELETE FROM `agent_workflow_step`
 WHERE `id` = @dead
   AND @dead IS NOT NULL
   AND EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                WHERE x.`workflow_id` = @wf
                  AND JSON_EXTRACT(x.`metadata`,
                        '$.tool_invoke.outputs_map.dice_initiative_kind') IS NOT NULL);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       -- ⚠⚠ Жребий обязан остаться **ровно один**: ноль значит, что снесли лишнего
       -- вместе с нужным, два — что примета лишнего перестала его отличать.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'dice') AS жребиев,
       -- ⚠ И он обязан класть все шесть переменных.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.outputs_map.dice_initiative_kind') IS NOT NULL
           AND JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.outputs_map.dice_mail_story_on') IS NOT NULL) AS полный,
       -- ⚠⚠ Веса берутся из настроек, а не числом: ради этого всё и делается.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec'))
               LIKE '%dice_mail_name_percent%') AS веса_из_настроек;
