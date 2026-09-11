-- Разведка анкеты мужчины: вход берём тот, что работает (2026-09-08)
--
-- ЧТО БЫЛО. Вход через `/signin` сайт отклонил: «E-mail or password invalid», хотя
-- пароль у анкеты есть. А страница мужчины без входа отдала 404 — гостю её не
-- показывают вовсе.
--
-- ⚠ ПРИЧИНА — ФОРМ ВХОДА ДВЕ. Образец брался у сценария 522 («чат: отправить
-- сообщение»), а он ходит формой `/signin`. Женский кабинет открывается другой —
-- модалкой на главной (`button.header-auth__btn` → `form:has(button.btn--blue)`), и
-- именно ею входит сценарий 259 («анкеты мужчин: список»), который живой и снимает
-- списки каждый день.
--
-- ЧТО ВМЕСТО. Шаги входа скопированы у 259 — включая согласие на cookie и паузы:
-- они там не для красоты, сайт медленный.

SET @id = (SELECT `id` FROM `browser_scenario` WHERE `name` = 'разведка: анкета мужчины');

SELECT 'ДО' AS этап, @id AS сценарий;

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
         {"action": "wait_ms", "url": "", "selector": "", "value": "15000",
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
