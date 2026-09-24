-- Локальные факты и собеседники — снимок прода, ключи по новому образцу
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Локально в `fact` лежали следы тестов: 413 фактов под старыми ключами, вперемешку
-- с боевыми именами. По ним нельзя ни проверить новый формат ключа, ни увидеть,
-- что он вправду работает. Обе таблицы заменяются снимком прода, а ключи по
-- дороге приводятся к образцу, который теперь собирает шаг «Ключи»:
--
--     девушка       {номер}_{имя}          1430354_Renata
--     собеседник    {companion_id}_{имя}   10_dating_343_128282
--     их пара       {ключ девушки}_{ключ собеседника}
--
-- ## ⚠ Что вправду есть на проде
--
-- Только девушки: 116 фактов, 5 документов, коллекция `dating_girl`.
-- `dating_companion` и `dating_talk` **пусты** — переносить оттуда нечего.
--
-- ## ⚠⚠ Три ключа из пяти в образец не переводятся, и это решение
--
--     renata_1430354  32  user 7  → 1430354_Renata   профиль 2, логин 1430354
--     diana_9021      23  user 7  → 9021_Diana       профиль 40
--     masha           31  user 1  → удаляется        анкеты с таким именем нет нигде
--     elena           28  user 1  → удаляется        две Elena (43 и 44), чья — неизвестно
--     dating_girl_universal 2  user 7 → удаляется    это имя агента, а не девушки
--
-- ⚠ Владелец разделяет их сам: боевые факты пишет `dating_service` (7), а `masha`
-- и `elena` числятся за `admin` — то есть заведены руками до того, как у DatingAi
-- появилась своя учётка. Догадка тут не нужна, граница видна в данных.
--
-- ⚠⚠ Переложить их «как-нибудь» нельзя: `elena` без номера не говорит, чья это
-- память, а отдать её одной из двух живых анкет значит приписать человеку чужие
-- слова.
--
-- ## ⚠⚠ Собеседников сносим при ВКЛЮЧЁННЫХ проверках
--
-- `agent_session.companion_id` ведёт сюда правилом `ON DELETE SET NULL`, и таких
-- сессий локально 39 524. Правило срабатывает **только пока проверки включены**:
-- погасив их «чтобы не мешали», мы удалили бы записи, а номера в сессиях остались
-- бы висеть на несуществующих — и база молча стала бы битой. Проверки гасятся
-- ровно на одну вставку фактов и включаются обратно.
--
-- ## ⚠ Локальная база — рабочая, не боевая
--
-- Снос целиком уместен здесь и **только здесь**. На проде такая миграция стёрла бы
-- накопленное; поедет туда — перенос ключей надо делать `UPDATE`-ом.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `fact`) AS фактов,
       (SELECT COUNT(*) FROM `companion`) AS собеседников,
       (SELECT COUNT(*) FROM `agent_session` WHERE `companion_id` IS NOT NULL)
         AS сессий_со_ссылкой;

-- ── Чистка ──────────────────────────────────────────────────────────────────
--
-- ⚠ `DELETE`, а не `TRUNCATE`: вторая не запускает `ON DELETE SET NULL` вовсе —
-- она не удаляет строки, а пересоздаёт таблицу. Сессии остались бы с висящими
-- номерами ровно так же, как при погашенных проверках.
DELETE FROM `fact`;
DELETE FROM `companion`;

-- ── Собеседники с прода ─────────────────────────────────────────────────────
--
-- ⚠ Столбец переименован под нашу схему: у прода он ещё `name`, у нас уже
-- `unique_id` (`…_companion_unique_id`).
INSERT INTO `companion` (`id`, `unique_id`, `title`) VALUES (1,'Vadim','Vadim'),(2,'Olenka','Olenka'),(3,'user_admin','admin'),(4,'detective_player','Игрок'),(10,'dating_person','Собеседник');

