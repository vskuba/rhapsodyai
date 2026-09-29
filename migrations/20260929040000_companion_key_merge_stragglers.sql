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
-- же номер** — он хвост старого ключа (`10_dating_343_329110`) и голова нового
-- (`329110_brian_ritter`). Сличение по номеру никакого транслита не требует,
-- поэтому миграция работает для **любого** отставшего, включая тех, кто отстанет
-- при следующей выкладке. Ради этого она и написана правилом, а не списком.
--
-- ⚠ Подчёркивание в образце обязательно: `LIKE '329110\_%'` не поймает
-- `3291100_...`, а `LIKE '329110%'` поймал бы — и слил бы двух разных людей.
--
-- ## ⚠ У кого новой записи нет — только отчёт
--
-- Такому надо посчитать имя, то есть позвать наш код; молча оставить старый ключ
-- честнее, чем угадать его в SQL. Отчёт в конце такие называет.
--
-- Идемпотентность: второй прогон не находит старых ключей и ничего не делает.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` LIKE '10\_dating\_%') AS отставших,
       (SELECT COUNT(*) FROM `companion_session` s
          JOIN `companion` c ON c.`id` = s.`companion_id`
         WHERE c.`unique_id` LIKE '10\_dating\_%') AS обменов_на_них,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов_всего;

-- ⚠ Показываем, что именно сольётся и куда: ключи читают люди.
SELECT old.`id` AS откуда, old.`unique_id` AS старый,
       fresh.`id` AS куда, fresh.`unique_id` AS новый, fresh.`title`
  FROM `companion` old
  JOIN `companion` fresh
    ON fresh.`unique_id` LIKE CONCAT(
         REPLACE(REPLACE(SUBSTRING_INDEX(old.`unique_id`, '_', -1),
                         '\\', '\\\\'), '_', '\\_'), '\_%')
 WHERE old.`unique_id` LIKE '10\_dating\_%' AND fresh.`id` <> old.`id`;

-- ── 1. Обмены переезжают на новую запись ────────────────────────────────────
--
-- ⚠⚠ До удаления, а не после: связь `companion_session` → `companion` стоит с
-- `ON DELETE CASCADE`, и снеси мы старую запись первой, обмен уехал бы с ней.
UPDATE `companion_session` s
  JOIN `companion` old ON old.`id` = s.`companion_id`
  JOIN `companion` fresh
    ON fresh.`unique_id` LIKE CONCAT(
         REPLACE(REPLACE(SUBSTRING_INDEX(old.`unique_id`, '_', -1),
                         '\\', '\\\\'), '_', '\\_'), '\_%')
   SET s.`companion_id` = fresh.`id`
 WHERE old.`unique_id` LIKE '10\_dating\_%' AND fresh.`id` <> old.`id`;

UPDATE `companion_session` s
  JOIN `companion` old ON old.`id` = s.`owner_id`
  JOIN `companion` fresh
    ON fresh.`unique_id` LIKE CONCAT(
         REPLACE(REPLACE(SUBSTRING_INDEX(old.`unique_id`, '_', -1),
                         '\\', '\\\\'), '_', '\\_'), '\_%')
   SET s.`owner_id` = fresh.`id`
 WHERE old.`unique_id` LIKE '10\_dating\_%' AND fresh.`id` <> old.`id`;

-- ── 2. Опустевшие старые записи убрать ─────────────────────────────────────
--
-- ⚠ Только те, у которых есть куда было переехать И на которых ничего не
-- осталось: условие — предохранитель против каскада.
DELETE old FROM `companion` old
  JOIN `companion` fresh
    ON fresh.`unique_id` LIKE CONCAT(
         REPLACE(REPLACE(SUBSTRING_INDEX(old.`unique_id`, '_', -1),
                         '\\', '\\\\'), '_', '\\_'), '\_%')
 WHERE old.`unique_id` LIKE '10\_dating\_%' AND fresh.`id` <> old.`id`
   AND NOT EXISTS (SELECT 1 FROM `companion_session` s
                    WHERE s.`companion_id` = old.`id` OR s.`owner_id` = old.`id`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion`
         WHERE `unique_id` LIKE '10\_dating\_%') AS отставших_осталось,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов_всего,
       (SELECT COUNT(*) FROM `companion_session` s
         WHERE NOT EXISTS (SELECT 1 FROM `companion` c
                            WHERE c.`id` = s.`companion_id`)) AS обменов_осиротело;

-- ⚠⚠ Кто остался без новой записи: им имя надо считать нашим кодом. Пусто —
-- слились все.
SELECT 'без пары' AS проверка, COUNT(*) AS сколько,
       COALESCE(GROUP_CONCAT(CONCAT(`unique_id`, ' («', `title`, '»)')
                             SEPARATOR '; '), '—') AS какие
  FROM `companion` WHERE `unique_id` LIKE '10\_dating\_%';

-- ⚠ И проверка, что пара снова одна: у номера обязан быть один ключ.
SELECT 'ключей на 329110' AS проверка, COUNT(*) AS сколько,
       GROUP_CONCAT(`unique_id` SEPARATOR '; ') AS какие
  FROM `companion` WHERE `unique_id` LIKE '%329110%';
