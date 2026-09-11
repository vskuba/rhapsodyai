-- «анкета мужчины: карточка»: раскрыть «More» и убрать неверный шаг (2026-09-08)
--
-- ЧТО ПОКАЗАЛ ПЕРВЫЙ ЖИВОЙ ПРОГОН (мужчина 352443):
--
--   1. Текст «About Myself» обрывается на слове **More** — сайт прячет хвост под
--      кнопкой. А это ровно то, ради чего анкету и открывают: «Looking for a girl
--      to enjoy my nice life… More».
--   2. Шаг «имя» по `.name_row` вернул **подписи полей**, а не имя: «Id: Location
--      Occupation Marital Status…». Селектор неверный.
--
-- ЧТО ВМЕСТО:
--
--   1. Перед снятием жмём «More» — `optional`, потому что у коротких анкет кнопки
--      нет вовсе, и её отсутствие не повод ронять прогон.
--   2. Шаг «имя» убран. Имя и возраст приходят из списка собеседников
--      (`dating_people`), и снимать их второй раз незачем — а неверный шаг хуже
--      отсутствующего: он молча кладёт мусор в карточку.

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
         {"action": "click", "url": "", "selector": "span:has-text(\\"More\\")", "value": "",
          "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 10000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "1500",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": ".user__profile-info", "value": "",
          "name": "анкета", "key": "", "fields": [], "optional": false, "timeout_ms": 30000},
         {"action": "extract_rows", "url": "", "selector": ".top__profle img[src*=\\"photos\\"]",
          "value": "", "name": "фото", "key": "",
          "fields": [{"name": "src", "selector": ":scope", "attribute": "src", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 15000}
       ]' AS JSON)
 WHERE `id` = @id;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов;
