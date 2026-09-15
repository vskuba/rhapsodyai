-- `dating_invite_write`: судья не верит секции «Метки» на слово (2026-09-14)
--
-- ЧТО ПОКАЗАЛА ПРОВЕРКА СУДЬИ. Ему подсунули заведомый брак: в секцию «Метки»
-- вписали выдуманную `[[his_city]]`. Модель честно поставила её в текст, а судья
-- ответил `yes`:
--
--     VERDICT: yes
--     TEXT: I have a feeling you're trouble in [[his_city]]…
--
-- Правило у него было такое: «есть лишняя, выдуманная (любая, кроме [[girl_name]]
-- и [[companion_name]])». Формально нарушение налицо — но рядом, в секции «Что
-- просили», стояло «поставь [[his_city]]», и судья поверил ей, а не правилу.
--
-- ⚠ ПОЧЕМУ ЭТО ВАЖНО, ХОТЯ ПАНЕЛЬ ТАКОЕ ЛОВИТ САМА. Ловит: чужая метка отбрасывает
-- шаблон целиком (`dating_mail_agent._invite`). Но тогда пул остаётся пустым до
-- следующего захода, то есть до получаса, — а судья для того и заведён, чтобы
-- брак чинился на месте, шагом правки. Пропуская брак, он не вредит, но и не
-- работает.
--
-- ЧТО МЕНЯЕМ. Список допустимых меток назван в правиле **исчерпывающе**, и прямо
-- сказано: секция «Метки» — это то, что просили у автора, а не разрешение. Любая
-- третья метка — брак, чем бы её ни объясняли.
--
-- Заодно то же самое сказано шагу правки: он читает ту же секцию и повторил бы
-- ошибку.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');

SELECT 'ДО' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%меток всего две%'
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 1) AS правка_есть;

-- ------------------------------------------- Судья: правило о метках
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 CONCAT('3. Меток не те, что просили: есть лишняя, выдуманная (любая, кроме ',
                        '[[girl_name]] и [[companion_name]]) или пропущена запрошенная.\n'),
                 CONCAT('3. Метки не те. Во всём проекте меток всего две: ',
                        '[[girl_name]] и [[companion_name]]. Любая третья — брак, ',
                        'чем бы она ни была объяснена: секция «Метки» выше — это ',
                        'то, что просили у автора, а не разрешение выдумывать. ',
                        'Брак и тогда, когда запрошенная метка пропущена или ',
                        'поставлена дважды.\n')))
 WHERE `workflow_id` = @wf AND `position` = 1;

-- ------------------------------------------- Правка: то же правило
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 CONCAT('тон, ровно запрошенные метки и никаких других, никаких имён словами, '),
                 CONCAT('тон, ровно запрошенные метки и никаких других (во всём проекте ',
                        'их две: [[girl_name]] и [[companion_name]]), никаких имён словами, ')))
 WHERE `workflow_id` = @wf AND `position` = 2;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%меток всего две%'
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 1) AS у_судьи,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%их две%'
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 2) AS у_правки;
