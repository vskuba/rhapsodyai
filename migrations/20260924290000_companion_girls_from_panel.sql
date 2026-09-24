-- Девушки с панели DatingAi заводятся в справочнике собеседников (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Прошлая миграция положила локально факты с прода и завела под них две записи —
-- `1430354_Renata` и `9021_Diana`. Обе собраны не тем правилом, и это видно
-- сразу, как только смотришь на панель:
--
--     было     9021_Diana      9021 — цифры из почты bogiladiana9021@bigmir.net
--     стало  643694_diana    643694 — её настоящий номер на сайте (`site_uid`)
--
-- `9021` не значит ничего: это обрывок адреса. У Solomia цифр в почте нет вовсе,
-- и прежнее правило отдавало ей ключ `solomiakorchinska@bigmir.net_Solomia`.
--
-- ## Правило ключа
--
--     {номер анкеты на сайте}_{имя латиницей в нижнем регистре}
--
-- Номер — тот самый, что панель показывает карточкой как «ID» (`profile.html`,
-- `ID ${row.site_uid}`). Имя — из той же карточки, опущенное в нижний регистр.
--
-- ⚠ У Renata `site_uid` нет — она заведена до того, как его начали снимать; её
-- номер лежит в `profile.id` и равен логину. Берём его: иначе единственная
-- анкета с 32 накопленными фактами осталась бы без записи.
--
-- ⚠ Имена всех четырнадцати уже латиница, поэтому нижний регистр — всё, что
-- нужно. Появись кириллическое имя, его придётся переводить в латиницу **до**
-- заведения: ключ обязан оставаться в одном алфавите.
--
-- ## ⚠⚠ Два имени на четверых, и ключ их разводит
--
-- Diana две, Elena две, Natalia две. Ровно поэтому имя само по себе ключом быть
-- не может, и ровно поэтому 28 фактов `elena` с прода пришлось удалить: они
-- ключевались одним именем, и чьи они — не знает никто.
--
-- ## Что ещё делает миграция
--
-- Переводит два уже лежащих документа фактов на новые ключи. Без этого они
-- ссылались бы на записи, которых больше нет, а поиск в Qdrant не нашёл бы
-- ничего — молча, как и прежде.
--
-- ⚠ Qdrant этой миграцией **не правится**: `document_id` лежит в payload точки,
-- и переносится он пересинхронизацией (`qdrant_synced = 0` ниже плюс
-- `qdrant_fact_sync`). Правка мимо неё развела бы базу и поиск.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion`) AS записей,
       (SELECT GROUP_CONCAT(DISTINCT `document_id` ORDER BY `document_id`
                            SEPARATOR ', ') FROM `fact`) AS ключи_фактов;

-- ── Записи прежним правилом уходят ──────────────────────────────────────────
--
-- ⚠ Именно эти две, а не «всё, что не по образцу»: список известен, а правило по
-- виду снесло бы завтра что-нибудь живое.
DELETE FROM `companion` WHERE `unique_id` IN ('1430354_Renata', '9021_Diana');

-- ── Четырнадцать девушек с панели ───────────────────────────────────────────
--
-- ⚠ `title` — имя как его показывают человеку («Diana»), а не кусок ключа. В
-- списке собеседников панели девушка должна зваться по-человечески.
INSERT INTO `companion` (`unique_id`, `title`)
SELECT one.`key`, one.`title` FROM (
        SELECT '1430354_renata' AS `key`, 'Renata' AS `title`
  UNION SELECT '643694_diana',    'Diana'
  UNION SELECT '418024_diana',    'Diana'
  UNION SELECT '622715_ekaterina','Ekaterina'
  UNION SELECT '599939_elena',    'Elena'
  UNION SELECT '486221_elena',    'Elena'
  UNION SELECT '748852_nadezhda', 'Nadezhda'
  UNION SELECT '363331_natalia',  'Natalia'
  UNION SELECT '201992_natalia',  'Natalia'
  UNION SELECT '413636_oksana',   'Oksana'
  UNION SELECT '999029_olga',     'Olga'
  UNION SELECT '924237_solomia',  'Solomia'
  UNION SELECT '124968_victoria', 'Victoria'
  UNION SELECT '773664_yulia',    'Yulia') AS one
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `companion`) x
                    WHERE x.`unique_id` = one.`key`);

-- ── Факты переезжают на новые ключи ─────────────────────────────────────────
--
-- ⚠ У Renata меняется только регистр, у Diana — и номер: `9021` был обрывком
-- почтового адреса.
UPDATE `fact` SET `document_id` = '1430354_renata'
 WHERE `document_id` = '1430354_Renata';

UPDATE `fact` SET `document_id` = '643694_diana'
 WHERE `document_id` = '9021_Diana';

-- ⚠⚠ Пересинхронизацию заказываем **здесь**, а не отдельной командой: ключ в
-- Qdrant живёт копией, и забыть про неё значит получить базу, где всё верно, и
-- поиск, который ничего не находит. Старые точки перед синком надо снести —
-- сменившийся `document_id` не заменяет их, а добавляет ещё одни.
UPDATE `fact` SET `qdrant_synced` = 0
 WHERE `document_id` IN ('1430354_renata', '643694_diana');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion`) AS записей,
       (SELECT COUNT(*) FROM `companion` WHERE `unique_id` REGEXP '^[0-9]+_[a-z]+$')
         AS девушек_по_образцу,
       (SELECT GROUP_CONCAT(DISTINCT `document_id` ORDER BY `document_id`
                            SEPARATOR ', ') FROM `fact`) AS ключи_фактов,
       -- ⚠ Главная проверка: у каждого документа фактов есть своя запись. Не
       -- сойдись — факты повисли бы на девушке, которой в справочнике нет.
       (SELECT COUNT(DISTINCT f.`document_id`) FROM `fact` f
         WHERE NOT EXISTS (SELECT 1 FROM `companion` c
                            WHERE c.`unique_id` = f.`document_id`))
         AS документов_без_записи,
       (SELECT COUNT(*) FROM `fact` WHERE `qdrant_synced` = 0) AS ждут_синка;
