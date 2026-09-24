-- `companion_uid` убран: ключ собеседника у соседа свой (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Переменная везла номер человека **на сайте знакомств** (`128282`). У соседа при
-- этом своя запись собеседника, и её номер приходит полем запроса —
-- `companion_id`, из которого движок и достаёт имя с заголовком.
--
-- Два ключа на одного человека — это не запас, а расхождение, отложенное во
-- времени: правят один, забывают второй, и факты разъезжаются по двум документам.
--
-- ⚠ Проверено перед удалением: `companion_uid` не читал **ни один** шаг — ни в
-- промптах, ни в картах инструментов, ни в переменных агента. Панель слала её в
-- каждом вызове (648 прогонов), и держалась она сама собой: панель шлёт, потому
-- что объявлено; объявлено, потому что панель шлёт.
--
-- ## ⚠ Порядок правок обратный обычному
--
-- Сперва панель перестаёт слать (`answer.py`), и только потом снимается
-- объявление. Наоборот было бы окно, в котором панель шлёт незаявленное и
-- получает `400` на каждый ответ в чате.
--
-- ## Чем ключуются факты теперь
--
-- `companion_name` — системным именем записи у соседа. Оно тоже приходит
-- запросом (`…_companion_vars_not_global`), а собирает его DatingAi из сайта и
-- номера: `dating_343_128282`. То есть номер с сайта в ключе остаётся — просто
-- одним значением, а не двумя.

SET @uid = (SELECT `id` FROM `agent_workflow_variable` WHERE `name` = 'companion_uid');

SELECT 'ДО' AS этап, COALESCE(@uid, 0) AS переменная,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` = @uid) AS связей,
       -- ⚠ Проверка обратной стороны: её вправду никто не читает. Выйди
       -- ненулевым — правку несли бы дальше, сломав чтение.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `metadata` LIKE '%companion\_uid%') AS шагов_читают;

-- ── Связь с `dating_talk` ───────────────────────────────────────────────────
DELETE FROM `agent_workflow_variable_workflow`
 WHERE `variable_id` = @uid
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_step` s
                    WHERE s.`metadata` LIKE '%companion\_uid%');

-- ── Сама переменная, раз больше ничья ───────────────────────────────────────
--
-- ⚠ Строка без единой связи в общем реестре — то же объявление, только ничьё:
-- видно в списке, выбирается в редакторе, не значит ничего.
DELETE FROM `agent_workflow_variable`
 WHERE `id` = @uid
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = @uid);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'companion_uid') AS переменная_осталась,
       -- ⚠ Замена обязана быть на месте: без неё собеседник у workflow безымянный.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = 5
           AND v.`name` IN ('companion_id', 'companion_name', 'companion_title'))
         AS замена_у_talk;
