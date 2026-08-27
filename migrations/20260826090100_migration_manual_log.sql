-- Журнал ручных прогонов SQL — таблица `migration_manual_log`.
--
-- Журнал применённых ручных миграций (`data/migration_manual/*.sql`).
--
-- Зачем. Файлы там одноразовые и применяются руками; без журнала «применён или
-- нет» отличить нельзя, а повторный прогон миграции, которая не идемпотентна,
-- ломает данные молча. Раньше это держали в голове и в шапке файла — тридцать
-- два файла спустя так уже не работает.
--
-- Ключ — имя файла, а не его содержимое: файл одноразовый, правят его до
-- применения, а не после. Хеш храним рядом справочно: разошёлся — файл трогали
-- после прогона, и это повод посмотреть глазами, а не запрещать.
--
-- `database` в ключе, потому что одна и та же миграция применяется в разные
-- базы: сначала в тестовую на проверку, потом в рабочую. Без него проверка в
-- тестовой выглядела бы как уже сделанная работа.
--
-- `status`: `ok` — прогон удался, `error` — упал на каком-то запросе, `dry` —
-- сухой прогон, откаченный транзакцией. Сухой пишем тоже: по нему видно, что
-- миграцию проверяли, и с каким исходом.
CREATE TABLE `migration_manual_log` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `file_name` VARCHAR(190) NOT NULL COMMENT 'Имя файла в data/migration_manual/',
    `database_name` VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'Куда применяли: рабочая или тестовая',
    `status` VARCHAR(16) NOT NULL DEFAULT '' COMMENT 'ok / error / dry',
    `statements` INT NOT NULL DEFAULT '0' COMMENT 'Сколько запросов в файле',
    `rows_affected` INT NOT NULL DEFAULT '0' COMMENT 'Сколько строк затронуто суммарно',
    `duration_ms` INT NOT NULL DEFAULT '0',
    `error` TEXT NOT NULL COMMENT 'Текст ошибки и номер запроса, на котором упало',
    `sha1` CHAR(40) NOT NULL DEFAULT '' COMMENT 'Хеш файла на момент прогона — сверка, а не запрет',
    `applied_by` VARCHAR(64) NOT NULL DEFAULT '',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_mml_file` (`file_name`, `database_name`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
