-- Два шага канала получили одну позицию — разводим (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Предыдущая миграция завела «Канал: письмо первым» и «Канал: ответ на письмо»
-- одним `INSERT … SELECT` из двух строк, а позицию брала как
-- `(SELECT MAX(position) + 1 …)`. Подзапрос вычислился **один раз на весь
-- оператор**, и обе строки получили 37.
--
-- ⚠ Работать это не мешает: к шагам ведут прыжки по `step_id`, а не по соседству, и
-- прогон их находит. Но порядок двух строк с равной позицией **не определён** —
-- редактор показывает их в произвольном порядке, а «номер шага» в трассе и в
-- панели перестаёт быть номером.
--
-- ## ⚠ Почему не `AUTO_INCREMENT`-порядок
--
-- Позиция и `id` — разные вещи: позиция это порядок чтения человеком, и её правят
-- перетаскиванием. Здесь просто раздаём двум строкам два свободных номера, взяв
-- отсчёт от нынешнего максимума.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @top = (SELECT MAX(`position`) FROM `agent_workflow_step` WHERE `workflow_id` = @wf);

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step`
           WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS x) AS позиций_с_двойниками,
       @top AS последняя;

-- ⚠ По одному `UPDATE` на шаг: тот же подзапрос в общем операторе и дал бы ту же
-- беду вторично. Шаги ищем по имени — они заведены этой же парой миграций, и
-- переименовать их никто не успел.
--
-- ⚠⚠ Условие «позиции совпадают» обязательно, иначе миграция **не повторяема**:
-- второй прогон сдвигал позиции ещё на два (38/39 → 40/41), третий — ещё, и номера
-- шагов уезжали в пустоту при каждом заходе.
SET @same = (SELECT COUNT(DISTINCT `position`) = 1
               FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `title` LIKE 'Канал:%');

UPDATE `agent_workflow_step`
   SET `position` = @top + 1
 WHERE `workflow_id` = @wf AND `title` = 'Канал: письмо первым' AND @same = 1;

UPDATE `agent_workflow_step`
   SET `position` = @top + 2
 WHERE `workflow_id` = @wf AND `title` = 'Канал: ответ на письмо' AND @same = 1;

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Двойников не остаётся ни одного: это и есть цель.
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step`
           WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS x) AS позиций_с_двойниками,
       (SELECT `position` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Канал: письмо первым') AS письмо,
       (SELECT `position` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Канал: ответ на письмо') AS ответ;
