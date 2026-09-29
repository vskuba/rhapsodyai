-- Отставшие ключи собеседников сливаются с их же новыми записями (2026-09-29)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `…_companion_key_person_shaped` перевёл ключи в вид «номер + имя» и перенёс
-- переписку. Но панель в это время работала: один заход `dating_talk` (trace
-- 59211, 03:02:03) успел уйти со старым ключом за три секунды до того, как
-- выкладка подняла процесс с новым кодом. Шаг `companion_create` завёл под ним
-- запись заново — и история пары **раздвоилась**:
--
--     id 14  329110_brian_ritter        43 обмена
--     id 83  10_dating_343_329110        1 обмен
--
-- Пара одна, записей две: агент читает ленту по ключу и увидит только половину.
-- Здесь это сливается обратно.
--
-- ## ⚠⚠⚠ Цель ищется по НОМЕРУ, а не по имени — и это принципиально
--
-- В первой миграции пары были перечислены значениями, потому что новый ключ надо
-- было **посчитать**, а `agent_key` в SQL не повторить (`René` → `ren`, а
-- `LOWER()` → `rené`).
--
-- Здесь считать нечего: новая запись уже есть, и обе половины несут **один и тот
-- же номер**. Он хвост старого ключа и голова нового, то есть сличается точным
-- равенством отрезков:
--
--     SUBSTRING_INDEX(старый, '_', -1)  =  10_dating_343_329110 → 329110
--     SUBSTRING_INDEX(новый,  '_',  1)  =  329110_brian_ritter  → 329110
--
-- Транслита это не требует, поэтому правило работает для **любого** отставшего,
-- включая тех, кто отстанет при следующей выкладке. Ради этого миграция написана
-- правилом, а не списком.
--
-- ## ⚠⚠ Почему равенство отрезков, а не `LIKE CONCAT(номер, '\_%')`
--
-- Так и было написано сначала, и **yoyo на этом падал**: его разборщик, встретив
-- экранирование обратными косыми (`REPLACE(…, '\\', '\\\\')`), терял точку с
-- запятой в конце отчётного `SELECT` и склеивал его со следующим `UPDATE` —
-- `1064 … near 'UPDATE companion_session s JOIN companion old …'`. Клиент `mysql`
-- то же самое принимал молча, поэтому репетиция ничего не показала: она гоняет
-- файл клиентом, а прод — yoyo.
--
-- Отсюда правило на будущее: в миграциях **обратных косых не держим**. Равенство
-- отрезков и короче, и точнее `LIKE` — префикс `3291100_…` им не поймается вовсе,
-- тогда как `LIKE '329110%'` поймал бы и слил двух разных людей.
--
-- ## ⚠⚠ Сличаем номер И имя
--
-- Номер уникален у собеседников, но в том же справочнике живут записи девушек
-- (`643694_diana`), и их ключ той же выкройки. Совпади номер девушки с номером
-- мужчины — слияние увело бы переписку в чужую запись. Совпадение имени делает
-- такую встречу невозможной на практике: один номер и одно имя — один человек.
--
-- ## ⚠ У кого новой записи нет — только отчёт
--
-- Такому надо посчитать имя, то есть позвать наш код; молча оставить старый ключ
-- честнее, чем угадать его в SQL. Отчёт в конце такие называет.
--
-- Идемпотентность: второй прогон не находит старых ключей и ничего не делает.
-- Проверено обоими путями — и yoyo, и клиентом.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` LIKE '10_dating_%') AS отставших,
       (SELECT COUNT(*) FROM `companion_session` s
          JOIN `companion` c ON c.`id` = s.`companion_id`
         WHERE c.`unique_id` LIKE '10_dating_%') AS обменов_на_них,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов_всего;

-- ⚠ Показываем, что именно сольётся и куда: ключи читают люди.
SELECT old.`id` AS откуда, old.`unique_id` AS старый,
       fresh.`id` AS куда, fresh.`unique_id` AS новый, fresh.`title` AS имя
  FROM `companion` old
  JOIN `companion` fresh
    ON SUBSTRING_INDEX(fresh.`unique_id`, '_', 1)
     = SUBSTRING_INDEX(old.`unique_id`, '_', -1)
   AND fresh.`title` = old.`title`
   AND fresh.`id` <> old.`id`
 WHERE old.`unique_id` LIKE '10_dating_%';

-- ── 1. Обмены переезжают на новую запись ────────────────────────────────────
--
-- ⚠⚠ До удаления, а не после: связь `companion_session` → `companion` стоит с
-- `ON DELETE CASCADE`, и снеси мы старую запись первой, обмен уехал бы с ней.
UPDATE `companion_session` s
  JOIN `companion` old ON old.`id` = s.`companion_id`
  JOIN `companion` fresh
    ON SUBSTRING_INDEX(fresh.`unique_id`, '_', 1)
     = SUBSTRING_INDEX(old.`unique_id`, '_', -1)
   AND fresh.`title` = old.`title`
   AND fresh.`id` <> old.`id`
   SET s.`companion_id` = fresh.`id`
 WHERE old.`unique_id` LIKE '10_dating_%';

-- ⚠ И нашу сторону тем же правилом: оно обязано быть одним на оба столбца,
-- иначе половина обменов осталась бы на записи, которую шаг 2 счёл бы пустой.
UPDATE `companion_session` s
  JOIN `companion` old ON old.`id` = s.`owner_id`
  JOIN `companion` fresh
    ON SUBSTRING_INDEX(fresh.`unique_id`, '_', 1)
     = SUBSTRING_INDEX(old.`unique_id`, '_', -1)
   AND fresh.`title` = old.`title`
   AND fresh.`id` <> old.`id`
   SET s.`owner_id` = fresh.`id`
 WHERE old.`unique_id` LIKE '10_dating_%';

-- ── 2. Опустевшие старые записи убрать ─────────────────────────────────────
--
-- ⚠ Только те, у которых есть куда было переехать И на которых ничего не
-- осталось: второе условие — предохранитель против каскада.
DELETE old FROM `companion` old
  JOIN `companion` fresh
    ON SUBSTRING_INDEX(fresh.`unique_id`, '_', 1)
     = SUBSTRING_INDEX(old.`unique_id`, '_', -1)
   AND fresh.`title` = old.`title`
   AND fresh.`id` <> old.`id`
 WHERE old.`unique_id` LIKE '10_dating_%'
   AND NOT EXISTS (SELECT 1 FROM `companion_session` s
                    WHERE s.`companion_id` = old.`id` OR s.`owner_id` = old.`id`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` LIKE '10_dating_%') AS отставших_осталось,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов_всего,
       (SELECT COUNT(*) FROM `companion_session` s
         WHERE NOT EXISTS (SELECT 1 FROM `companion` c
                            WHERE c.`id` = s.`companion_id`)) AS обменов_осиротело;

-- ⚠⚠ Кто остался без новой записи: им имя надо считать нашим кодом. Пусто —
-- слились все.
SELECT 'без пары' AS проверка, COUNT(*) AS сколько,
       COALESCE(GROUP_CONCAT(`unique_id` SEPARATOR ' | '), 'нет') AS какие
  FROM `companion` WHERE `unique_id` LIKE '10_dating_%';

-- ⚠ И проверка, что пара снова одна: у номера обязан быть один ключ.
SELECT 'ключей на 329110' AS проверка, COUNT(*) AS сколько,
       COALESCE(GROUP_CONCAT(`unique_id` SEPARATOR ' | '), 'нет') AS какие
  FROM `companion` WHERE `unique_id` LIKE '%329110%';
