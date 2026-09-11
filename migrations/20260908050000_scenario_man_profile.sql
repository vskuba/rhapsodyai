-- Сценарий «анкета мужчины: карточка» (2026-09-08)
--
-- ЗАЧЕМ. Письма рассылки спрашивают собеседника про его интересы, а интересы
-- берутся из его анкеты на сайте. Списки (сценарий 259) дают имя, фото и номер —
-- этого хватает, чтобы обратиться, но не хватает, чтобы спросить.
--
-- ЧТО ВЫЯСНИЛА РАЗВЕДКА (сценарий 613, четыре прогона):
--
--   1. Гостю анкета мужчины не показывается вовсе — 404. Нужен вход девушкой.
--   2. Вход женским кабинетом идёт **модалкой на главной**, а не формой
--      `/signin`: последняя отвечает «E-mail or password invalid».
--   3. Ссылка достаточна **одним номером**: `/profile/275296` открывается так же,
--      как `/profile/275296-men-from-germany`. Хвост со страной не нужен — и это
--      важно, потому что в списке через API сайта ссылки нет вовсе, есть только
--      номер.
--   4. Весь текст анкеты лежит в `.user__profile-info` — без меню и подвала:
--
--        Id: 275296 Location Stuttgart, Germany Occupation Marital Status Widowed
--        Children None Height 175 cm … Education University Smoke No Drink On
--        Occasions Level of English About Myself <текст> Partner (age 18 - 40)
--
-- ⚠ СНИМАЕМ ТЕКСТ ЦЕЛИКОМ, А НЕ ПОЛЯ ПО ОТДЕЛЬНОСТИ. Подписи («Occupation»,
-- «Marital Status») переживут перевёрстку, а классы вроде `col-sm-6 user_row` —
-- нет: их у сайта два на всю анкету, и поля в них слиты в кучу. Разбор живёт в
-- DatingAi (`dating_companion_about.py`), где его видно и есть чем проверить.
--
-- ⚠ ПАРОЛЬ ПЕРЕДАЁТ ВЫЗЫВАЮЩИЙ. У анкеты есть настройка, каким паролем ходить —
-- своим или общим агентским (`password_source`), — и решает её DatingAi
-- (`dating_password_pick`). Подставь сосед свою переменную сайта, анкета с личным
-- паролем ходила бы под чужим.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT COUNT(*) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: карточка') AS уже_есть;

INSERT INTO `browser_scenario` (`site_id`, `name`, `goal`, `start_url`, `steps`,
                                `variables`, `status`)
SELECT @site, 'анкета мужчины: карточка',
       'войти девушкой и снять анкету мужчины по его номеру: чем занимается, '
       'семейное положение, образование, текст «About Myself» — то, из чего письмо '
       'сочиняет вопрос про его интересы',
       'https://ladadate.com/',
       CAST('[
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
         {"action": "extract", "url": "", "selector": ".user__profile-info", "value": "",
          "name": "анкета", "key": "", "fields": [], "optional": false, "timeout_ms": 30000},
         {"action": "extract", "url": "", "selector": ".name_row", "value": "",
          "name": "имя", "key": "", "fields": [], "optional": true, "timeout_ms": 15000},
         {"action": "extract_rows", "url": "", "selector": ".top__profle img[src*=\\"photos\\"]",
          "value": "", "name": "фото", "key": "",
          "fields": [{"name": "src", "selector": ":scope", "attribute": "src", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 15000}
       ]' AS JSON),
       CAST('{}' AS JSON), 'active'
 WHERE NOT EXISTS (SELECT 1 FROM `browser_scenario`
                    WHERE `name` = 'анкета мужчины: карточка');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: карточка') AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: карточка') AS шагов;
