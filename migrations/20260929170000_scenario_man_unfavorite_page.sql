-- Сценарий «анкета мужчины: из избранных»: переписка на страницу сайта
-- «/favorites» (2026-09-29)
--
-- ЗАЧЕМ ПЕРЕПИСЫВАЕМ. Прогон по анкетe (миграция 20260929120000) на проду звёздку
-- не гасил НИКОГДА, и диагностика на живом браузере вскрыла причину в самом сайте:
-- обработчик звезды в `user.min.js` берёт номер человека из строки списка
-- (`closest(".people__item").attr("id")`), а на страницах анкеты такой строки нет,
-- `attr("id")` отдаёт `undefined`, и обработчик падает на `n.split("-")` — без
-- запроса, без видимого отказа. Снятие избранного с анкеты сайтом просто не
-- работает, жми хоть сто раз.
--
-- ЧТО ДЕЛАЕМ ТЕПЕРЬ. Идём туда, где сайта хватает сам: на свою страницу
-- избранных `/favorites`. Человек там стоит строкой `id="userid-<номер>"`,
-- состояние звезды то же (класс `favorite__status-ok`), и по нажатию на горящую
-- звёздочку сам сайт открывает своё окно подтверждения `#removecontact_popup`,
-- где кнопка `.button-remove-ok` шлёт `POST /contact-remove` и снимает строку со
-- страницы. То есть мы не изобретаем ручку, которой нет, — жмём те же кнопки,
-- которые жмёт человек.
--
-- ШАГИ, КОТОРЫЕ ОТЛИЧАЮТСЯ ОТ ПРЕЖНЕГО ПРОГОНА:
--   goto /favorites вместо анкеты; ждать строку `#userid-<номер>`;
--   к нажатию горящей звезды добавлен клик подтверждения в модалке сайта.
--
-- ⚠ Селектор нажатия остался направленно-безопасным: жмём
-- `#userid-<номер> .favorite__status.favorite__status-ok`, только горящую звезду
-- СТРОКИ ЭТОГО ЧЕЛОВЕКА. Погасшей звезды (значит, его и так нет) касаться нельзя:
-- кнопка одна на оба направления, и нажатие по погасшей зажгла бы избранное
-- обратно. Чужие строки селектор не назовёт вовсе — номер подставлен в id.
--
-- ⚠ Клик подтверждения — `optional`, и таймаум его короткий (15 с): если окно не
-- открылось (звезду не нашли — шаг нажатия пропустили), прогон не виснет, а
-- честно доходит до снятия состояния, где вызывающий увидит отказ.
--
-- ⚠ «После» теперь пустое на УДАЧУ: сайт снимает строку вместе со звездой
-- (`pathname === "/favorites"` — и `remove()`). Вызывающий (`favorite.py`,
-- `favorite_state`) знает: пустое «после» при горящем «до» — это «строку сняли»,
-- а не «звезду не показали». Контракт записан там же, в докстринге.
--
-- ИМЯ И `start_url` не меняются: вызывающий ищет сценарий по имени.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS шагов,
       (SELECT CAST(`steps` AS CHAR) LIKE '%/profile/%'
          FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS шёл_на_анкету
  FROM `browser_scenario`
 WHERE `name` = 'анкета мужчины: из избранных';

UPDATE `browser_scenario`
   SET `goal` = 'войти девушкой, открыть свою страницу избранных сайта, найти
                 строку мужчины по его номеру и снять избранность: нажать на
                 строке горящую звёздочку и подтвердить снятие в окне самого
                 сайта. Погасшую звезду и чужие строки не трогать: кнопка одна
                 на оба направления, и нажатие по погасшей зажгла бы обратно',
       `steps` = CAST('[
          {"action": "goto", "url": "{{login_url}}", "selector": "", "value": "",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
          {"action": "wait_ms", "url": "", "selector": "", "value": "3000",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
          {"action": "click", "url": "", "selector": "button.panel-cookie__button", "value": "",
           "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 45000},
          {"action": "click", "url": "", "selector": "button.header-auth__btn", "value": "",
           "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 45000},
          {"action": "wait_ms", "url": "", "selector": "", "value": "2000",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
          {"action": "fill", "url": "", "selector": "form:has(button.btn--blue) input[name=login]",
           "value": "{{profile_login}}", "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 10000},
          {"action": "fill", "url": "", "selector": "form:has(button.btn--blue) input[name=password]",
           "value": "{{girl_password}}", "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 10000},
          {"action": "click", "url": "", "selector": "form:has(button.btn--blue) button.btn--blue",
           "value": "", "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 45000},
          {"action": "wait_ms", "url": "", "selector": "", "value": "12000",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
          {"action": "goto", "url": "{{login_url}}/favorites", "selector": "",
           "value": "", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
          {"action": "wait_for", "url": "", "selector": ".people__item", "value": "",
           "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 45000},
          {"action": "wait_for", "url": "", "selector": "#userid-{{companion_uid}}", "value": "",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 45000},
          {"action": "wait_ms", "url": "", "selector": "", "value": "3000",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
          {"action": "extract", "url": "", "selector": "#userid-{{companion_uid}} .favorite__status",
           "value": "@class", "name": "до", "key": "", "fields": [], "optional": true, "timeout_ms": 20000},
          {"action": "click", "url": "", "selector": "#userid-{{companion_uid}} .favorite__status.favorite__status-ok",
           "value": "", "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 30000},
          {"action": "click", "url": "", "selector": "#removecontact_popup .button-remove-ok",
           "value": "", "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 15000},
          {"action": "wait_ms", "url": "", "selector": "", "value": "6000",
           "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
          {"action": "extract", "url": "", "selector": "#userid-{{companion_uid}} .favorite__status",
           "value": "@class", "name": "после", "key": "", "fields": [], "optional": true, "timeout_ms": 20000}
        ]' AS JSON)
 WHERE `name` = 'анкета мужчины: из избранных';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS шагов,
       (SELECT CAST(`steps` AS CHAR) LIKE '%{{login_url}}/favorites%'
          FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS идёт_на_страницу,
       (SELECT CAST(`steps` AS CHAR) LIKE '%button-remove-ok%'
          FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS подтверждает_в_окне,
       (SELECT CAST(`steps` AS CHAR) LIKE '%#userid-{{companion_uid}} .favorite__status.favorite__status-ok%'
          FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS жмёт_горящую_его_строки;
