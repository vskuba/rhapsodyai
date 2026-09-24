-- `companion.name` зовётся `unique_id`: это ключ, а не имя (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Поле уникально (`un_companion_name`) и всегда было ключом, а не именем. Кто им
-- пользуется, кладёт туда ключ и знает об этом:
--
--     DatingAi      dating_343_128282   приставка, сайт, номер на сайте
--     детектив      detective_player
--     блог          user_admin
--
-- Имя человека при этом лежит рядом, в `title` («Собеседник», «Gerard»).
--
-- Разница между «именем» и «ключом» здесь не вкусовая. Пока поле звалось
-- `name`, оно приезжало в workflow переменной `companion_name`, и всякий,
-- читавший промпт, видел «имя собеседника» — а там был `dating_343_128282`.
-- Отсюда и сегодняшняя путаница: факты ключевались «именем», имя собеседника
-- искали не в той переменной, а `%agent_name%` в промпте годами выдавал имя
-- агента за имя девушки.
--
-- ## ⚠ Переименование, а не новое поле
--
-- Уникальное поле уже есть — заводить второе значило бы держать два ключа на
-- одну запись и следить, чтобы они не разошлись. Меняется **имя столбца**,
-- данные остаются на месте.
--
-- ## ⚠⚠ Что обязано поехать вместе
--
-- Правка задевает семь мест в коде соседа; ни одно не переживёт переименования
-- само:
--
--     src/tool/companion/companion.py        три поиска по `name`
--     src/uvicorn/routers/companion/…        поиск и заведение
--     src/uvicorn/routers/chat/chat.py       `companion_name=entity.get('name')`
--     data/…/admin/session.html              показ в списке
--
-- Порядок: **сперва код, потом схема**. Наоборот процесс упал бы на первом же
-- запросе — колонки `name` уже нет, а код о ней ещё спрашивает.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'name') AS есть_name,
       (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'unique_id') AS есть_unique_id,
       (SELECT COUNT(*) FROM `companion`) AS записей;

-- ── Переименование ──────────────────────────────────────────────────────────
--
-- ⚠⚠ `RENAME COLUMN`, а не `CHANGE`: он не трогает тип и не требует его
-- повторять. Повторённый тип — лишний повод ошибиться, а `char(25)` здесь
-- осмыслен: `dating_343_128282` это 17 знаков, запас невелик.
--
-- ⚠ Уникальный ключ переезжает **сам**: индекс живёт на столбце, а не на имени.
-- Имя индекса (`un_companion_name`) при этом останется прежним — переименовывать
-- его отдельно незачем, оно нигде не упоминается.
--
-- ⚠ Идемпотентность: повторный прогон упал бы «Unknown column 'name'», поэтому
-- переименование идёт **подготовленным запросом** и только если столбец есть.
SET @sql = IF(
    (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
      WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
        AND `COLUMN_NAME` = 'name') > 0,
    'ALTER TABLE `companion` RENAME COLUMN `name` TO `unique_id`',
    'SELECT ''столбец уже переименован'' AS _');

PREPARE go FROM @sql;
EXECUTE go;
DEALLOCATE PREPARE go;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'unique_id') AS есть_unique_id,
       (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'name') AS остался_name,
       -- ⚠ Уникальность обязана уцелеть: без неё два собеседника получат один
       -- ключ, и факты о них сольются в один документ.
       (SELECT COUNT(*) FROM `information_schema`.`STATISTICS`
         WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'companion'
           AND `COLUMN_NAME` = 'unique_id' AND `NON_UNIQUE` = 0) AS ключ_уникален,
       (SELECT COUNT(*) FROM `companion`) AS записей;
