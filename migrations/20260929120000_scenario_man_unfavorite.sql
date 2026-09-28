-- Сценарий «анкета мужчины: из избранных» (2026-09-29)
--
-- ЗАЧЕМ. Зеркало «анкеты мужчины: в избранные»: человек жмёт «убрать из
-- фаворитов» — и звезда должна погаснуть **и на сайте**. Гасим сами: ручки
-- «снять избранное» у сайта нет, а без шага на сайте звезда остаётся гореть,
-- `favorite_sync` читает список сайта и возвращает строку обратно —
-- «удаление» держится ровно до ближайшей сверки (`favorite_sync_every`).
--
-- ЧТО МЕНЯЕТСЯ ОТНОСИТЕЛЬНО «В ИЗБРАННЫЕ». Один шаг: селектор нажатия.
--
--   .favorite__status:not(.favorite__status-ok)   ← зажечь, добавить
--   .favorite__status.favorite__status-ok          ← погасить, убрать
--
-- Кнопка на анкете одна и та же — переключатель, и состояние лежит в классе
-- (разведка — в миграции «в избранные»). Селектор без `:not`, наоборот,
-- совпадает только с **горящей** звездой: на анкете, где его и так нет в
-- избранных, шаг (`optional`) пропускается, и прогон честно отвечает «его там
-- и так нет» — симметрично тому, как `:not` бережёт уже избранного.
--
-- Состояние снова снимается до и после: по одному «после» не отличить «мы
-- погасили» от «его там и так не было», а для вызывающего это разные исходы.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT COUNT(*) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS уже_есть;

INSERT INTO `browser_scenario` (`site_id`, `name`, `goal`, `start_url`, `steps`,
                                `variables`, `status`)
SELECT @site, 'анкета мужчины: из избранных',
       'войти девушкой, открыть анкету мужчины по его номеру и снять с неё
        избранность — нажать горящую звёздочку. Уже не избранного не трогать:
        кнопка одна и та же, и нажатие по погасшей зажгло бы избранное обратно',
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
         {"action": "wait_for", "url": "", "selector": ".favorite__status", "value": "",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 45000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "2000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": ".favorite__status", "value": "@class",
          "name": "до", "key": "", "fields": [], "optional": true, "timeout_ms": 20000},
         {"action": "click", "url": "", "selector": ".favorite__status.favorite__status-ok",
          "value": "", "name": "", "key": "", "fields": [], "optional": true, "timeout_ms": 30000},
         {"action": "wait_ms", "url": "", "selector": "", "value": "3000",
          "name": "", "key": "", "fields": [], "optional": false, "timeout_ms": 25000},
         {"action": "extract", "url": "", "selector": ".favorite__status", "value": "@class",
          "name": "после", "key": "", "fields": [], "optional": true, "timeout_ms": 20000},
         {"action": "extract", "url": "", "selector": ".favorite__status", "value": "@title",
          "name": "подпись", "key": "", "fields": [], "optional": true, "timeout_ms": 20000}
       ]' AS JSON),
       CAST('{}' AS JSON), 'active'
 WHERE NOT EXISTS (SELECT 1 FROM `browser_scenario`
                    WHERE `name` = 'анкета мужчины: из избранных');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: из избранных') AS шагов,
       (SELECT CAST(`steps` AS CHAR) LIKE '%.favorite__status.favorite__status-ok%'
          FROM `browser_scenario`
          WHERE `name` = 'анкета мужчины: из избранных') AS жмёт_горящую;