-- ── Факты с прода ───────────────────────────────────────────────────────────
--
-- ⚠⚠ Здесь и только здесь проверки гасятся: прод пишет факты от учётки
-- `dating_service` под номером 7, а локально та же учётка живёт под своим
-- номером. Вставить как есть при включённых проверках нельзя, а править номера
-- в дампе — значит зашить их в текст. Поэтому кладём как есть и **сразу** ниже
-- переводим владельца поиском по имени учётки.
SET FOREIGN_KEY_CHECKS = 0;

INSERT INTO `fact`(`id`, `collection_id`, `user_id`, `document_id`, `document_title`, `file_id`, `category`, `language`, `document`, `tags`, `qdrant_synced`, `verify_status`, `verified_at`, `created_at`) VALUES (1,2,1,'masha','Маша',NULL,'биография','ru','Мне 27 лет','age',1,'ok','2026-07-26 21:15:07','2026-07-26 13:12:35'),(2,2,1,'masha','Маша',NULL,'биография','ru','Зовут Маша','name',1,'ok','2026-07-26 21:15:07','2026-07-26 13:12:35'),(3,2,1,'masha','Маша',NULL,'биография','ru','Родилась в Виннице, Винницкой области','origin',1,'corrected','2026-07-26 21:15:10','2026-07-26 13:12:35'),(4,2,1,'masha','Маша',NULL,'биография','ru','Проживает в Киеве','residence',1,'ok','2026-07-26 21:15:13','2026-07-26 13:12:35'),(5,2,1,'masha','Маша',NULL,'биография','ru','Проживает в Киеве уже 5 лет','residence_duration',1,'unverifiable','2026-07-26 21:15:16','2026-07-26 13:12:35'),(6,2,1,'masha','Маша',NULL,'биография','ru','Работает графическим дизайнером','work',1,'ok','2026-07-26 21:15:17','2026-07-26 13:12:35'),(7,2,1,'masha','Маша',NULL,'биография','ru','Работает в небольшой студии','workplace',1,'ok','2026-07-26 21:16:16','2026-07-26 13:12:35'),(8,2,1,'masha','Маша',NULL,'биография','ru','Училась в КПИ на издательском деле','education',1,'unverifiable','2026-07-26 21:17:19','2026-07-26 13:12:35'),(9,2,1,'masha','Маша',NULL,'биография','ru','Снимает однокомнатную квартиру','housing',1,'ok','2026-07-26 21:18:17','2026-07-26 13:12:35'),(10,2,1,'masha','Маша',NULL,'биография','ru','Квартира находится возле парка','location',1,'ok','2026-07-26 21:18:24','2026-07-26 13:12:35'),(11,2,1,'masha','Маша',NULL,'биография','ru','Живет с котом Марсом','pets',1,'ok','2026-07-26 22:15:07','2026-07-26 13:12:35'),(12,2,1,'masha','Маша',NULL,'биография','ru','Любит пробежки вдоль Днепра','sport',1,'ok','2026-07-26 22:16:08','2026-07-26 13:12:35'),(13,2,1,'masha','Маша',NULL,'биография','ru','Обожает кофе','food',1,'ok','2026-07-26 22:16:08','2026-07-26 13:12:35'),(14,2,1,'masha','Маша',NULL,'биография','ru','Знает все кофейни своего района','cafe',1,'ok','2026-07-26 22:16:09','2026-07-26 13:12:35'),(15,2,1,'masha','Маша',NULL,'биография','ru','Занималась бальными танцами в школьные годы','dance',1,'ok','2026-07-26 22:16:09','2026-07-26 13:12:35'),(16,2,1,'masha','Маша',NULL,'биография','ru','Имеет теплые отношения с родителями','family',1,'ok','2026-07-26 22:16:10','2026-07-26 13:12:35'),(17,2,1,'masha','Маша',NULL,'биография','ru','Созванивается с родителями каждые выходные','parents',1,'ok','2026-07-26 22:17:08','2026-07-26 13:12:35'),(18,2,1,'masha','Маша',NULL,'биография','ru','Мама преподает музыку','parents',1,'ok','2026-07-26 22:17:08','2026-07-26 13:12:35'),(19,2,1,'masha','Маша',NULL,'биография','ru','Папа инженер','parents',1,'ok','2026-07-26 22:17:09','2026-07-26 13:12:35'),(20,2,1,'masha','Маша',NULL,'биография','ru','Имеет младшего брата Артема','siblings',1,'ok','2026-07-26 22:17:09','2026-07-26 13:12:35'),(21,2,1,'masha','Маша',NULL,'биография','ru','Артем студент','siblings',1,'ok','2026-07-26 23:15:05','2026-07-26 13:12:35'),(22,2,1,'masha','Маша',NULL,'биография','ru','Любит путешествовать','travel',1,'ok','2026-07-26 23:15:05','2026-07-26 13:12:35'),(23,2,1,'masha','Маша',NULL,'биография','ru','Была в Польше, Грузии и Италии','travel',1,'ok','2026-07-26 23:15:06','2026-07-26 13:12:35'),(24,2,1,'masha','Маша',NULL,'биография','ru','Мечтает увидеть Японию','travel',1,'ok','2026-07-26 23:15:06','2026-07-26 13:12:35'),(25,2,1,'masha','Маша',NULL,'биография','ru','Не в отношениях','personal_life',1,'ok','2026-07-26 23:15:07','2026-07-26 13:12:35'),(26,2,1,'masha','Маша',NULL,'биография','ru','Рассталась с парнем 2 года назад','personal_life',1,'ok','2026-07-26 23:15:07','2026-07-26 13:12:35'),(27,2,1,'masha','Маша',NULL,'биография','ru','Нет детей','family',1,'ok','2026-07-26 23:16:05','2026-07-26 13:12:35'),(28,2,1,'masha','Маша',NULL,'биография','ru','Хочет иметь семью в будущем','family',1,'ok','2026-07-26 23:16:06','2026-07-26 13:12:35'),(29,2,1,'masha','Маша',NULL,'биография','ru','Любит готовить, особенно выпечку','hobbies',1,'ok','2026-07-26 23:16:07','2026-07-26 13:12:35'),(30,2,1,'masha','Маша',NULL,'биография','ru','Читает современную украинскую литературу','reading',1,'ok','2026-07-26 23:16:07','2026-07-26 13:12:35'),(31,2,1,'masha','Маша',NULL,'биография','ru','По характеру спокойная, но любит посмеяться','character',1,'ok','2026-07-27 00:15:05','2026-07-26 13:12:35'),(32,2,1,'elena','Елена',NULL,'биография','ru','Елена 27 лет','age,biography',1,'ok','2026-07-27 00:15:06','2026-07-26 13:27:07'),(33,2,1,'elena','Елена',NULL,'место рождения','ru','Родилась в Виннице','city,biography',1,'ok','2026-07-27 00:15:06','2026-07-26 13:27:07'),(34,2,1,'elena','Елена',NULL,'место жительства','ru','Живет в Киеве','city,biography',1,'ok','2026-07-27 00:15:07','2026-07-26 13:27:07'),(35,2,1,'elena','Елена',NULL,'продолжительность проживания','ru','Проживает в Киеве 5 лет','duration,biography',1,'ok','2026-07-27 00:15:07','2026-07-26 13:27:07'),(36,2,1,'elena','Елена',NULL,'работа','ru','Работает графическим дизайнером','work,career',1,'ok','2026-07-27 00:15:08','2026-07-26 13:27:07'),(37,2,1,'elena','Елена',NULL,'место работы','ru','Работает в небольшой студии','work,studio',1,'ok','2026-07-27 00:16:05','2026-07-26 13:27:07'),(38,2,1,'elena','Елена',NULL,'образование','ru','Училась в КПИ на издательском деле','education,university',1,'ok','2026-07-27 00:16:08','2026-07-26 13:27:07'),(39,2,1,'elena','Елена',NULL,'жилищные условия','ru','Снимает однокомнатную квартиру','housing',1,'ok','2026-07-27 00:16:08','2026-07-26 13:27:07'),(40,2,1,'elena','Елена',NULL,'местоположение жилья','ru','Квартира находится возле парка','location,parks',1,'ok','2026-07-27 00:16:09','2026-07-26 13:27:07'),(41,2,1,'elena','Елена',NULL,'семья','ru','Живет с котом Марсом','family,pets',1,'ok','2026-07-27 01:15:05','2026-07-26 13:27:07'),(42,2,1,'elena','Елена',NULL,'спорт','ru','Любит пробежки вдоль Днепра','sport,running',1,'ok','2026-07-27 01:15:05','2026-07-26 13:27:07'),(43,2,1,'elena','Елена',NULL,'питание','ru','Обожает кофе','food,coffee',1,'ok','2026-07-27 01:15:06','2026-07-26 13:27:07'),(44,2,1,'elena','Елена',NULL,'знания','ru','Знает все кофейни своего района','knowledge,cafe',1,'ok','2026-07-27 01:15:06','2026-07-26 13:27:07'),(45,2,1,'elena','Елена',NULL,'хобби','ru','Занималась бальными танцами в школьные годы','hobbies,dance',1,'ok','2026-07-27 01:15:07','2026-07-26 13:27:07'),(46,2,1,'elena','Елена',NULL,'отношения с родителями','ru','Имеет теплые отношения с родителями','relationships,parents',1,'ok','2026-07-27 01:16:04','2026-07-26 13:27:07'),(47,2,1,'elena','Елена',NULL,'родители','ru','Мама преподает музыку','parents,music',1,'ok','2026-07-27 01:16:05','2026-07-26 13:27:07'),(48,2,1,'elena','Елена',NULL,'родители','ru','Папа инженер','parents,engineer',1,'ok','2026-07-27 01:16:05','2026-07-26 13:27:07'),(49,2,1,'elena','Елена',NULL,'брат','ru','Имеет младшего брата Артема','siblings,artem',1,'ok','2026-07-27 01:17:06','2026-07-26 13:27:07'),(50,2,1,'elena','Елена',NULL,'брат','ru','Артем студент','siblings,student',1,'ok','2026-07-27 01:17:07','2026-07-26 13:27:07'),(51,2,1,'elena','Елена',NULL,'путешествия','ru','Путешествовала в Польшу, Грузию и Италию','travel,country',1,'ok','2026-07-27 02:15:05','2026-07-26 13:27:07'),(52,2,1,'elena','Елена',NULL,'путешествия','ru','Мечтает посетить Японию','travel,japan',1,'ok','2026-07-27 02:15:05','2026-07-26 13:27:07'),(53,2,1,'elena','Елена',NULL,'любовные отношения','ru','Не находится в отношениях','relationships,solitude',1,'ok','2026-07-27 02:15:06','2026-07-26 13:27:07'),(54,2,1,'elena','Елена',NULL,'любовные отношения','ru','Рассталась с парнем 2 года назад','relationships,breakup',1,'ok','2026-07-27 02:15:06','2026-07-26 13:27:07'),(55,2,1,'elena','Елена',NULL,'семья','ru','Не имеет детей','family,children',1,'ok','2026-07-27 02:15:07','2026-07-26 13:27:07'),(56,2,1,'elena','Елена',NULL,'планы','ru','Хочет иметь семью в будущем','plans,family',1,'ok','2026-07-27 02:16:05','2026-07-26 13:27:07'),(57,2,1,'elena','Елена',NULL,'хобби','ru','Любит готовить, особенно выпечку','hobbies,cooking',1,'ok','2026-07-27 02:16:06','2026-07-26 13:27:07'),(58,2,1,'elena','Елена',NULL,'интересы','ru','Читает современную украинскую литературу','interests,reading',1,'ok','2026-07-27 02:16:07','2026-07-26 13:27:07'),(59,2,1,'elena','Елена',NULL,'характер','ru','Спокойная, но любит посмеяться','character,calm',1,'ok','2026-07-27 02:16:07','2026-07-26 13:27:07'),(60,2,7,'renata_1430354','Renata',NULL,'personal','en','Renata is 43 years old.','age',1,'ok','2026-08-18 09:15:10','2026-08-18 08:27:00'),(61,2,7,'renata_1430354','Renata',NULL,'personal','en','She lives in Kharkiv, Ukraine.','location,residence',1,'ok','2026-08-18 09:15:11','2026-08-18 08:27:00'),(62,2,7,'renata_1430354','Renata',NULL,'personality','en','Renata describes herself as kind, feminine, and sincere.','personality,traits',1,'ok','2026-08-18 09:15:11','2026-08-18 08:27:00'),(63,2,7,'renata_1430354','Renata',NULL,'values','en','She believes true happiness comes from harmony, trust, and meaningful relationships.','philosophy,happiness',1,'ok','2026-08-18 09:15:14','2026-08-18 08:27:00'),(64,2,7,'renata_1430354','Renata',NULL,'values','en','Honesty, loyalty and mutual respect are core values for Renata.','values,ethics',1,'ok','2026-08-18 09:15:15','2026-08-18 08:27:00'),(65,2,7,'renata_1430354','Renata',NULL,'personality','en','She tries to bring warmth and positivity into the lives of people she cares about.','personality,positivity',1,'ok','2026-08-18 09:16:10','2026-08-18 08:27:00'),(66,2,7,'renata_1430354','Renata',NULL,'personality','en','Renata has a calm personality and an optimistic outlook on life.','personality,optimism',1,'ok','2026-08-18 09:16:12','2026-08-18 08:27:00'),(67,2,7,'renata_1430354','Renata',NULL,'relationships','en','She believes that ordinary moments become unforgettable when shared with someone special.','relationships,philosophy',1,'ok','2026-08-18 09:16:13','2026-08-18 08:27:00'),(68,2,7,'renata_1430354','Renata',NULL,'family','en','Renata grew up in a close‑knit family in Kharkiv and maintains strong ties with her parents.','family,upbringing',1,'ok','2026-08-18 09:16:14','2026-08-18 08:27:00'),(69,2,7,'renata_1430354','Renata',NULL,'education','en','She completed her secondary education at a local high school with good grades.','education,school',1,'ok','2026-08-18 09:16:15','2026-08-18 08:27:00'),(70,2,7,'renata_1430354','Renata',NULL,'education','en','Renata earned a bachelor\'s degree in psychology from Kharkiv National University.','education,degree,psychology',1,'ok','2026-08-18 20:15:10','2026-08-18 08:27:00'),(71,2,7,'renata_1430354','Renata',NULL,'career','en','She works as a counselor helping individuals improve emotional wellbeing.','career,counseling',1,'ok','2026-08-18 20:15:11','2026-08-18 08:27:00'),(72,2,7,'renata_1430354','Renata',NULL,'career','en','Renata has been employed in the counseling field for over 15 years.','career,experience',1,'ok','2026-08-18 20:15:16','2026-08-18 08:27:00'),(73,2,7,'renata_1430354','Renata',NULL,'hobbies','en','In her free time she enjoys reading contemporary fiction.','hobbies,reading',1,'ok','2026-08-18 20:15:17','2026-08-18 08:27:01'),(74,2,7,'renata_1430354','Renata',NULL,'hobbies','en','She practices yoga three times a week to maintain physical and mental balance.','hobbies,yoga,health',1,'ok','2026-08-18 20:15:19','2026-08-18 08:27:01'),(75,2,7,'renata_1430354','Renata',NULL,'hobbies','en','Renata loves cooking traditional Ukrainian dishes for friends and family.','hobbies,cooking,culture',1,'ok','2026-08-18 20:15:20','2026-08-18 08:27:01'),(76,2,7,'renata_1430354','Renata',NULL,'travel','en','She has visited Lviv, Odesa and Kyiv, appreciating Ukrainian regional diversity.','travel,ukraine',1,'ok','2026-08-18 20:15:21','2026-08-18 08:27:01'),(77,2,7,'renata_1430354','Renata',NULL,'travel','en','Renata’s most memorable trip abroad was a week‑long cultural tour of Poland.','travel,poland',1,'ok','2026-08-18 20:15:22','2026-08-18 08:27:01'),(78,2,7,'renata_1430354','Renata',NULL,'relationships','en','She is currently single but hopes to meet a partner who shares her values of trust and respect.','relationships,status',1,'ok','2026-08-18 20:15:23','2026-08-18 08:27:01'),(79,2,7,'renata_1430354','Renata',NULL,'adolescence','en','During her teenage years Renata participated in a school choir, developing a love for music.','adolescence,music,choir',1,'ok','2026-08-18 20:15:24','2026-08-18 08:27:01'),(80,2,7,'renata_1430354','Renata',NULL,'adolescence','en','She volunteered at a local community center, assisting younger children with homework.','adolescence,volunteering',1,'ok','2026-08-18 21:15:05','2026-08-18 08:27:01'),(81,2,7,'renata_1430354','Renata',NULL,'family','en','Renata has an older brother who works as an engineer in the same city.','family,sibling',1,'ok','2026-08-18 21:15:06','2026-08-18 08:27:01'),(82,2,7,'renata_1430354','Renata',NULL,'personal','en','She owns a small balcony garden where she grows herbs and seasonal flowers.','personal,gardening',1,'ok','2026-08-18 21:15:07','2026-08-18 08:27:01'),(83,2,7,'renata_1430354','Renata',NULL,'values','en','Renata believes that mutual respect is essential for any lasting relationship.','values,respect',1,'ok','2026-08-18 21:15:08','2026-08-18 08:27:01'),(84,2,7,'renata_1430354','Renata',NULL,'career','en','She offers free workshops on stress management for local NGOs.','career,workshops,ngos',1,'ok','2026-08-18 21:15:09','2026-08-18 08:27:01'),(85,2,7,'renata_1430354','Renata',NULL,'personality','en','Her open heart makes it easy for friends to confide in her.','personality,trust',1,'ok','2026-08-18 21:15:10','2026-08-18 08:27:01'),(86,2,7,'renata_1430354','Renata',NULL,'hobbies','en','Renata enjoys walking in Kharkiv’s Shevchenko Park to clear her mind.','hobbies,walking,park',1,'ok','2026-08-18 21:15:14','2026-08-18 08:27:01'),(87,2,7,'renata_1430354','Renata',NULL,'personal','en','She prefers a simple lifestyle focused on personal growth rather than material wealth.','personal,lifestyle',1,'ok','2026-08-18 21:15:15','2026-08-18 08:27:01'),(88,2,7,'renata_1430354','Renata',NULL,'future plans','en','Renata hopes to write a short memoir about the power of everyday happiness.','future,writing,memoir',1,'ok','2026-08-18 21:15:16','2026-08-18 08:27:01'),(89,2,7,'renata_1430354','Renata',NULL,'personal','uk','У мене є кішка, яка любить спати на підвіконні.','pets,cat,personal',1,'ok','2026-08-18 21:15:17','2026-08-18 10:24:16'),(90,2,7,'renata_1430354','Renata',NULL,'Personal Preference','en','I usually unwind by binge-watching modern detective series after a long day at work.','hobbies,relaxation,series',1,'ok','2026-08-18 22:15:04','2026-08-18 19:40:12'),(91,2,7,'renata_1430354','Renata',NULL,'Career','en','My job allows me to be creative, which keeps me inspired for writing my memoir.','work,creativity,memior',1,'ok','2026-08-18 22:15:05','2026-08-18 19:40:12'),(92,2,7,'diana_9021','Diana',NULL,'Biography','en','Her name is Diana.','name,identity',1,'ok','2026-09-02 19:15:08','2026-09-02 18:51:28'),(93,2,7,'diana_9021','Diana',NULL,'Biography','en','She is 36 years old.','age,demographics',1,'ok','2026-09-02 19:15:09','2026-09-02 18:51:28'),(94,2,7,'diana_9021','Diana',NULL,'Biography','en','She lives in Kyiv.','location,city',1,'ok','2026-09-02 19:15:13','2026-09-02 18:51:28'),(95,2,7,'diana_9021','Diana',NULL,'Career','en','Her profession is a choreographer.','career',1,'ok','2026-09-02 19:15:15','2026-09-02 18:51:28'),(96,2,7,'diana_9021','Diana',NULL,'Appearance','en','She has red hair.','hair,appearance',1,'ok','2026-09-02 19:15:16','2026-09-02 18:51:28'),(97,2,7,'diana_9021','Diana',NULL,'Personality','en','She describes herself as sunny and warm.','personality,character',1,'ok','2026-09-02 19:15:17','2026-09-02 18:51:28'),(98,2,7,'diana_9021','Diana',NULL,'Personality','en','She loves laughter and jokes.','humor,interests',1,'ok','2026-09-02 19:15:18','2026-09-02 18:51:28'),(99,2,7,'diana_9021','Diana',NULL,'Personality','en','She gives joy to others.','social,traits',1,'ok','2026-09-02 19:15:19','2026-09-02 18:51:28'),(100,2,7,'diana_9021','Diana',NULL,'Metaphor','en','She compares herself to a sunny bunny.','self_image,metaphor',1,'ok','2026-09-02 19:15:20','2026-09-02 18:51:28'),(101,2,7,'diana_9021','Diana',NULL,'Career','en','Her work requires constant professional improvement.','career,growth',1,'ok','2026-09-02 19:15:21','2026-09-02 18:51:28'),(102,2,7,'diana_9021','Diana',NULL,'Lifestyle','en','A healthy lifestyle is a priority for her.','health,lifestyle',1,'ok','2026-09-02 20:15:06','2026-09-02 18:51:28'),(103,2,7,'diana_9021','Diana',NULL,'Diet','en','She does not deny herself the pleasure of eating delicious food.','food,lifestyle',1,'ok','2026-09-02 20:15:07','2026-09-02 18:51:28'),(104,2,7,'diana_9021','Diana',NULL,'Childhood','en','As a teenager, she likely discovered her passion for movement and dance.','childhood,interests',1,'ok','2026-09-02 20:15:08','2026-09-02 18:51:28'),(105,2,7,'diana_9021','Diana',NULL,'Education','en','She studied at a performing arts academy to become a professional choreographer.','education,career',1,'ok','2026-09-02 20:15:08','2026-09-02 18:51:28'),(106,2,7,'diana_9021','Diana',NULL,'Family','en','She has a close and supportive relationship with her parents.','family,relationships',1,'ok','2026-09-02 20:15:09','2026-09-02 18:51:28'),(107,2,7,'diana_9021','Diana',NULL,'Hobbies','en','She enjoys improvisational theater because she loves humor.','hobbies,comedies',1,'ok','2026-09-02 20:15:10','2026-09-02 18:51:28'),(108,2,7,'diana_9021','Diana',NULL,'Hobbies','en','She practices yoga to maintain flexibility and balance.','hobbies,health',1,'ok','2026-09-02 20:15:11','2026-09-02 18:51:28'),(109,2,7,'diana_9021','Diana',NULL,'Relationships','en','She values honesty and kindness in her romantic relationships.','love,values',1,'ok','2026-09-02 20:15:11','2026-09-02 18:51:28'),(110,2,7,'diana_9021','Diana',NULL,'Travel','en','She loves traveling to explore new cultures and dance styles.','travel,career',1,'ok','2026-09-02 20:15:12','2026-09-02 18:51:28'),(111,2,7,'diana_9021','Diana',NULL,'Travel','en','She has visited several European countries for dance workshops.','travel,work',1,'ok','2026-09-02 20:15:13','2026-09-02 18:51:28'),(112,2,7,'diana_9021','Diana',NULL,'Work','en','She creates contemporary dance routines for local theater productions.','work,creative',1,'ok','2026-09-02 21:15:07','2026-09-02 18:51:28'),(113,2,7,'diana_9021','Diana',NULL,'Work','en','She conducts masterclasses for young dancers in Kyiv.','work,teaching',1,'unverifiable','2026-09-02 21:15:09','2026-09-02 18:51:28'),(114,2,7,'diana_9021','Diana',NULL,'Lifestyle','en','She engages in regular cardio exercises to stay fit.','health,exercise',1,'ok','2026-09-02 21:15:10','2026-09-02 18:51:28'),(115,2,7,'dating_girl_universal','Девушка',NULL,'dating_girl','en','I love cooking, especially simple meals on busy weekdays. My go-to is a quick pasta with fresh herbs.','cooking,food,habits',1,'ok','2026-09-21 14:15:10','2026-09-21 13:59:58'),(116,2,7,'dating_girl_universal','Девушка',NULL,'dating_girl','en','I am a good cook but prefer homemade food over fancy restaurant dinners. I enjoy trying new recipes at home.','cooking,food,lifestyle',1,'ok','2026-09-21 14:15:13','2026-09-21 13:59:58');

