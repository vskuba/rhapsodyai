-- Персона: «переводи тему» — про контакты, а не про всё личное (2026-09-22)
--
-- ЗАЧЕМ. В промпте персоны стоит:
--
--     If questions arise about meetings, calls, or other personal information,
--     you try to gently joke or change the subject.
--
-- «Other personal information» — ловушка: под неё попадает всё, включая
-- фотографии. И промпт ветки, которому велено договариваться о фото, эту строку
-- перебить не может — системный промпт сильнее.
--
-- Живой прогон, на котором это поймано (`tests_llm/test_dating_talk.py`,
-- `test_it_promises_her_photos`):
--
--     он:  Can you send me your photos? I'd love to see more of you
--     она: i'm shy with pics rn. tell me a secret instead? 😜
--     решение ветки: photo_deal = 'his'
--
-- Это буквальное исполнение строки: пошутила и перевела тему. Ветка при этом
-- отработала и дошла до конца — сломано не ветвление, а то, что модель читает
-- запрет там, где его больше нет.
--
-- ⚠⚠ ЗАПРЕТ НА ФОТО УЖЕ СНИМАЛИ, И ЭТОГО НЕ ХВАТИЛО. Миграция
-- `20260921150000_girl_prompt_photo_allow` убрала прямую фразу «The same applies
-- to photos: you don't send them». Осталась эта — общая, — и она продолжила
-- работать за убранную. Отсюда правило: снимая запрет, надо убирать и зонтик, под
-- который он прячется.
--
-- ЧТО ДЕЛАЕМ. Сужаем «other personal information» до того, что и имелось в виду:
-- контакты. Следующая же фраза их перечисляет — «Do not sends any addresses,
-- phones, social contacts for dating», — то есть правило не меняется, а
-- перестаёт захватывать лишнее.
--
-- ⚠ ВСТРЕЧИ И ЗВОНКИ ОСТАЮТСЯ. Их запрещают отдельные строки выше («You never
-- agree to personal meetings or calls»), и трогать их незачем: это решение
-- заказчика о том, как ведёт себя анкета, а не побочная помеха.
--
-- ⚠⚠ ДВА МЕСТА, И ОБА ОБЯЗАТЕЛЬНЫ. Текст персоны лежит и у агента
-- (`agent.prompt_system`, id 1663), и у узла (`node_variable.girl_prompt_system`).
-- Правь одно — второе перебьёт его при следующей сборке, и правка «не
-- подействует» без единого следа в журнале. Ровно так и было с запретом на фото.
--
-- Идемпотентность: `REPLACE` не находит строки, если её уже заменили.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%other personal information%') AS у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `default` LIKE '%other personal information%') AS у_узла;

UPDATE `agent`
   SET `prompt_system` = REPLACE(
         `prompt_system`,
         'If questions arise about meetings, calls, or other personal information, you try to gently joke or change the subject.',
         'If questions arise about meetings, calls, or contact details, you try to gently joke or change the subject.')
 WHERE `id` = 1663;

UPDATE `node_variable`
   SET `default` = REPLACE(
         `default`,
         'If questions arise about meetings, calls, or other personal information, you try to gently joke or change the subject.',
         'If questions arise about meetings, calls, or contact details, you try to gently joke or change the subject.')
 WHERE `name` = 'girl_prompt_system';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%other personal information%') AS осталось_у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `default` LIKE '%other personal information%') AS осталось_у_узла,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%or contact details%') AS правка_у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `default` LIKE '%or contact details%') AS правка_у_узла;
