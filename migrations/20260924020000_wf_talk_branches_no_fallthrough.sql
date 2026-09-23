-- Ветки сочинения не проваливаются друг в друга (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ: движок идёт по позициям, и шаг без перехода падает в следующий
--
-- Предыдущая миграция (`…_wf_talk_branches.sql`) завела три ветки сочинения
-- **в конец** списка — позиции 21, 22, 23. Переход назад на «Валидацию» у
-- каждой есть, но он условный (`girl_response exists`), а всё, что не сработало,
-- утекает в следующую позицию. Отсюда три дыры:
--
-- | провал | чем кончится |
-- |--------|--------------|
-- | 21 → 22 | письмо сочинится дважды: сперва «первым», потом «ответом» |
-- | 22 → 23 | к ответу припишется реплика инициативы |
-- | 23 → конец | реплика уйдёт **мимо проверки** судьёй |
--
-- ⚠⚠ И четвёртая, которой раньше не было. Шаг 20 «Влить придуманные факты»
-- прыгает назад по условию `agent_id > 0`; не сработай оно — до правки это
-- значило «конец прогона» (шаг был последним), а стало «провалиться в „Письмо
-- первым“» и сочинить письмо посреди сбора фактов.
--
-- ## Как чинится
--
-- **Ветки переезжают вплотную к шагу чата** — позиции 13, 14, 15, — а всё, что
-- шло после, сдвигается на три. Тогда порядок сам отвечает за правильность:
--
--     12 Ответ в чат      → всегда прыгает на «Валидацию»
--     13 Письмо первым    → всегда прыгает на «Валидацию»
--     14 Ответ на письмо  → всегда прыгает на «Валидацию»
--     15 Инициатива       → всегда прыгает на «Валидацию»
--     16 Валидация ответа → дальше как было
--     …
--     23 Влить придуманные факты  ← снова последний, провал = конец прогона
--
-- ⚠ Плюс **сторож на входе** у каждой ветки: `girl_response exists` → сразу на
-- «Валидацию». Ответ уже написан — значит в эту ветку попали ошибочно, и писать
-- второй раз нельзя. Один переход стережёт вход, другой уводит с выхода.
--
-- ⚠⚠ Шагу чата тоже добавлен переход на выход. Без него он падал бы в «Письмо
-- первым» — то есть каждая реплика в чат дописывалась бы письмом.
--
-- Идемпотентность: перенос считает позиции заново, сторожа ставятся поверх.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @valid = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Валидация ответа' LIMIT 1);
SET @chat = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` = 'Ответ в чат' LIMIT 1);
SET @chat_pos = (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @chat);
SET @s_write = (SELECT `id` FROM `agent_workflow_step`
                 WHERE `workflow_id` = @wf AND `title` = 'Письмо первым' LIMIT 1);
SET @s_reply = (SELECT `id` FROM `agent_workflow_step`
                 WHERE `workflow_id` = @wf AND `title` = 'Ответ на письмо' LIMIT 1);
SET @s_init = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf AND `title` = 'Инициатива' LIMIT 1);

-- Переносить нужно только если ветки ещё стоят в конце.
SET @move = (SELECT `position` <> @chat_pos + 1
               FROM `agent_workflow_step` WHERE `id` = @s_write);

SELECT 'ДО' AS этап, @chat_pos AS чат_на,
       (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @s_write) AS письмо_на,
       @move AS переносим;

-- ── 1. Ветки — на время в сторону ───────────────────────────────────────────
--
-- ⚠ Через временные номера: сдвиг хвоста на три занял бы позиции 21–23, где
-- ветки сейчас и стоят, и они столкнулись бы.
UPDATE `agent_workflow_step`
   SET `position` = 900 + FIELD(`id`, @s_write, @s_reply, @s_init)
 WHERE @move AND `id` IN (@s_write, @s_reply, @s_init);

-- ── 2. Хвост сдвигается на три ──────────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `position` = `position` + 3
 WHERE @move AND `workflow_id` = @wf AND `position` > @chat_pos AND `position` < 900
 ORDER BY `position` DESC;

-- ── 3. Ветки встают сразу за чатом ──────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `position` = @chat_pos + FIELD(`id`, @s_write, @s_reply, @s_init)
 WHERE @move AND `id` IN (@s_write, @s_reply, @s_init);

-- ── 4. Выход: каждая ветка уходит на проверку ───────────────────────────────
--
-- ⚠ `exists`, а не сравнение со значением: `girl_response` может быть законно
-- пустым (агент молчит), и проверка «не пусто» уводила бы молчание мимо судьи.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
         JSON_OBJECT('variable', 'girl_response', 'operator', 'exists',
                     'value', '', 'step_id', CAST(@valid AS CHAR))))
 WHERE `id` IN (@chat, @s_write, @s_reply, @s_init);

-- ── 5. Вход: сторож от ошибочного попадания ─────────────────────────────────
--
-- ⚠ У шага чата сторожа нет намеренно: он **первый** в развилке, и попасть в
-- него с уже готовым ответом неоткуда. Его `transitions_before` заняты самой
-- развилкой — вторым списком они бы её и затёрли.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_before', JSON_ARRAY(
         JSON_OBJECT('variable', 'girl_response', 'operator', 'exists',
                     'value', '', 'step_id', CAST(@valid AS CHAR))))
 WHERE `id` IN (@s_write, @s_reply, @s_init);

-- ── Проверка ────────────────────────────────────────────────────────────────
SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(CONCAT(`position`, ':', `title`) ORDER BY `position`
                            SEPARATOR ' → ')
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` BETWEEN @chat_pos AND @chat_pos + 4)
         AS порядок,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `id` IN (@chat, @s_write, @s_reply, @s_init)
           AND JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after')) = 1)
         AS с_выходом,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `id` IN (@s_write, @s_reply, @s_init)
           AND JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_before')) = 1)
         AS со_сторожем,
       (SELECT `title` FROM `agent_workflow_step` WHERE `workflow_id` = @wf
         ORDER BY `position` DESC LIMIT 1) AS последний_шаг,
       (SELECT COUNT(*) FROM (SELECT `position` FROM `agent_workflow_step`
                               WHERE `workflow_id` = @wf
                               GROUP BY `position` HAVING COUNT(*) > 1) d)
         AS позиций_вдвоём;
