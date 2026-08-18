-- Метки сайтов: `browser_site.tags` (выпуск 2026-08-18)
--
-- Зачем вручную: `migrations/0001.sql` — схема для чистой установки, на живой базе
-- `CREATE TABLE` не перевыполняется. Колонка добавлена туда же, а этот файл догоняет
-- её на уже созданных базах — локальной и прод.
--
-- ЗАЧЕМ КОЛОНКА. `GET /api/browser/site` отдаёт все закладки подряд, и соседний
-- проект DatingAi показывал в селекте анкет не только сайты знакомств, но и сам
-- RhapsodyAi — выбрать его там нельзя ничем разумным. Метка разделяет закладки по
-- принадлежности: DatingAi спрашивает `?tag=dating` и видит только своё. Новые
-- сайты знакомств получат ту же метку и появятся у него сами.
--
-- ЧТО МЕНЯЕТСЯ:
--   browser_site.tags   VARCHAR(255) NOT NULL DEFAULT ''  — новая колонка
--   Goldenbride         tags = 'dating'                   — единственный сайт знакомств
--
-- Прочие закладки остаются без меток. Это осознанно: пустая метка не совпадает ни с
-- одним `?tag=`, поэтому в списках соседей их не будет, а на вкладке «Сайты» самой
-- админки видны все — фильтр там не применяется.
--
-- ЧТО ТЕРЯЕТСЯ: ничего. Колонка добавляется, данные не переписываются, кроме одной
-- строки Goldenbride, у которой меток до сих пор не было вовсе.
--
-- Идемпотентность: колонка добавляется по сверке с `information_schema.COLUMNS`,
-- метка ставится только там, где `tags` пуст. Файл можно гонять сколько угодно раз.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup`.

USE `project`;

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_site'
           AND COLUMN_NAME = 'tags') AS колонка_есть,
       (SELECT COUNT(*) FROM browser_site) AS всего_сайтов;

-- ------------------------------------------- 1. Колонка меток
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'browser_site'
        AND COLUMN_NAME = 'tags') = 0,
    'ALTER TABLE `browser_site` ADD COLUMN `tags` VARCHAR(255) NOT NULL DEFAULT ''''
       COMMENT ''Метки через запятую: чьи это сайты'' AFTER `position`',
    'SELECT ''browser_site.tags уже на месте'' AS шаг');
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- ------------------------------------------- 2. Метка сайту знакомств
--
-- По имени, а не по номеру: номера закладок у прода и локальной базы свои, а имя
-- уникально ключом `uk_browser_site_name`. Пустая проверка `tags` бережёт руками
-- проставленные метки — повторный прогон их не затрёт.
UPDATE browser_site SET tags = 'dating' WHERE name = 'Goldenbride' AND tags = '';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, id, name, tags FROM browser_site ORDER BY position, id;
