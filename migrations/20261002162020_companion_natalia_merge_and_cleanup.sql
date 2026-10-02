-- Последняя Natalia сливается, две пустые записи уходят (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Хвост от `…_companion_girls_merge`. Та миграция слила десять пар, а две
-- записи оставила нарочно: имя делили две анкеты, а круг собеседников не
-- пересекался ни с одной, то есть доказательства не было и выбор был бы
-- монеткой.
--
-- Одну из двух **разрешил человек**: `67_Natalia` — это анкета `201992`.
-- Это знание о своих анкетах, которого в данных нет ни у нас, ни у соседа:
-- истории этих трёх собеседников (`343150_gary_kerns`,
-- `869661_michael_davies`, `506561_don`) у DatingAi уже нет.
--
-- ⚠ `279501_Elena` (4 обмена) **остаётся неразведённой**: про неё решения не
-- было. Имя по-прежнему делят две анкеты (599939 и 486221).
--
-- ## Что переносится
--
--     67_Natalia → 201992_natalia     7 обменов почтой, 25–27.09.2026
--
-- Столкновений по `uq_companion_session_source` нет — проверено на боевых
-- данных перед написанием файла.
--
-- ## Две пустые записи
--
--     Olenka      0 обменов    ключ не вида «{номер}_{имя}», имени взять негде
--     Vadim       0 обменов    то же
--
-- Это остатки ранних проб: ни одной строки разговора ни той, ни другой
-- стороной. Удаление ничего не уносит — проверено обоими счётчиками
-- (`owner_id` и `companion_id` по нулям), и условие удаления всё равно стоит
-- на отсутствии ссылок.
--
-- ⚠⚠ Порядок внутри пары обязателен: сперва перенос, потом удаление. У
-- `companion_session` обе связи с `companion` стоят `ON DELETE CASCADE` —
-- удали запись первой, и обмены уедут вместе с ней.
--
-- Идемпотентность: второй прогон не находит ни старой записи, ни пустых.
-- Проверено прогоном через yoyo дважды со снятой отметкой, на копии боевых
-- таблиц.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion`) AS записей,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов,
       (SELECT COUNT(*) FROM `companion` WHERE `unique_id` = `title`) AS без_имени;

-- 67_Natalia → 201992_natalia: 7 обменов, пару назвал человек
UPDATE `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id` AND o.`unique_id` = '67_Natalia'
  JOIN `companion` n ON n.`unique_id` = '201992_natalia'
   SET s.`owner_id` = n.`id`;

DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` = '67_Natalia' AND s.`id` IS NULL;

-- Пустые записи ранних проб: ни одного разговора ни той, ни другой стороной
DELETE o FROM `companion` o
  LEFT JOIN `companion_session` s
    ON s.`owner_id` = o.`id` OR s.`companion_id` = o.`id`
 WHERE o.`unique_id` IN ('Olenka', 'Vadim') AND s.`id` IS NULL;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion`) AS записей,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов,
       (SELECT COUNT(*) FROM `companion` WHERE `unique_id` = `title`) AS без_имени,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` IN ('67_Natalia', 'Olenka', 'Vadim')) AS убранных_осталось,
       (SELECT COUNT(*) FROM `companion_session` s
          JOIN `companion` o ON o.`id` = s.`owner_id`
         WHERE o.`unique_id` = '201992_natalia') AS обменов_у_natalia;
