-- Ключ собеседника перестаёт обрезаться на 25 знаках (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ: тихая поломка, пойманная тестом
--
-- `unique_id` был `char(25)` — длины хватало, пока туда клали `dating_person`.
-- Теперь ключ склеивается из номера и имени, и он длиннее:
--
--     pytest_llm_girl_Zinaida-Test    28 знаков
--     pytest_llm_girl_Zinaida-T       столько доехало до базы
--
-- Дальше беда становится **громкой, но непонятной**: вставка урезает, а поиск
-- идёт по полному ключу — не находит и вставляет снова. Вторая вставка упирается
-- в уникальный индекс:
--
--     (1062, "Duplicate entry 'pytest_llm_girl_Zinaida-T' for key
--             'companion.un_companion_name'")
--
-- Сообщение про дубликат при том, что записи «нет», — и есть худшее: ищут
-- гонку вставок, а дело в ширине столбца.
--
-- ## Сколько нужно
--
-- 190 знаков. Не «с запасом на всякий случай»: это привычный предел для
-- уникального индекса в utf8mb4 — 190 × 4 = 760 байт, и он влезает даже в старое
-- ограничение InnoDB в 767. Ключ длиннее ста знаков означал бы, что склеили не
-- то.
--
-- ⚠ `varchar`, а не `char`: `char(190)` добивал бы каждую строку пробелами до
-- полной длины. Для `dating_person` это 180 лишних знаков на запись.
--
-- ## ⚠ Название тоже
--
-- `title` тем же `char(25)`, и имена живых людей в него упираются: «Bartholomew
-- Smith-Jones» это 22, а с отчеством уже нет. Обрезанное имя агент читает как
-- настоящее и зовёт человека огрызком.

SELECT 'ДО' AS этап,
       (SELECT `COLUMN_TYPE` FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'unique_id') AS тип_ключа,
       (SELECT `COLUMN_TYPE` FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'title') AS тип_названия,
       (SELECT COUNT(*) FROM `companion`) AS записей;

-- ── Ширина ──────────────────────────────────────────────────────────────────
--
-- ⚠ `MODIFY` выполняется и на уже расширенном столбце — он просто не меняет
-- ничего. Отдельной проверки не нужно: повторный прогон безвреден.
ALTER TABLE `companion`
    MODIFY `unique_id` varchar(190) COLLATE utf8mb4_general_ci NOT NULL,
    MODIFY `title` varchar(190) COLLATE utf8mb4_general_ci NOT NULL;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `COLUMN_TYPE` FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'unique_id') AS тип_ключа,
       (SELECT `COLUMN_TYPE` FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'title') AS тип_названия,
       -- ⚠ Уникальность обязана уцелеть: без неё два человека получат один ключ,
       -- и факты о них сольются в один документ.
       (SELECT COUNT(*) FROM `information_schema`.`STATISTICS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'unique_id' AND `NON_UNIQUE` = 0) AS ключ_уникален,
       (SELECT COUNT(*) FROM `companion`) AS записей;
