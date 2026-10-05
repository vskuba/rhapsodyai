-- Токены доступа: пометка и время выдачи — договор общего скелета панели.
--
-- ЗАЧЕМ. Управление людьми переехало в общий скелет
-- (`py_modules/panel_/`, страница `.claude/docs-common/panel.md`). Он ждёт у
-- таблицы токенов четыре поля сверх ключа: `token`, `note`, `created_at` и связь
-- с человеком каскадом. Каскад здесь уже есть, а двух столбцов не было.
--
-- ⚠⚠ ПОМЕТКА — НЕ УКРАШЕНИЕ. Токен виден целиком **один раз**, в ответ на
-- выдачу; дальше в списке остаются пометка и хвост в шесть знаков. Без пометки
-- список действующих ключей выглядит как «три токена по шесть знаков», и
-- отозвать чужой, не отозвав свой, нельзя — приходится отзывать все.
--
-- ⚠ ВРЕМЯ ВЫДАЧИ ставится прошлым для уже выданных: честного значения для них
-- нет, и `NOW()` соврал бы, будто все ключи выданы в день миграции. Умолчание
-- столбца при этом нормальное — новые получат своё настоящее.
--
-- ЧТО МЕНЯЕТСЯ: две колонки в `user_access_token`. Значения токенов не
-- трогаются вовсе — выданные ключи продолжают работать.
--
-- ПОВТОРНЫЙ ПРОГОН: страховка `information_schema` ниже — колонка уже стоит,
-- и `ADD COLUMN` упал бы.

SELECT 'ДО' AS mark, COUNT(*) AS tokens FROM `user_access_token`;

SET @has_note := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_access_token'
       AND COLUMN_NAME = 'note');

SET @sql := IF(@has_note = 0,
    'ALTER TABLE `user_access_token`
        ADD COLUMN `note` VARCHAR(190) NOT NULL DEFAULT ''''
            COMMENT ''кому выдан: токен виден целиком только при выдаче''',
    'SELECT ''note уже стоит'' AS skipped');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_at := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_access_token'
       AND COLUMN_NAME = 'created_at');

SET @sql := IF(@has_at = 0,
    'ALTER TABLE `user_access_token`
        ADD COLUMN `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
    'SELECT ''created_at уже стоит'' AS skipped');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ⚠ Уже выданным — заведомо прошлая дата, а не время миграции: «когда выдан»
-- про них неизвестно, и выдумывать сегодняшний день значит соврать в столбце,
-- по которому потом будут решать, какой ключ пора отозвать.
UPDATE `user_access_token`
   SET `created_at` = '2000-01-01 00:00:00'
 WHERE `created_at` >= CURRENT_DATE;

SELECT 'ПОСЛЕ' AS mark, COUNT(*) AS tokens,
       SUM(`note` = '') AS without_note FROM `user_access_token`;
