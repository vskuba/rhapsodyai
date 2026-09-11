-- Разведка анкеты мужчины: нащупываем контейнер (2026-09-08)
--
-- ЧТО УЖЕ ЗНАЕМ. Вход женским кабинетом работает, анкета открывается, и в тексте
-- страницы есть всё нужное:
--
--     Gerhard, 64 … Id: 275296 Location Stuttgart, Germany Occupation
--     Marital Status Widowed Children None Height 175 cm … Education University
--     Smoke No Drink On Occasions Level of English About Partner (age 18 - 40)
--
-- ⚠ ПАРОЛЬ СОСЕД ПОДСТАВЛЯЕТ САМ. Первые три прогона отвечали «E-mail or password
-- invalid», потому что вызывающий передавал `girl_password` из `dating_profile` —
-- и перебивал им верную переменную сайта. У агентства пароль общий, в анкетах его
-- нет вовсе.
--
-- ЧТО ИЩЕМ ТЕПЕРЬ. Текст со `body` тащит меню и подвал. Пробуем несколько
-- кандидатов контейнера разом — какой попадёт, тот и возьмём в рабочий сценарий.
-- Все шаги `optional`: промах по селектору не должен ронять разведку.

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
         {"action": "wait_ms", "url": "", "selector": "", "value": "12000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "goto", "url": "{{profile_url}}", "selector": "", "value": "",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 90000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "8000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},

         {"action": "extract_rows", "url": "", "selector": "li:has-text(\\"Marital Status\\")",
          "value": "", "name": "кандидат_li", "key": "",
          "fields": [{"name": "класс", "selector": ":scope", "attribute": "class", "mandatory": false, "fields": []},
                     {"name": "текст", "selector": ":scope", "attribute": "", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 15000},
         {"action": "extract_rows", "url": "", "selector": "tr:has-text(\\"Marital Status\\")",
          "value": "", "name": "кандидат_tr", "key": "",
          "fields": [{"name": "класс", "selector": ":scope", "attribute": "class", "mandatory": false, "fields": []},
                     {"name": "текст", "selector": ":scope", "attribute": "", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 15000},
         {"action": "extract_rows", "url": "", "selector": "div[class]:has-text(\\"Marital Status\\")",
          "value": "", "name": "кандидат_div", "key": "",
          "fields": [{"name": "класс", "selector": ":scope", "attribute": "class", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 15000},
         {"action": "extract", "url": "", "selector": "h1", "value": "",
          "name": "заголовок", "key": "", "fields": [], "optional": true, "timeout_ms": 10000},
         {"action": "extract_rows", "url": "", "selector": "img[src*=\\"photo\\"]",
          "value": "", "name": "фото", "key": "",
          "fields": [{"name": "src", "selector": ":scope", "attribute": "src", "mandatory": false, "fields": []}],
          "optional": true, "timeout_ms": 10000}
       ]' AS JSON)
 WHERE `id` = @id;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario` WHERE `id` = @id) AS шагов;
