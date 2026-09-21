-- Персона девушки: снят запрет на отправку фотографий (2026-09-21)
--
-- ЗАЧЕМ. У `dating_talk` есть ветка «письма и фото»
-- (`20260921100000_wf_dating_talk_about_photo.sql`), заведённая ради согласия в
-- ОБЕ стороны: он присылает свои — соглашаемся принять, он просит наши —
-- соглашаемся прислать письмом.
--
-- ⚠⚠ Половина замысла не работала. Системный промпт персоны говорит:
--
--     The same applies to photos: you don't send them or promise anything specific.
--
-- Системный промпт сильнее шагового, и ветка на «пришли свои фотографии» отвечала
-- отказом: «nah, i keep that for the first date», `photo_deal = none` вместо `mine`.
-- Нашёл живой тест `tests_llm/test_dating_talk.py::test_it_promises_her_photos`.
--
-- ⚠ УБИРАЕМ ПРЕДЛОЖЕНИЕ ЦЕЛИКОМ, а не переписываем. Пробная переформулировка
-- («Photos are different: if he offers his or asks for yours, you gladly agree…»)
-- сделала хуже: сломался ранее проходивший случай «принять его фотографии» —
-- девушка стала отказывать и там. Персона задаёт характер, а не правила сделки;
-- что делать с фотографиями, решает промпт ветки, и двух голосов об одном ему
-- не нужно.
--
-- ⚠ Запреты на контакты остаются нетронутыми: адреса, телефоны, соцсети — это
-- увод с сайта и бан, а не разговор про фотографии.
--
-- ⚠⚠ ДВА МЕСТА, И ОБА ОБЯЗАТЕЛЬНЫ:
--   1) `agent.prompt_system` у `dating_girl_universal` — то, что работает сейчас
--      (движок читает поля агента напрямую, минуя переменные workflow);
--   2) `node_variable.girl_prompt_system` — шаблон, которым заводят агента
--      (`dating_bot` шаг 9, `dating_girl_create` шаг 3). Оставь его — и запрет
--      вернётся с первой же новой анкетой.
--
-- ⚠ Апостроф в тексте ТИПОГРАФСКИЙ (U+2019, байты E2 80 99), а не ASCII: с
-- обычным `'` замена не находит строку и миграция проходит вхолостую.
--
-- Идемпотентность: `REPLACE` не найдёт строку на второй заход и ничего не тронет.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%applies to photos%') AS у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `name` = 'girl_prompt_system'
           AND `default` LIKE '%applies to photos%') AS в_шаблоне;

-- 1. Промпт работающего агента.
UPDATE `agent`
   SET `prompt_system` = REPLACE(`prompt_system`,
       ' The same applies to photos: you don’t send them or promise anything specific.',
       '')
 WHERE `prompt_system` LIKE '%applies to photos%';

-- 2. Шаблон, из которого заводят новых.
UPDATE `node_variable`
   SET `default` = REPLACE(`default`,
       ' The same applies to photos: you don’t send them or promise anything specific.',
       '')
 WHERE `name` = 'girl_prompt_system';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%applies to photos%') AS у_агента,
       (SELECT COUNT(*) FROM `node_variable`
         WHERE `name` = 'girl_prompt_system'
           AND `default` LIKE '%applies to photos%') AS в_шаблоне,
       -- ⚠ Сверка, что убрали ровно фразу, а не абзац: соседние запреты на месте.
       (SELECT COUNT(*) FROM `agent`
         WHERE `prompt_system` LIKE '%social contacts for dating%') AS контакты_целы;
