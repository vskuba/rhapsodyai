-- Доставка реплики как факт строки: `companion_session.delivered_at` (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Шаг `dating_talk` «Разговор: записать ответ» пишет обмен **внутри прогона** —
-- до того, как ответ вернётся в DatingAi и панель попробует его отправить. У
-- панели строка в переписке появляется только при удачной отправке, у нас —
-- всегда. Неудача отправки расходит две истории: в переписке реплики нет, в
-- памяти агента есть, и следующий ответ строится так, будто сказанное сказано.
--
-- Отметку ставит DatingAi отдельным вызовом, когда реплика реально ушла.
--
-- ## ⚠⚠ `NULL` и БЕЗ умолчания
--
-- `NOT NULL DEFAULT CURRENT_TIMESTAMP` получил бы от `ALTER` время миграции
-- **всем накопленным строкам** — и недоставленное выглядело бы доставленным сию
-- секунду. Эта грабля уже стоила ложной картины в «Доставке» у DatingAi
-- (`favorite_mail.updated_at`). Неизвестно — значит `NULL`.
--
-- ## Бэкфилл накопленного: решение принято явно
--
-- Без него агент в день выкладки разом забывает переписку со всеми
-- собеседниками и начинает разговоры с нуля. Цена известна и принята: среди
-- отмеченных есть неизвестное число реально не ушедших реплик — это ровно то
-- допущение, на котором система жила до сих пор.
--
-- ⚠ Время берём `answer_at`, а не `NOW()`: это момент, когда реплика была
-- сказана. `NOW()` сделал бы всю прежнюю переписку «доставленной только что».
--
-- Идемпотентность: колонка заводится по условию, бэкфилл не трогает уже
-- проставленное (`delivered_at IS NULL`).

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'companion_session'
           AND COLUMN_NAME = 'delivered_at') AS колонка_есть,
       (SELECT COUNT(*) FROM `companion_session`) AS строк,
       (SELECT COUNT(*) FROM `companion_session`
         WHERE COALESCE(`answer`, '') <> '') AS с_ответом;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'companion_session'
        AND COLUMN_NAME = 'delivered_at') = 0,
    'ALTER TABLE `companion_session`
        ADD COLUMN `delivered_at` DATETIME NULL DEFAULT NULL
            COMMENT ''Когда наш ответ дошёл до собеседника; NULL — не дошёл или ещё не ушёл''',
    'SELECT ''колонка уже есть'' AS пропуск');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE `companion_session`
   SET `delivered_at` = `answer_at`
 WHERE `delivered_at` IS NULL
   AND `answer_at` IS NOT NULL
   AND COALESCE(`answer`, '') <> '';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion_session`
         WHERE `delivered_at` IS NOT NULL) AS отмечено,
       (SELECT COUNT(*) FROM `companion_session`
         WHERE `delivered_at` IS NULL) AS без_отметки;
