-- Страна выхода: код ISO-3166 alpha-2 рядом с увиденным адресом (2026-09-14)
--
-- ЗАЧЕМ. Потребителю важно не только «каким адресом нас видят», но и **откуда**:
-- сайты сверяют геолокацию входа с тем, что написано в анкете, и канал не из той
-- страны — повод к вопросам у них, а не у нас. Раньше страну приходилось узнавать
-- глазами по IP; теперь она едет вместе с ним.
--
-- ⚠ БЕРЁТСЯ ТЕМ ЖЕ ЗАПРОСОМ, что и адрес (`ipinfo.io` отдаёт оба поля). Второй
-- поход удвоил бы время проверки на каждый выход, а проверяют их пачками по два
-- десятка.
--
-- ⚠ ПУСТО — ЭТО «НЕ ЗНАЕМ», А НЕ «НЕТ СТРАНЫ». Так будет у непроверенных, у
-- мёртвых и у тех, кого проверили прежней службой (она страну не называла).
-- Заполнится при следующей проверке — своей или по кругу.
--
-- Два знака: ISO даёт ровно столько, и лишний запас в колонке означал бы, что
-- туда однажды положат «Украина».
--
-- Идемпотентность: колонка заводится по условию отсутствия.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy'
           AND COLUMN_NAME = 'check_country') AS колонка_есть;

-- ------------------------------------------- Колонка
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy'
        AND COLUMN_NAME = 'check_country') = 0,
    'ALTER TABLE `browser_proxy`
        ADD COLUMN `check_country` CHAR(2) NOT NULL DEFAULT ''''
            COMMENT ''Страна выхода по ISO-3166 alpha-2; пусто — не знаем''
            AFTER `check_ip`',
    'SELECT ''browser_proxy.check_country уже есть'' AS пропуск');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy'
           AND COLUMN_NAME = 'check_country') AS колонка_есть,
       (SELECT COUNT(*) FROM `browser_proxy` WHERE `check_country` <> '') AS со_страной;
