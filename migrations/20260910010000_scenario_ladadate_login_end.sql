-- «вход под анкетой»: конец сценария без проверки DOM (2026-09-10)
--
-- ЧТО ПОКАЗАЛ ПЕРВЫЙ ЖЕ ПРОГОН. Вход прошёл: сценарий добрался до `/chat` и нашёл
-- там `#user-message` — поле, которого гостю не отдают вовсе. Но упал:
--
--     waiting for locator("#user-message").first to be visible
--     16 × locator resolved to hidden <textarea id="user-message" …>
--
-- Поле есть, но скрыто: сайт показывает его, когда выбран собеседник. Ждать его
-- видимым — значит требовать от входа ещё и открытого диалога.
--
-- ⚠ ПОЧЕМУ НЕ МЕНЯЕМ СЕЛЕКТОР, А УБИРАЕМ ШАГ. Любой видимый элемент `/chat`
-- зависит от того, есть ли у девушки переписка: список диалогов у новой анкеты
-- пуст, и проверка снова начнёт врать — теперь в другую сторону. Искать элемент,
-- видимый всегда и у всех, значит гадать по чужой вёрстке.
--
-- Проверять вход сценарием и не нужно: **это делает панель**, и делает лучше.
-- После сценария она сама заходит на страницу для вошедших с снятыми cookie и
-- смотрит ответ (DatingAi, `dating_login._verify` + настройка `heartbeat`): `200`
-- — сессия настоящая, `302` на `/signin` — нет. Один механизм на проверку входа
-- и на поддержание присутствия, а не два, которые однажды разойдутся.
--
-- Заход на `/chat` оставляем: он не проверка, а место, где сессия оседает —
-- страница отдаётся только вошедшему, и сайт видит её как обычную работу.

SET @id = (SELECT `id` FROM `browser_scenario` WHERE `name` = 'вход под анкетой');

SELECT 'ДО' AS этап, @id AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов,
       (SELECT CAST(`steps` AS CHAR) LIKE '%user-message%' FROM `browser_scenario`
         WHERE `id` = @id) AS ждёт_поле;

-- Последний шаг заменяем на паузу: странице дают догрузиться, и на этом всё.
UPDATE `browser_scenario`
   SET `steps` = JSON_SET(`steps`, '$[10]',
                          JSON_OBJECT('action', 'wait_ms', 'url', '', 'selector', '',
                                      'value', '4000', 'timeout_ms', 8000,
                                      'optional', FALSE))
 WHERE `id` = @id
   AND JSON_LENGTH(`steps`) = 11;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов,
       (SELECT CAST(`steps` AS CHAR) LIKE '%user-message%' FROM `browser_scenario`
         WHERE `id` = @id) AS ждёт_поле,
       (SELECT CAST(`steps` AS CHAR) LIKE '%{{login}}%' FROM `browser_scenario`
         WHERE `id` = @id) AS есть_логин;
