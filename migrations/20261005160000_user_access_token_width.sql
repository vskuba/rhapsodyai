-- Токен доступа: столбец расширяется до 64 знаков — иначе выданный не работает.
--
-- ⚠⚠ ЭТО НЕ КОСМЕТИКА, А МОЛЧАЛИВАЯ ПОЛОМКА. Общий скелет панели выдаёт токен
-- через `auth_token_new()` — `secrets.token_urlsafe(32)`, то есть **43 знака**.
-- Столбец здесь `char(36)`: ровно под старый uuid4. MySQL в нестрогом режиме
-- обрезает молча, и получается так:
--
--   ручка вернула  7zY9Ecoa7mkGulBt79HF…  (43 знака)
--   в базе лежит   7zY9Ecoa7mkGulBt79HF…  (36 знаков)
--   этим токеном   → 401
--
-- Проверено живьём на этой базе: выданный ключ не работал ни разу, и ни одна
-- строка об этом не говорила. Человек копировал токен, получал отказ и шёл
-- искать ошибку в заголовках.
--
-- ⚠ У двух соседних проектов столбец давно `varchar(64)` — договор скелета
-- именно такой. Здесь он просто отстал: таблица пережила переход с uuid4.
--
-- ЧТО МЕНЯЕТСЯ: ширина одного столбца. Значения не трогаются — выданные раньше
-- 36-знаковые токены продолжают работать.
--
-- ПОВТОРНЫЙ ПРОГОН БЕЗВРЕДЕН: `MODIFY COLUMN` ставит столбец в описанное
-- состояние, сколько его ни гоняй, а сам столбец есть на любой установке.

SELECT 'ДО' AS mark, COLUMN_TYPE AS token_column
  FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_access_token'
   AND COLUMN_NAME = 'token';

ALTER TABLE `user_access_token`
    MODIFY COLUMN `token` VARCHAR(64) NOT NULL
    COMMENT 'secrets.token_urlsafe(32) — 43 знака; запас до 64';

SELECT 'ПОСЛЕ' AS mark, COLUMN_TYPE AS token_column,
       (SELECT COUNT(*) FROM `user_access_token`) AS tokens
  FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_access_token'
   AND COLUMN_NAME = 'token';
