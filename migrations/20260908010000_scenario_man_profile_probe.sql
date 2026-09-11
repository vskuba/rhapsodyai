-- Разведка: что видно на странице анкеты мужчины (2026-09-08)
--
-- ЗАЧЕМ. DatingAi собирается писать письма «про интересы собеседника», а интересы
-- берутся из его анкеты на сайте. Анкеты этой мы никогда не открывали: списки
-- (сценарий 259) дают имя, фото и ссылку, и только.
--
-- ⚠ СЦЕНАРИЙ РАЗВЕДОЧНЫЙ, и он временный. Селекторов страницы никто не знает, а
-- гадать их по памяти — способ потратить пять прогонов вместо одного. Поэтому
-- снимаем текст крупными кусками, смотрим, что пришло, и уже по этому пишем
-- настоящий сценарий с точными полями.
--
-- Вход взят у сценария 522 («чат: отправить сообщение»): он `active`, и его форма
-- входа проверена живыми прогонами. Повторяем шаг в шаг, чтобы разведка не
-- спотыкалась о вход.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT COUNT(*) FROM `browser_scenario`
         WHERE `name` = 'разведка: анкета мужчины') AS уже_есть;

INSERT INTO `browser_scenario` (`site_id`, `name`, `goal`, `start_url`, `steps`,
                                `variables`, `status`)
SELECT @site, 'разведка: анкета мужчины',
       'открыть анкету мужчины по ссылке из списка и снять текст страницы целиком '
       '— чтобы увидеть, какие на ней разделы',
       'https://ladadate.com/',
       CAST('[
         {"action": "goto", "url": "{{login_url}}/signin", "selector": "", "value": "",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
         {"action": "wait_for", "url": "", "selector": "form[action*=\\"signin\\"] input[name=\\"login\\"]",
          "value": "", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 45000},
         {"action": "fill", "url": "", "selector": "form[action*=\\"signin\\"] input[name=\\"login\\"]",
          "value": "{{profile_login}}", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 10000},
         {"action": "fill", "url": "", "selector": "form[action*=\\"signin\\"] input[name=\\"password\\"]",
          "value": "{{girl_password}}", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 10000},
         {"action": "click", "url": "", "selector": "form[action*=\\"signin\\"] button[type=\\"submit\\"]",
          "value": "", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 45000},
         {"action": "wait_for", "url": "", "selector": "a[href*=\\"/chat\\"]",
          "value": "", "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 60000},
         {"action": "goto", "url": "{{profile_url}}", "selector": "", "value": "",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "6000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": "body", "value": "",
          "name": "страница", "key": "", "fields": [], "optional": false, "timeout_ms": 30000},
         {"action": "extract", "url": "", "selector": "h1", "value": "",
          "name": "заголовок", "key": "", "fields": [], "optional": true, "timeout_ms": 15000},
         {"action": "extract", "url": "", "selector": ".profile-info", "value": "",
          "name": "блок_профиля", "key": "", "fields": [], "optional": true, "timeout_ms": 15000},
         {"action": "extract", "url": "", "selector": "main", "value": "",
          "name": "основное", "key": "", "fields": [], "optional": true, "timeout_ms": 15000}
       ]' AS JSON),
       CAST('{}' AS JSON), 'active'
 WHERE NOT EXISTS (SELECT 1 FROM `browser_scenario`
                    WHERE `name` = 'разведка: анкета мужчины');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `browser_scenario`
         WHERE `name` = 'разведка: анкета мужчины') AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'разведка: анкета мужчины') AS шагов;
