-- Задвоенные реплики убираются: 23 обмена, которых не было (2026-10-02)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- В ленте разговора одна и та же наша реплика стояла дважды. Поймано человеком
-- на паре Solomia ↔ Finland: «haha ok! but i prefer my own bed 😅» в 08:06 и
-- в 08:19, обе с отметкой «доставлено».
--
-- Собеседник получил **одно** сообщение. У соседа оно записано один раз
-- (`panel:59180693`), и второй отправки не было — её остановил запрет повтора
-- (`send._said_already`, «это сообщение уже отправлено последним»).
--
-- ## Откуда дубли: три разные причины
--
-- **1. Повторный прогон агента.** `is_answered` у входящего не проставился
-- (привезённое из панели ложится задним числом), автоответчик взял тот же повод
-- снова, агент сочинил тот же ответ. Обмен пишется **внутри прогона**, до
-- отправки, — поэтому строка легла, хотя реплика не ушла.
--
-- ⚠ Причина уже закрыта правкой соседа: `_waiting_tail` берёт границу хвоста по
-- нашей последней реплике, а не по `is_answered`.
--
-- **2. Близнецы переноса — и это ошибка миграции `…_chat_from_panel`.** У соседа
-- наше исходящее лежит в `message` дважды: своей строкой от отправки (ULID) и
-- отражением из журнала панели (`panel:…`). Отсев близнецов описан у него же
-- (`message_twin.py`) и был применён в локальной миграции переноса — а в
-- боевой я его **не применил**. Отсюда 14 пар, все с разницей 0–7 секунд.
--
-- **3. Перенос задвоил уже наше.** Дедупликация сверяла обе половины сразу, а у
-- перенесённой строки вопрос **склеен** из нескольких реплик и с нашим не
-- совпадал — строка проходила как новая. Четыре пары.
--
-- ## ⚠⚠⚠ Что считается дублем, а что законным повтором
--
-- Решает **источник истины**: сколько раз текст реально ушёл собеседнику. Счёт
-- строк у соседа на этот вопрос не отвечает — там свои близнецы, поэтому перед
-- счётом применяется их же правило отсева (панельная строка рядом с
-- не-панельной в пределах 60 секунд — отражение, а не отправка).
--
-- Строк оставляем столько, сколько ушло. Законные повторы не тронуты:
--
--     1439074_renata   «hello! how are you today?»        ушло 3 раза — 3 строки
--     181685_semen     «semen, what do you do for fun…»   ушло 4 раза — 4 строки
--
-- ## Какая строка из пары остаётся
--
-- Та, что несёт больше: сперва с непустым вопросом, затем с более длинным
-- вопросом (склеенный хвост полнее одной реплики), затем с `source_uid`
-- (прослеживаемость до источника), затем младшая по номеру.
--
-- ## ⚠⚠ Защита от чужой базы
--
-- Номера строк сняты с **прода**, а на другой базе те же номера значат другое.
-- Поэтому каждое удаление проверяет ещё три вещи: канал, ключи обеих сторон и
-- первые 40 знаков ответа. Не сошлось — строка не трогается, и файл проходит
-- молча. Локально он снесёт ноль строк, и это верный исход.
--
-- Идемпотентность: второй прогон не находит удалённого.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов,
       (SELECT COUNT(*) FROM `companion_session` a
         WHERE EXISTS (SELECT 1 FROM (SELECT * FROM `companion_session`) b
                        WHERE b.`owner_id` = a.`owner_id`
                          AND b.`companion_id` = a.`companion_id`
                          AND b.`kind` = a.`kind` AND b.`answer` = a.`answer`
                          AND b.`id` <> a.`id` AND a.`answer` <> '')) AS в_парах;

DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 103 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '501093_mike'
   AND LEFT(s.`answer`, 40) = 'coffee was perfect, but i''m already on c';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 104 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '501093_mike'
   AND LEFT(s.`answer`, 40) = 'not yet! dreaming of windy lakes though.';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 144 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '300288_mohamad'
   AND LEFT(s.`answer`, 40) = 'Hey! Just had dinner with a friend. How''';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 153 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '300288_mohamad'
   AND LEFT(s.`answer`, 40) = 'Hey! I''m okay, just chilling at home. Wh';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 268 AND s.`kind` = 'chat'
   AND o.`unique_id` = '999029_olga' AND c.`unique_id` = '283331_dwight_carter'
   AND LEFT(s.`answer`, 40) = 'haha too spicy for coffee time 😅 let’s k';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 279 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '930315_bruce'
   AND LEFT(s.`answer`, 40) = 'cool, what made you decide that?';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 332 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '511328_gerry'
   AND LEFT(s.`answer`, 40) = 'haha ok bossy then? what’s your type, an';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 346 AND s.`kind` = 'chat'
   AND o.`unique_id` = '643694_diana' AND c.`unique_id` = '329110_brian_ritter'
   AND LEFT(s.`answer`, 40) = 'ha, so you want the strong man story? ma';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 362 AND s.`kind` = 'chat'
   AND o.`unique_id` = '924237_solomia' AND c.`unique_id` = '443309_finland'
   AND LEFT(s.`answer`, 40) = 'haha ok! but i prefer my own bed 😅';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 399 AND s.`kind` = 'chat'
   AND o.`unique_id` = '124968_victoria' AND c.`unique_id` = '421674_christopher'
   AND LEFT(s.`answer`, 40) = 'Your profile suggests a quiet intensity ';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 427 AND s.`kind` = 'chat'
   AND o.`unique_id` = '413636_oksana' AND c.`unique_id` = '102921_simon'
   AND LEFT(s.`answer`, 40) = 'Your silence is louder than words, and I';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 445 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'awesome. i''ll go first. i cry every time';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 448 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'take your time. what''s one thing about y';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 450 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'passionate about cooking or just talking';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 452 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'impressive. do you channel that passion ';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 454 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'honey? cute. I’m just busy. do you cook ';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 456 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'flexible. do you prefer cooking somethin';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 458 AND s.`kind` = 'chat'
   AND o.`unique_id` = '418024_diana' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'sounds tempting, but i prefer my own kit';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 482 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'bold. but i''m busy with work, maybe catc';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 485 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'sleeping? lol. seriously though, i''m jus';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 488 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'oh wow, long distance then. i''m just chi';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 490 AND s.`kind` = 'chat'
   AND o.`unique_id` = '599939_elena' AND c.`unique_id` = '604366_henry'
   AND LEFT(s.`answer`, 40) = 'glitch lol. just moved here recently. yo';
DELETE s FROM `companion_session` s
  JOIN `companion` o ON o.`id` = s.`owner_id`
  JOIN `companion` c ON c.`id` = s.`companion_id`
 WHERE s.`id` = 498 AND s.`kind` = 'chat'
   AND o.`unique_id` = '643694_diana' AND c.`unique_id` = '181685_semen_gorbunkov'
   AND LEFT(s.`answer`, 40) = 'pretty chill honestly. just watching a s';
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `companion_session`) AS обменов,
       (SELECT COUNT(*) FROM `companion_session` a
         WHERE EXISTS (SELECT 1 FROM (SELECT * FROM `companion_session`) b
                        WHERE b.`owner_id` = a.`owner_id`
                          AND b.`companion_id` = a.`companion_id`
                          AND b.`kind` = a.`kind` AND b.`answer` = a.`answer`
                          AND b.`id` <> a.`id` AND a.`answer` <> '')) AS в_парах;
