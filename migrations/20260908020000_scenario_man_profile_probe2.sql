-- Разведка анкеты мужчины: снимаем и то, что видно после входа (2026-09-08)
--
-- ЧТО БЫЛО. Первый прогон встал на шаге 6: `wait_for a[href*="/chat"]` не дождался
-- ссылки на чат за минуту. Что именно случилось — из этого не видно: вход мог не
-- пройти вовсе, а мог пройти и привести на страницу, где ссылка называется иначе.
--
-- ЧТО ВМЕСТО. Ожидание убрано, а вместо него снимок: адрес и текст страницы сразу
-- после входа. Разведка на то и разведка — сначала посмотреть, потом писать
-- селекторы.
--
-- ⚠ Шаг `extract` с `body` даёт весь текст страницы. Для рабочего сценария так
-- нельзя (мусор и лишний вес), но здесь это ровно то, что нужно: увидеть, куда нас
-- привели.

SET @id = (SELECT `id` FROM `browser_scenario` WHERE `name` = 'разведка: анкета мужчины');

SELECT 'ДО' AS этап, @id AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов;

UPDATE `browser_scenario`
   SET `steps` = CAST('[
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
         {"action": "wait_ms", "url": "", "selector": "", "value": "9000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": "body", "value": "",
          "name": "после_входа", "key": "", "fields": [], "optional": false, "timeout_ms": 30000},
         {"action": "goto", "url": "{{profile_url}}", "selector": "", "value": "",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "8000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": "body", "value": "",
          "name": "страница_анкеты", "key": "", "fields": [], "optional": false, "timeout_ms": 30000}
       ]' AS JSON)
 WHERE `id` = @id;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов;
