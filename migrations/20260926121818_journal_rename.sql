-- Таблица `error_log` переименована в `journal` — вслед за предметной областью (2026-09-26)
--
-- ## Зачем
--
-- Страница называется «Журнал» (`/admin/journal`), namespace кода — `src/journal/`,
-- функции — `journal_write`, `journal_rows`. Таблица оставалась `error_log`, и это
-- ровно то расхождение, из-за которого потом ищут «а где же журнал»: имя в коде
-- одно, в базе другое.
--
-- ⚠ **Предмет журнала шире ошибок.** Страница отвечает на вопрос «что происходило
-- на установке», и ошибки — её первая подвкладка, а не весь смысл. Имя `error_log`
-- закрывало бы дорогу соседним записям, а `journal` — нет.
--
-- ## Почему отдельным файлом, а не правкой создающей миграции
--
-- `20260926101937_error_log.sql` уже применена (и на локальной установке, и на
-- проде): yoyo помнит её в `_yoyo_migration` и второй раз не запустит. Правка
-- применённого файла ничего бы не изменила в базе и разошлась бы с тем, что в ней
-- на самом деле лежит.
--
-- ## Порядок на новой установке
--
-- Создающая миграция заводит `error_log`, эта — переименовывает. Условия ниже
-- делают файл идемпотентным: прогон на базе, где `journal` уже есть, ничего не
-- трогает.
--
-- ⚠ Данные переезжают вместе с таблицей: `RENAME TABLE` не копирует строки, а
-- меняет имя — записи, накопленные до переименования, остаются на месте.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'error_log') AS есть_error_log,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal') AS есть_journal;

-- ------------------------------------------- Сама таблица
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'error_log') = 1
    AND (SELECT COUNT(*) FROM information_schema.TABLES
          WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal') = 0,
    'RENAME TABLE `error_log` TO `journal`',
    'SELECT ''таблица уже journal'' AS пропуск');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------- Имена ключей
--
-- Ключи переименовываются отдельно: `RENAME TABLE` их не трогает, и в схеме
-- остались бы `uniq_error_log_fingerprint` рядом с таблицей `journal`. Имя ключа
-- всплывает в тексте ошибки при нарушении уникальности — читать его будут люди.
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal'
        AND INDEX_NAME = 'uniq_error_log_fingerprint') > 0,
    'ALTER TABLE `journal` RENAME INDEX `uniq_error_log_fingerprint` TO `uniq_journal_fingerprint`',
    'SELECT ''ключ отпечатка уже переименован'' AS пропуск');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal'
        AND INDEX_NAME = 'idx_error_log_last') > 0,
    'ALTER TABLE `journal` RENAME INDEX `idx_error_log_last` TO `idx_journal_last`',
    'SELECT ''ключ времени уже переименован'' AS пропуск');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal'
        AND INDEX_NAME = 'idx_error_log_source') > 0,
    'ALTER TABLE `journal` RENAME INDEX `idx_error_log_source` TO `idx_journal_source`',
    'SELECT ''ключ источника уже переименован'' AS пропуск');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal') AS есть_journal,
       (SELECT COUNT(*) FROM information_schema.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'journal'
           AND INDEX_NAME LIKE 'error_log%') AS ключей_со_старым_именем,
       (SELECT COUNT(*) FROM `journal`) AS записей;
