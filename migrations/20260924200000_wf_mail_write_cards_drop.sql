-- Мёртвые карточки у `dating_mail_write` убраны (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `companion_card` и `girl_card` объявлены у него входящими — и мертвы **с обеих
-- сторон**:
--
--     панель      не шлёт их вовсе (`mail_agent.mail_write` кладёт другое)
--     промпты     не читают ни в одном из девяти шагов
--
-- Это хуже, чем просто мусор. Объявление входящей — договор: «пришли мне это».
-- Ненужное объявление заставляет искать, кто же его выполняет, и находить, что
-- никто. Разобраться в этом стоит получаса, а стоит на месте оно нуля.
--
-- ⚠ Тем же именем они звались у `dating_mail_question` и `dating_mail_vars`, где
-- вправду работали, — но там переименованы в `companion_bio` / `girl_bio`
-- (`…_wf_mail_card_to_bio`). После той правки и удаления `dating_mail_reply`
-- держателем остался один `dating_mail_write`, и держит он их зря.
--
-- ## ⚠ Переменные уходят целиком, не только связи
--
-- Реестр `agent_workflow_variable` один на все занятия, и строка без единой
-- связи в нём — то же самое объявление, только ничьё: видно в списке, выбирается
-- в редакторе, не значит ничего. Поэтому проверка «не осталось ли связей» стоит
-- **в самом запросе**: появись у переменной другой хозяин между написанием
-- миграции и её применением — удаления не будет.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @wf
           AND v.`name` IN ('companion_card', 'girl_card')) AS связей,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('companion_card', 'girl_card')) AS переменных,
       -- ⚠ Проверка обратной стороны: их вправду никто не читает. Окажись
       -- иначе — числа в отчёте разойдутся с ожидаемым нулём, и это видно до
       -- того, как правку понесут на прод.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND (`metadata` LIKE '%companion\_card%'
             OR `metadata` LIKE '%girl\_card%')) AS шагов_читают;

-- ── Связи ───────────────────────────────────────────────────────────────────
DELETE vw FROM `agent_workflow_variable_workflow` vw
  JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
 WHERE vw.`workflow_id` = @wf
   AND v.`name` IN ('companion_card', 'girl_card')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_step` s
                    WHERE s.`workflow_id` = @wf
                      AND s.`metadata` LIKE CONCAT('%', v.`name`, '%'));

-- ── Сами переменные, если больше ничьи ──────────────────────────────────────
--
-- ⚠ Подзапрос обёрнут в `SELECT *`: MySQL не даёт читать в `NOT EXISTS` ту же
-- таблицу, из которой удаляют, а через производную — даёт.
DELETE FROM `agent_workflow_variable`
 WHERE `name` IN ('companion_card', 'girl_card')
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = `agent_workflow_variable`.`id`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('companion_card', 'girl_card')) AS переменных_осталось,
       -- ⚠ Новые имена обязаны уцелеть: их читают `mail_question` и `mail_vars`.
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('companion_bio', 'girl_bio')) AS новые_целы,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE v.`name` IN ('companion_bio', 'girl_bio')) AS связей_у_новых;
