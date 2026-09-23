-- Отвязать одноимённых чужаков, прицепленных к чату (2026-09-23)
--
-- ЗАЧЕМ. `20260923030000_wf_inputs_declared` привязывал переменные к workflow
-- **по имени**, а имя в реестре не уникально. `companion_title` есть в трёх
-- экземплярах, и один из них — переменная детектива («Отображаемое имя
-- детектива-игрока», workflow 14). Её прицепило к чату.
--
-- На странице это видно глазом: две одинаковые строки `companion_title` с
-- разными описаниями. Так и нашлось — снимком страницы, а не запросом.
--
-- Сама та миграция уже исправлена (двойное `NOT EXISTS`), но на базах, где она
-- успела пройти, связь осталась. Эта её убирает.
--
-- ⚠ Убираем **только лишнее**: у кого одноимённых нет, ничего не меняется. Из
-- каждой пары остаётся та, что привязана к меньшему числу чужих workflow, —
-- то есть «своя» для этого.
--
-- Идемпотентность: второй заход не найдёт дублей.

SELECT 'ДО' AS этап, vw.`workflow_id`, v.`name`, COUNT(*) AS дублей
  FROM `agent_workflow_variable_workflow` vw
  JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
 GROUP BY vw.`workflow_id`, v.`name` HAVING COUNT(*) > 1;

-- Лишние связи: для пары «workflow + имя» оставляем строку с наименьшим
-- `variable_id`, прочие убираем.
--
-- ⚠ Наименьший номер — не произвол: переменная, заведённая раньше, и есть та,
-- ради которой workflow писали; поздние одноимённые пришли с другими занятиями.
DELETE vw FROM `agent_workflow_variable_workflow` vw
  JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
  JOIN (
      SELECT vw2.`workflow_id`, v2.`name`, MIN(v2.`id`) AS keep_id
        FROM `agent_workflow_variable_workflow` vw2
        JOIN `agent_workflow_variable` v2 ON v2.`id` = vw2.`variable_id`
       GROUP BY vw2.`workflow_id`, v2.`name`
      HAVING COUNT(*) > 1
  ) dup ON dup.`workflow_id` = vw.`workflow_id` AND dup.`name` = v.`name`
 WHERE v.`id` <> dup.`keep_id`;

SELECT 'ПОСЛЕ' AS этап, COUNT(*) AS осталось_дублей FROM (
    SELECT vw.`workflow_id`, v.`name`
      FROM `agent_workflow_variable_workflow` vw
      JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
     GROUP BY vw.`workflow_id`, v.`name` HAVING COUNT(*) > 1) AS d;
