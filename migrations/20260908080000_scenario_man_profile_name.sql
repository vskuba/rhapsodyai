-- «анкета мужчины: карточка» снимает имя и фото (2026-09-08)
--
-- ЧТО БЫЛО. Сценарий снимал только текст анкеты, а имя и фотографию — нет. В
-- DatingAi карточка при этом заводится **под сбор описания**, и у собеседника,
-- которого не видели в лентах, она получалась безымянной: номер, город, описание —
-- и пустое место вместо имени и лица. В списке такие читаются как мусор, и человек
-- справедливо спросил, не тестовые ли это записи.
--
-- ⚠ ПОЛАГАТЬСЯ НА ЛЕНТУ БЫЛО НЕЛЬЗЯ. Имя и фото приходят из списков онлайна, но
-- анкету мы открываем и у тех, кого в лентах не было: адресата берут из пула, а
-- пул живёт дольше снимка ленты.
--
-- ЧТО ВМЕСТО. Два шага:
--
--   `шапка` — `.top__profle-wr`. Там имя с возрастом и кнопки: «Kevin , 58 SEND
--             MESSAGE START LIVE CHAT…». Разбирает это DatingAi — берёт всё до
--             первой кнопки.
--   `фото_главное` — `img.ratio-1x15-img`. ⚠ Именно оно: галерея (`.owl-lazy`)
--             отдаёт миниатюры с суффиксом `-s`, а это полноразмерное.
--
-- ⚠ Пробные шаги разведки (`проба_имя_1`, `проба_имя_2`, `проба_фото`) убраны:
-- сценарий переписывается целиком, и они в новый список не входят. `.name_row`
-- среди них не годился вовсе — отдавал подписи полей, а не имя.

SET @id = (SELECT `id` FROM `browser_scenario` WHERE `name` = 'анкета мужчины: карточка');

SELECT 'ДО' AS этап, @id AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов;

UPDATE `browser_scenario`
   SET `steps` = CAST('[
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
         {"action": "goto", "url": "{{login_url}}/profile/{{companion_uid}}", "selector": "",
          "value": "", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
         {"action": "wait_for", "url": "", "selector": ".user__profile-info", "value": "",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 45000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "2500",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "click", "url": "", "selector": "a:has-text(\\"More\\")", "value": "",
          "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 10000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "1500",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": ".user__profile-info", "value": "",
          "name": "анкета", "key": "", "fields": [], "optional": false, "timeout_ms": 30000},
         {"action": "extract", "url": "", "selector": ".top__profle-wr", "value": "",
          "name": "шапка", "key": "", "fields": [], "optional": true, "timeout_ms": 15000},
         {"action": "extract_rows", "url": "", "selector": "img.ratio-1x15-img",
          "value": "", "name": "фото_главное", "key": "",
          "fields": [{"name": "src", "selector": ":scope", "attribute": "src", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 15000}
       ]' AS JSON)
 WHERE `id` = @id;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов;