SET FOREIGN_KEY_CHECKS = 1;

-- ── Владелец: прод-номер на наш ─────────────────────────────────────────────
--
-- ⚠ По имени учётки, а не по номеру: номера у баз разошлись и разойдутся снова.
UPDATE `fact` f
  JOIN `user` u ON u.`username` = 'dating_service'
   SET f.`user_id` = u.`id`
 WHERE f.`user_id` <> u.`id`
   AND f.`document_id` <> 'masha' AND f.`document_id` <> 'elena';

-- ── Ключи к новому образцу ──────────────────────────────────────────────────
--
-- ⚠ Порядок: сперва переводим переводимое, потом удаляем остальное. Наоборот —
-- и пришлось бы помнить, что уже удалено, а что ещё нет.
UPDATE `fact` SET `document_id` = '1430354_Renata'
 WHERE `document_id` = 'renata_1430354';

UPDATE `fact` SET `document_id` = '9021_Diana'
 WHERE `document_id` = 'diana_9021';

-- ⚠⚠ Удаляем **по именам ключей**, а не «всё, что не похоже на образец»: список
-- короткий и проверен, а правило по виду завтра снесло бы что-нибудь новое.
DELETE FROM `fact`
 WHERE `document_id` IN ('masha', 'elena', 'dating_girl_universal');

