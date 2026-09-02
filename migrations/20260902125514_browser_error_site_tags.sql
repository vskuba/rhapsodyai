-- Журнал ошибок браузера получает сайт и теги: `browser_error.site_id`, `.tags`.
--
-- Зачем сайт. Ошибка отвечала на «что сломалось», но не на «где»: в списке стояли
-- источник, время и адрес страницы — а адрес пуст почти у всех записей. Живьём из 8255
-- ошибок `url` заполнен у нуля: их шлют соседние проекты по API, а те работают не с
-- адресом, а с сайтом из справочника. Сайт при этом у них есть — некоторые кладут его
-- в `context.site_id`, — но лежит он там как придётся, не индексируется и в список не
-- выводится. Разбор чужого сбоя начинается с вопроса «на каком сайте», и ответа на него
-- страница не давала.
--
-- Колонка, а не ключ `context`. По сайту фильтруют и группируют, а JSON для этого
-- негоден: индекса нет, тип не гарантирован, и запись, приславшая `site_id` строкой,
-- в выборку по числу не попадёт. Внешнего ключа намеренно нет: журнал переживает
-- удаление сайта — «ошибка на сайте, которого больше нет» это осмысленная строка, а
-- каскадное удаление стёрло бы историю разбора вместе с сайтом.
--
-- Зачем теги. Источник (`source`) говорит, кто прислал, а не что случилось: под одним
-- словом `dating` лежат и таймауты, и отказы авторизации, и упавшие сценарии. Тег
-- отвечает на второй вопрос — про род ошибки, — и по нему журнал фильтруется чипсами
-- на самой странице.
--
-- Теги строкой, а не отдельной таблицей. Их немного, они короткие и ставятся
-- автоматически по тексту ошибки (`browser_error_tags`); связь «многие ко многим» здесь
-- дала бы две таблицы и JOIN ради подписи, которую человек читает глазами. Хранятся с
-- обрамляющими запятыми (`,timeout,network,`), чтобы поиск по одному тегу был точным:
-- `LIKE '%,net,%'` не поймает `,network,`, а без обрамления — поймал бы.
--
-- Идемпотентность: `ADD COLUMN IF NOT EXISTS` MySQL не поддерживает, поэтому через
-- `information_schema` и `PREPARE` — тем же приёмом, что в `20260828020000`.

-- 1. Сайт, на котором случилась ошибка.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'browser_error'
       AND COLUMN_NAME = 'site_id'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `browser_error`
        ADD COLUMN `site_id` INT DEFAULT NULL
            COMMENT ''Сайт из browser_site; NULL — сайт неизвестен''
            AFTER `session_id`',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. Род ошибки — теги через запятую.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'browser_error'
       AND COLUMN_NAME = 'tags'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `browser_error`
        ADD COLUMN `tags` VARCHAR(255) NOT NULL DEFAULT ''''
            COMMENT ''Род ошибки: ,timeout,network, — с обрамляющими запятыми''
            AFTER `context`',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. Индекс под фильтр по сайту.
SET @exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'browser_error'
       AND INDEX_NAME = 'idx_browser_error_site'
);

SET @sql := IF(@exists = 0,
    'ALTER TABLE `browser_error` ADD INDEX `idx_browser_error_site` (`site_id`, `id`)',
    'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 4. Сайт у записей, которые его уже присылали — в `context.site_id`. Разбор задним
-- числом: колонки не было, и класть его было некуда, а ошибки эти живут в журнале и
-- сейчас. Берём только числовые значения: `JSON_EXTRACT` вернёт что угодно, и строка
-- вроде `main` в колонке `INT` молча стала бы нулём.
UPDATE `browser_error`
   SET `site_id` = CAST(JSON_UNQUOTE(JSON_EXTRACT(`context`, '$.site_id')) AS UNSIGNED)
 WHERE `site_id` IS NULL
   AND JSON_EXTRACT(`context`, '$.site_id') IS NOT NULL
   AND JSON_UNQUOTE(JSON_EXTRACT(`context`, '$.site_id')) REGEXP '^[0-9]+$';
