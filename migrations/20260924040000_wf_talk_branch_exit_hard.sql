-- Выход ветки не зависит от чужого объявления (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ: на графе шаг 13 ведёт на шаг 14, и это правда
--
-- Движок идёт по номерам, а редактор рисует это сплошной стрелкой у **каждого**
-- нетерминального шага (`graph.js`: «Sequential → next step»). То есть на вкладке
-- «Граф» ветка «Письмо первым» соединена со следующей веткой «Ответ на письмо» —
-- и соединена честно: уводит с неё только переход, пока его условие истинно.
--
-- Условие стояло на `girl_response exists`. Оно истинно всегда — но **по
-- случайности устройства**: `girl_response` объявлена переменной workflow, и
-- движок кладёт её в область видимости на старте
-- (`ai_workflow_variables_defaults_apply`). Сними кто-нибудь это объявление в
-- редакторе — и выход перестанет срабатывать: письмо напишется дважды, вторым
-- заходом как «ответ на письмо». Молча.
--
-- ⚠ Такую зависимость видно только отсюда, из перехода. Тот, кто правит список
-- переменных, о ней не узнает.
--
-- ## Как теперь
--
-- Условие — `prompt_user exists`. Эту переменную кладёт **сам движок**
-- (`ai_workflow_variables_base`), её нет в списке переменных workflow, и удалить
-- её из редактора нельзя. Ближайшее к безусловному переходу, что даёт язык
-- переходов.
--
-- ⚠ Смысл тот же, что был: «шаг отработал — уходи на проверку». Меняется только
-- то, на чём эта безусловность держится: на устройстве движка вместо чужой
-- строки в справочнике.
--
-- ⚠⚠ Стрелка 13 → 14 на графе **останется**: редактор рисует её всем шагам
-- подряд и о переходах при этом не спрашивает. Читать её надо как «сюда пойдёт
-- поток, если ни один переход не сработал», а не как «сюда пойдёт поток».
--
-- Идемпотентность: правится только то, что ещё на старом условии.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @valid = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Валидация ответа' LIMIT 1);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `title` IN ('Ответ в чат', 'Письмо первым', 'Ответ на письмо',
                           'Инициатива')
           AND `metadata` LIKE '%girl_response%exists%') AS на_чужой_переменной;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
         JSON_OBJECT('variable', 'prompt_user', 'operator', 'exists',
                     'value', '', 'step_id', CAST(@valid AS CHAR))))
 WHERE `workflow_id` = @wf
   AND `title` IN ('Ответ в чат', 'Письмо первым', 'Ответ на письмо',
                   'Инициатива');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `title` IN ('Ответ в чат', 'Письмо первым', 'Ответ на письмо',
                           'Инициатива')
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.transitions_after[0].variable')) = 'prompt_user'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.transitions_after[0].step_id')) = CAST(@valid AS CHAR))
         AS веток_с_твёрдым_выходом,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `title` IN ('Письмо первым', 'Ответ на письмо', 'Инициатива')
           AND JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_before')) > 0)
         AS сторожей_осталось,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_before'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ответ в чат') AS правил_развилки;