-- ── Записи девушек в справочнике ────────────────────────────────────────────
--
-- ⚠ Девушки живут в том же справочнике (`…_wf_talk_girl_key`), и записи им нужны
-- заранее: иначе workflow заведёт их сам при первом заходе — но с другим
-- номером, а факты уже лежат под этим ключом.
INSERT INTO `companion` (`unique_id`, `title`)
SELECT one.`key`, one.`title` FROM (
        SELECT '1430354_Renata' AS `key`, 'Renata' AS `title`
  UNION SELECT '9021_Diana', 'Diana') AS one
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `companion`) x
                    WHERE x.`unique_id` = one.`key`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `fact`) AS фактов,
       (SELECT COUNT(*) FROM `companion`) AS собеседников,
       (SELECT GROUP_CONCAT(DISTINCT `document_id` ORDER BY `document_id`
                            SEPARATOR ', ') FROM `fact`) AS ключи,
       -- ⚠ Образец: номер, подчёркивание, имя. Останься старый ключ — новый поиск
       -- его не найдёт, и агент молча «не вспомнит» ничего.
       (SELECT COUNT(*) FROM `fact`
         WHERE `document_id` NOT REGEXP '^[0-9]+_.') AS ключей_не_по_образцу,
       -- ⚠⚠ Главная проверка целости: проверки были погашены, и убедиться, что
       -- ни один факт не ведёт в пустоту, надо **явно**. База задним числом этого
       -- не сделает.
       (SELECT COUNT(*) FROM `fact` f
         WHERE NOT EXISTS (SELECT 1 FROM `user` u WHERE u.`id` = f.`user_id`)
            OR NOT EXISTS (SELECT 1 FROM `fact_collection` c
                            WHERE c.`id` = f.`collection_id`)) AS фактов_в_пустоту,
       -- ⚠ И обратная: сессии не должны ссылаться на снесённых собеседников.
       (SELECT COUNT(*) FROM `agent_session` s
         WHERE s.`companion_id` IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM `companion` c
                            WHERE c.`id` = s.`companion_id`)) AS сессий_в_пустоту;
