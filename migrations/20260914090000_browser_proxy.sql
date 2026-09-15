-- Реестр прокси: выходные адреса и кто за ними сидит (2026-09-14)
--
-- ЗАЧЕМ. Сайты знакомств считают учётки **по внешнему IP**: с одного адреса
-- пускают несколько девушек, дальше вход отвергается. Значит анкете нужен свой
-- выход, а выходы нужно где-то держать, проверять и раздавать.
--
-- ⚠ ПОЧЕМУ ЗДЕСЬ, А НЕ В DatingAi. Прокси нужен обоим концам одной работы: здесь
-- через него ходит Chromium (вход на сайт сценарием), там — HTTP-запросы к API
-- сайта, присутствие и вебсокет чата. Реестр в потребителе означал бы, что
-- браузер узнаёт свой выход от того, кому сам же его и отдаёт; а второй
-- потребитель завёл бы второй реестр, и оба поделили бы один IP, не зная об этом.
--
-- ⚠ СЧИТАЕМ ПО УВИДЕННОМУ АДРЕСУ, А НЕ ПО СТРОКЕ ПОДКЛЮЧЕНИЯ. Две записи в
-- реестре запросто выходят одним и тем же IP — так устроены пулы у провайдеров, —
-- и тогда лимит сайта они делят молча. Поэтому `check_ip` не украшение отчёта:
-- занятость считается по нему, и до первой удачной проверки прокси в раздачу не
-- попадает вовсе.
--
-- ЧТО ЗАВОДИТСЯ:
--
--   `browser_proxy`      — сам выход: адрес, вход, вместимость, итог проверки;
--   `browser_proxy_seat` — место: кто занял (`dating:profile:41`) и когда.
--
-- ⚠ ПОЧЕМУ МЕСТА ОТДЕЛЬНОЙ ТАБЛИЦЕЙ, А НЕ КОЛОНКОЙ `busy_by`. Лимит сайта — не
-- «одна анкета на IP», а «несколько»; сколько именно — выясняется опытом и живёт
-- в `seat_limit`. Колонка держала бы ровно одного, и первое же «а давай две»
-- потребовало бы переезда данных.
--
-- ⚠ ВЛАДЕЛЕЦ — НЕПРОЗРАЧНАЯ СТРОКА (`owner_key`). Здесь не знают, что такое
-- анкета, и знать не должны: это хозяйство соседа. Уникальность ключа даёт
-- главное правило — **одна анкета сидит ровно на одном выходе**, и повторный
-- запрос отдаёт ей тот же, а не второй.
--
-- ПАРОЛЬ ЛЕЖИТ ОТКРЫТЫМ, как и пароли сайтов в `browser_site_variable`: им
-- авторизуется машина, а не человек, и подставить хеш вместо пароля в прокси
-- нельзя. Наружу он уходит ровно одной ручкой и по отдельному праву
-- (`browser:proxy`), остальным показывается `•••`.
--
-- Идемпотентность: `CREATE TABLE IF NOT EXISTS` — файл можно гонять сколько
-- угодно раз.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME IN ('browser_proxy', 'browser_proxy_seat')) AS таблиц_есть;

-- ------------------------------------------- Выходы
--
-- `name` — как человек зовёт этот выход в разговоре («DE-1», «резидент Киев 3»).
-- Уникально: два одинаковых имени в списке означают, что один из них выберут не
-- глядя, и разбираться придётся по номеру.
--
-- `scheme` — `http`, `https`, `socks5`, `socks5h`. Хранится строкой, а не ENUM:
-- список схем задаёт клиент (`py_modules/http_/http_proxy.py`), и менять его
-- миграцией ради новой строки — лишний шаг.
--
-- `seat_limit` — сколько анкет допустимо посадить **на этот внешний адрес**.
-- Единица по умолчанию: она всегда безопасна, а настоящий предел сайта
-- выясняется опытом и поднимается руками.
--
-- `check_*` — итог последней проверки: прошла ли, каким адресом нас увидели,
-- сколько заняло и что сказал отказ. Держим прямо в строке, а не отдельной
-- таблицей проверок: вопрос к прокси один — «годен ли он сейчас», а история
-- проверок никому ещё не понадобилась.
CREATE TABLE IF NOT EXISTS `browser_proxy` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL COMMENT 'Как человек зовёт этот выход',
    `scheme` VARCHAR(10) NOT NULL DEFAULT 'http' COMMENT 'http | https | socks5 | socks5h',
    `host` VARCHAR(190) NOT NULL,
    `port` SMALLINT UNSIGNED NOT NULL,
    `username` VARCHAR(190) NOT NULL DEFAULT '',
    `password` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Открытым: им авторизуется машина; наружу — по праву browser:proxy',
    `note` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Пометка человека: чей канал, до какого числа оплачен',
    `is_enabled` TINYINT NOT NULL DEFAULT 1 COMMENT '0 — в раздачу не берём, но и не удаляем',
    `seat_limit` SMALLINT NOT NULL DEFAULT 1 COMMENT 'Сколько анкет допустимо на этот внешний IP',
    `checked_at` DATETIME DEFAULT NULL COMMENT 'Когда проверяли последний раз',
    `check_ok` TINYINT NOT NULL DEFAULT 0 COMMENT '1 — проверка прошла; 0 — не проверен или отказал',
    `check_ip` VARCHAR(45) NOT NULL DEFAULT '' COMMENT 'Каким адресом нас видят: по нему и считается занятость',
    `check_ms` INT NOT NULL DEFAULT 0 COMMENT 'Сколько занял поход через прокси, мс',
    `check_error` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Отказ словами; пусто при удаче',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_browser_proxy_name` (`name`),
    INDEX `idx_browser_proxy_ip` (`check_ip`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------- Места
--
-- `owner_key` — ключ потребителя, для нас непрозрачный: `dating:profile:41`.
-- Уникален на весь реестр, и в этом всё правило: одна анкета — один выход.
-- Повторный запрос той же анкеты отдаёт ей тот же прокси, а не второй.
--
-- `owner_name` — то же самое человеческими словами, для страницы: «Diana ·
-- Ladadate». Нужен затем, чтобы глядя в реестр было видно, кого именно снимут с
-- выхода, если его выключить.
CREATE TABLE IF NOT EXISTS `browser_proxy_seat` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `proxy_id` INT NOT NULL,
    `owner_key` VARCHAR(100) NOT NULL COMMENT 'Ключ потребителя: dating:profile:41',
    `owner_name` VARCHAR(190) NOT NULL DEFAULT '' COMMENT 'Он же словами, для страницы',
    `claimed_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_browser_proxy_seat_owner` (`owner_key`),
    INDEX `idx_browser_proxy_seat_proxy` (`proxy_id`),
    CONSTRAINT `fk_browser_proxy_seat_proxy` FOREIGN KEY (`proxy_id`)
        REFERENCES `browser_proxy` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME IN ('browser_proxy', 'browser_proxy_seat')) AS таблиц_есть,
       (SELECT COUNT(*) FROM `browser_proxy`) AS выходов,
       (SELECT COUNT(*) FROM `browser_proxy_seat`) AS занято;
