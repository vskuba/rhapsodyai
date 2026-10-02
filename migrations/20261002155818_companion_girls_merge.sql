-- Записи девушек сливаются: один человек — один ключ (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- На странице «Сессии», вкладка «Чат», одна и та же девушка показывалась
-- двумя разговорами: `999029_olga ↔ Gerard` и `Olga ↔ Gerard`. Это не вид, а
-- данные: в `companion` две записи на одного человека.
--
-- Ключ нашей стороны сменил форму, и старые записи остались как были:
--
--     старая   {наш внутренний номер}_{Имя}      70_Olga, 89_Elena, 9021_Diana
--     новая    {номер анкеты на сайте}_{имя}     999029_olga, 599939_elena
--
-- Собеседникам ту же смену уже пережили (`…_companion_key_person_shaped`),
-- девушкам — ни разу. Разрыв заморожен: записи старой формы перестали
-- получать обмены 27.09.2026, всё с тех пор идёт на новые ключи.
--
-- ## ⚠⚠ Цена разрыва — не вид страницы, а ПАМЯТЬ АГЕНТА
--
-- `companion_session_history` собирает ленту для промпта по `unique_id`.
-- Пока записи две, агент не помнит переписку до 27.09: у Elena это 26
-- обменов, у Diana 22, у Oksana 17. Он пишет человеку как незнакомому — ровно
-- та беда, от которой `companion_session` и заводили.
--
-- ## ⚠⚠⚠ ПАРЫ ВЫЧИСЛЕНЫ ПО ДАННЫМ СОСЕДА, А НЕ УГАДАНЫ ПО ИМЕНИ
--
-- Имена НЕ уникальны: в DatingAi две Diana (643694 и 418024), две Elena
-- (599939 и 486221), две Natalia (363331 и 201992). Слить по совпадению имени
-- значило бы сварить память двух разных женщин в одну.
--
-- Поэтому каждая пара доказана, и доказательств два вида:
--
--     имя одно на установку     в DatingAi ровно одна анкета с этим именем
--     общие собеседники         у старой записи и у анкеты один круг людей
--
-- Второе считается так: собеседник в ключе несёт свой номер на сайте
-- (`329110_brian_ritter`), а DatingAi знает, какая анкета с каким номером
-- переписывалась (`message.sender_uid`, `contact.uid`). Пересечение кругов
-- разводит двух Diana однозначно: `120998_Diana` делит с 418024 трёх
-- собеседников из четырёх и с 643694 одного; `9021_Diana` — наоборот.
--
-- ## ⚠⚠ ДВЕ ЗАПИСИ НЕ СЛИВАЮТСЯ, И ЭТО НАРОЧНО
--
--     279501_Elena    4 обмена    ни один собеседник не известен DatingAi
--     67_Natalia      7 обменов   ни один собеседник не известен DatingAi
--
-- У обеих имя делят две анкеты, а круг собеседников не пересекается ни с
-- одной: истории этих людей у соседа уже нет. Доказательства нет — значит
-- выбор был бы монеткой, а цена ошибки — склеенная память двух разных
-- женщин. Эти две записи остаются как есть; разведёт их человек, который
-- знает, чьи это анкеты.
--
-- ## Что делает миграция
--
-- Переносит 120 обменов на выжившие записи, убирает опустевшие старые и
-- ставит десяти записям человеческий заголовок вместо ключа (`999029_olga` →
-- `Olga`): их заводили без имени, и в интерфейсе стоял ключ.
--
-- ⚠ Порядок внутри пары обязателен: сперва перенос, потом удаление. У
-- `companion_session` обе связи с `companion` стоят `ON DELETE CASCADE` —
-- удали запись первой, и обмены уедут вместе с ней. Удаление вдобавок
-- защищено условием «не осталось ни одной ссылки».
--
-- ⚠ Столкновений по `uq_companion_session_source` нет — проверено на боевых
-- данных по всем десяти парам перед написанием файла.
--
-- Идемпотентность: второй прогон не находит старых записей, переносить и
-- удалять нечего, заголовки уже проставлены. Проверено прогоном через yoyo
-- дважды со снятой отметкой.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion`) AS записей,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов,
       (SELECT COUNT(*) FROM `companion` WHERE `unique_id` = `title`) AS без_имени;

-- 93_Ekaterina → 622715_ekaterina: 8 обменов, имя одно на всю установку
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '93_Ekaterina'
  JOIN `companion` n ON n.`unique_id` = '622715_ekaterina'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '93_Ekaterina' AND s.`id` IS NULL;

-- 92_Nadezhda → 748852_nadezhda: 2 обменов, имя одно на всю установку
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '92_Nadezhda'
  JOIN `companion` n ON n.`unique_id` = '748852_nadezhda'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '92_Nadezhda' AND s.`id` IS NULL;

-- 8511_Oksana → 413636_oksana: 17 обменов, имя одно на всю установку
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '8511_Oksana'
  JOIN `companion` n ON n.`unique_id` = '413636_oksana'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '8511_Oksana' AND s.`id` IS NULL;

-- 70_Olga → 999029_olga: 6 обменов, имя одно на всю установку
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '70_Olga'
  JOIN `companion` n ON n.`unique_id` = '999029_olga'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '70_Olga' AND s.`id` IS NULL;

-- 1694_Victoria → 124968_victoria: 3 обменов, имя одно на всю установку
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '1694_Victoria'
  JOIN `companion` n ON n.`unique_id` = '124968_victoria'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '1694_Victoria' AND s.`id` IS NULL;

-- 77_Yulia → 773664_yulia: 15 обменов, имя одно на всю установку
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '77_Yulia'
  JOIN `companion` n ON n.`unique_id` = '773664_yulia'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '77_Yulia' AND s.`id` IS NULL;

-- 120998_Diana → 418024_diana: 22 обменов, общих собеседников 3 из 4 против 1
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '120998_Diana'
  JOIN `companion` n ON n.`unique_id` = '418024_diana'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '120998_Diana' AND s.`id` IS NULL;

-- 9021_Diana → 643694_diana: 14 обменов, общих собеседников 2 из 5 против 1
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '9021_Diana'
  JOIN `companion` n ON n.`unique_id` = '643694_diana'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '9021_Diana' AND s.`id` IS NULL;

-- 89_Elena → 599939_elena: 26 обменов, общих собеседников 3 из 8 против 0
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '89_Elena'
  JOIN `companion` n ON n.`unique_id` = '599939_elena'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '89_Elena' AND s.`id` IS NULL;

-- 95_Natalia → 363331_natalia: 7 обменов, общих собеседников 1 из 1 против 0
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '95_Natalia'
  JOIN `companion` n ON n.`unique_id` = '363331_natalia'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '95_Natalia' AND s.`id` IS NULL;

-- Заголовки: имя человека вместо ключа (их присылает DatingAi, но прислал не всем)
UPDATE `companion` SET `title` = 'Victoria' WHERE `unique_id` = '124968_victoria' AND `title` <> 'Victoria';
UPDATE `companion` SET `title` = 'Natalia' WHERE `unique_id` = '201992_natalia' AND `title` <> 'Natalia';
UPDATE `companion` SET `title` = 'Oksana' WHERE `unique_id` = '413636_oksana' AND `title` <> 'Oksana';
UPDATE `companion` SET `title` = 'Diana' WHERE `unique_id` = '418024_diana' AND `title` <> 'Diana';
UPDATE `companion` SET `title` = 'Elena' WHERE `unique_id` = '486221_elena' AND `title` <> 'Elena';
UPDATE `companion` SET `title` = 'Elena' WHERE `unique_id` = '599939_elena' AND `title` <> 'Elena';
UPDATE `companion` SET `title` = 'Ekaterina' WHERE `unique_id` = '622715_ekaterina' AND `title` <> 'Ekaterina';
UPDATE `companion` SET `title` = 'Nadezhda' WHERE `unique_id` = '748852_nadezhda' AND `title` <> 'Nadezhda';
UPDATE `companion` SET `title` = 'Yulia' WHERE `unique_id` = '773664_yulia' AND `title` <> 'Yulia';
UPDATE `companion` SET `title` = 'Olga' WHERE `unique_id` = '999029_olga' AND `title` <> 'Olga';
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion`) AS записей,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов,
       (SELECT COUNT(*) FROM `companion` WHERE `unique_id` = `title`) AS без_имени,
       (SELECT COUNT(*) FROM `companion` WHERE `unique_id` IN
           ('93_Ekaterina','92_Nadezhda','8511_Oksana','70_Olga','1694_Victoria',
            '77_Yulia','120998_Diana','9021_Diana','89_Elena','95_Natalia')) AS старых_осталось;
