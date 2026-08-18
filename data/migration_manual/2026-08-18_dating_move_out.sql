-- Знакомства уехали в отдельный проект DatingAi: сносим их таблицы здесь.
--
-- ЧТО ТЕРЯЕТСЯ. Четыре таблицы целиком:
--   dating_contact  — собеседницы анкет (кэш профилей с сайта)
--   dating_log      — журнал работы по учётке
--   dating_message  — вся переписка
--   dating_girl     — учётки анкет: логины, пароли, снятый вход (storage_state)
--
-- `DROP TABLE` необратим. На локальной установке перед прогоном было 1 учётка,
-- 22 961 сообщение, 23 073 строки журнала и 200 собеседниц — все перенесены в
-- DatingAi (`dating.dating_girl` id=3 и связанные). На проде числа свои: их
-- показывает первый блок SELECT ниже, и смотреть его надо ДО прогона.
--
-- ПОРЯДОК ОБЯЗАТЕЛЕН: сначала зависимые, потом `dating_girl`. Иначе внешние ключи
-- не дадут уронить таблицу, и файл встанет на первом же DROP.
--
-- ЧТО ОСТАЁТСЯ ЗДЕСЬ и трогать это нельзя:
--   * `browser_site` с её `presence` — закладки сайтов нужны DatingAi по HTTP;
--   * `browser_scenario` — сценарии входа, анкеты, диалогов;
--   * агенты анкет (`agent`, имена вида `renata_1430354`), workflow `dating_talk`
--     и `dating_girl_create`, коллекция фактов `dating_girl` в `fact` и Qdrant.
--   Всё это про агентов и браузер, а не про анкеты, и уезжать не должно.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup` и перенос данных в DatingAi.
-- Прогон — по SSH-туннелю к прод-базе (см. `.claude/docs/migration.md`, 3.1).

USE `project`;

-- 1. Что сейчас есть — смотреть ДО удаления.
--
--    Через подготовленный запрос, а не прямым SELECT: файл обязан переживать
--    повторный прогон, а после первого таблиц уже нет, и обычный SELECT из них
--    уронил бы весь прогон на второй строке.
SET @есть := (SELECT COUNT(*) FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dating_girl');

SET @sql := IF(@есть,
    "SELECT 'ДО УДАЛЕНИЯ' AS этап,
            (SELECT COUNT(*) FROM dating_girl)    AS учёток,
            (SELECT COUNT(*) FROM dating_message) AS сообщений,
            (SELECT COUNT(*) FROM dating_log)     AS строк_журнала,
            (SELECT COUNT(*) FROM dating_contact) AS собеседниц",
    "SELECT 'ТАБЛИЦ ЗНАКОМСТВ УЖЕ НЕТ — повторный прогон' AS этап");
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- 2. Логины учёток — чтобы в отчёте осталось, что именно уехало.
SET @sql := IF(@есть,
    "SELECT id, site_id, login, role, status FROM dating_girl ORDER BY id",
    "SELECT 'учёток нет' AS учётки");
PREPARE это FROM @sql; EXECUTE это; DEALLOCATE PREPARE это;

-- 3. Снос. `IF EXISTS` — чтобы повторный прогон не падал: файл догоняет живую
--    базу, а не создаёт её, и второй запуск должен быть безобидным.
DROP TABLE IF EXISTS `dating_contact`;
DROP TABLE IF EXISTS `dating_log`;
DROP TABLE IF EXISTS `dating_message`;
DROP TABLE IF EXISTS `dating_girl`;

-- 4. Проверка: таблиц знакомств больше нет, а браузерные на месте.
SELECT 'ПОСЛЕ УДАЛЕНИЯ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = 'project' AND TABLE_NAME LIKE 'dating\_%') AS осталось_таблиц_dating,
       (SELECT COUNT(*) FROM browser_site)     AS сайтов_закладок,
       (SELECT COUNT(*) FROM browser_scenario) AS сценариев;

-- 5. Агенты анкет остаются. Показываем их, чтобы было видно: они не тронуты.
SELECT a.id, a.name, a.workflow_id
  FROM agent a JOIN node n ON n.id = a.node_id
 WHERE n.name = 'Dating' ORDER BY a.id;
