-- Реестр прокси перестаёт знать про анкеты (2026-09-14)
--
-- ЧТО БЫЛО НЕ ТАК. Заводя реестр сутки назад, я положил в него места:
-- `browser_proxy_seat` (кто сидит) и `browser_proxy.seat_limit` (сколько анкет
-- допустимо на внешний адрес). Это знание **соседнего проекта**, а не этого:
-- здесь не знают, что такое анкета, и знать не должны.
--
-- Граница нарушалась молча и сразу в трёх местах: таблица мест хранила ключи
-- вида `dating:profile:41`, колонка `seat_limit` называла предел «в анкетах», а
-- страница показывала столбец «Анкеты» — в проекте, где анкет нет.
--
-- ЧТО СТАНОВИТСЯ. Реестр отвечает на один вопрос: **какие выходы есть и какие из
-- них живые**. Кому их раздать и сколько потребителей допустимо на один внешний
-- адрес, решает тот, кто этих потребителей знает: DatingAi считает своих анкет по
-- `check_ip`, который реестр отдаёт вместе со строкой.
--
-- Почему это лучше, а не просто «иначе»:
--
--   * предел зависит от **сайта знакомств**, а не от канала: Goldenbride пускает
--     одно число девушек с адреса, Ladadate другое. Здесь про сайты знакомств не
--     знают вовсе, и число это было беспризорным;
--   * второй потребитель реестра (а он появится) считал бы своих по своим
--     правилам — и делил бы таблицу мест с чужими ключами;
--   * пропадает целый разряд вопросов «почему место занято, а анкеты нет».
--
-- ⚠ ДАННЫЕ МЕСТ ТЕРЯЮТСЯ, и это осознанно. Они прожили сутки, в них только мои
-- проверочные строки, а переносить их некуда: у соседа привязка уже своя
-- (`dating_profile.proxy_id`). Заведи он места заново — они встанут при первом
-- же обращении анкеты за выходом.
--
-- Идемпотентность: таблица сносится по условию, колонка — через
-- `information_schema` и `PREPARE` (`DROP COLUMN IF EXISTS` MySQL не умеет).

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy_seat') AS таблица_мест,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy'
           AND COLUMN_NAME = 'seat_limit') AS колонка_предела;

-- ------------------------------------------- Места
DROP TABLE IF EXISTS `browser_proxy_seat`;

-- ------------------------------------------- Предел «в анкетах»
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy'
        AND COLUMN_NAME = 'seat_limit') > 0,
    'ALTER TABLE `browser_proxy` DROP COLUMN `seat_limit`',
    'SELECT ''browser_proxy.seat_limit уже убран'' AS пропуск');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy_seat') AS таблица_мест,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_proxy'
           AND COLUMN_NAME = 'seat_limit') AS колонка_предела,
       (SELECT COUNT(*) FROM `browser_proxy`) AS выходов;
