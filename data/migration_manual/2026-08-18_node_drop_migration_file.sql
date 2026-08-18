-- Снос колонки `node.migration_file` на проде
--
-- Зачем вручную: колонка есть только на проде — в `migrations/0001.sql` её нет, и на
-- локальной установке её тоже нет. `DROP COLUMN` на живой базе деплой не делает.
--
-- ⚠️ `DROP COLUMN` НЕОБРАТИМ. Что теряется — шесть значений (снято с прода 2026-08-18):
--
--     id 2  Dating      migrations/0003.sql
--     id 4  Detective   migrations/0004.sql
--     id 6  Dashboard   migrations/0002.sql
--     id 7  Telegram    migrations/0005.sql
--     id 8  Cashier     migrations/0006.sql
--     id 9  Planning    migrations/0007.sql
--
--   Это имена файлов подпроектных миграций. Самих файлов в репозитории давно нет:
--   в `migrations/` лежит один `0001.sql`, единственный источник схемы. То есть
--   значения указывают в пустоту.
--
-- ПОЧЕМУ СНОСИТЬ БЕЗОПАСНО (проверено перед выпуском):
--
--   1. В коде на колонку не ссылается ни один Python-модуль — ни роутеры, ни
--      репозитории, ни инструменты.
--   2. Ручка `PUT /node/{id}` берёт из тела только `name` и `position`, остальное
--      молча отбрасывает. То есть поле нельзя было сохранить и раньше: страница его
--      показывала, отправляла — и оно терялось по дороге.
--   3. Инструменты `mysql_export_node_to_migration` и `mysql_migration_prod_create`,
--      которым колонка предназначалась, в таблице `tool` отсутствуют — их синхронизация
--      из кода ничего не находит. Шаги workflow #8, которые их зовут, уже мертвы.
--   4. Поле с формы ноды убрано тем же коммитом (`data/uvicorn/template/admin/node.html`).
--      Без этого страница читала бы `node.migration_file` из ответа, получала `undefined`
--      и показывала пустую строку — не ошибка, но обман: поле, которое ничего не делает.
--
-- Идемпотентность: сверяется с `information_schema`, повторный прогон ничего не делает.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup`. Значения выше уже записаны в
-- этой шапке — если они понадобятся, восстанавливать их можно отсюда, а не из дампа.

USE `project`;

-- ---------------------------------------------------------------- До
SET @есть := (SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node'
                 AND COLUMN_NAME = 'migration_file');

SET @sql := IF(@есть,
    "SELECT 'ДО' AS этап, id, name, IFNULL(migration_file, 'NULL') AS migration_file
       FROM node ORDER BY id",
    "SELECT 'КОЛОНКИ УЖЕ НЕТ — повторный прогон' AS этап");
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- ---------------------------------------------------------------- Снос
SET @sql := IF(@есть,
    'ALTER TABLE `node` DROP COLUMN `migration_file`',
    "SELECT 'сносить нечего' AS шаг");
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'node'
           AND COLUMN_NAME = 'migration_file') AS осталась_колонка,
       (SELECT COUNT(*) FROM node)             AS нод;

-- Ноды на месте и читаются: снос колонки не должен был задеть строки.
SELECT id, name, `position` FROM node ORDER BY id;
