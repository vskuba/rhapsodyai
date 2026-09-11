-- Сценарий «анкета мужчины: в избранные» (2026-09-10)
--
-- ЗАЧЕМ. Ответившего на письмо мужчину надо добавить девушке в избранные: на
-- сайте это звёздочка на его анкете. У сайта есть ручка, которая избранных
-- **читает** (`GET /users/my-favorites`), а ручки «добавить» нет — только кнопка
-- на странице. Значит браузер, значит сценарий.
--
-- ЧТО ВЫЯСНИЛА РАЗВЕДКА (пробный сценарий, два прогона под анкетой 849):
--
--   1. Звёздочка — не ссылка и не кнопка с подписью, а элемент без текста:
--
--        <i class="favorite__status  profile_btn-friend" title="Add to Favorites">
--
--   2. **Состояние лежит в классе.** У того, кто уже в избранных:
--
--        class="favorite__status favorite__status-ok profile_btn-friend"
--        title="Remove from Favorites"
--
--      То есть кнопка одна и та же, и второе нажатие **снимает** избранное.
--   3. Текст шапки анкеты меняется вместе с ней: «ADD TO FAVORITES» у одного,
--      «REMOVE FAVORITE» у другого. Отсюда же видно, что это переключатель.
--   4. Нажатие уходит запросом без перезагрузки страницы: класс дописывается на
--      месте (и вместе с ним `profile_btn-friend_disable` — кнопка гаснет).
--   5. Гостю анкета мужчины не показывается вовсе (404) — нужен вход девушкой.
--      То же, что у «анкеты мужчины: карточка», и вход здесь тот же шаг в шаг.
--
-- ⚠ НАЖИМАЕМ ТОЛЬКО НЕЗАЖЖЁННУЮ ЗВЕЗДУ — `:not(.favorite__status-ok)`, и шаг
-- помечен `optional`. Это главное в сценарии: кнопка переключатель, и повторный
-- прогон по тому же человеку **снял бы** избранное вместо того, чтобы ничего не
-- сделать. Селектор с `:not` не совпадает ни с чем на анкете уже избранного, шаг
-- пропускается, и прогон честно отвечает «он и так там».
--
-- Проверено живыми прогонами: 788856 (уже избранный) — класс до и после
-- одинаков, ничего не тронуто; 181685 (не избранный) — после прогона
-- `favorite__status-ok` появился, а список сайта вырос с 18 до 19.
--
-- ⚠ СОСТОЯНИЕ СНИМАЕМ ДО И ПОСЛЕ, а не только после. По одному «после» не
-- отличить «мы добавили» от «он там был», а это разные события: первое стоит
-- сорока секунд браузера и его надо записать, второе — повод больше не ходить.
--
-- ⚠ ПАРОЛЬ ПЕРЕДАЁТ ВЫЗЫВАЮЩИЙ. У анкеты есть настройка, каким паролем ходить —
-- своим или общим агентским (`password_source`), — и решает её DatingAi
-- (`dating_password_pick`). Подставь сосед свою переменную сайта, анкета с личным
-- паролем ходила бы под чужим. То же правило, что у карточки мужчины.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT COUNT(*) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: в избранные') AS уже_есть;

INSERT INTO `browser_scenario` (`site_id`, `name`, `goal`, `start_url`, `steps`,
                                `variables`, `status`)
SELECT @site, 'анкета мужчины: в избранные',
       'войти девушкой, открыть анкету мужчины по его номеру и добавить его в её '
       'избранные — нажать звёздочку. Уже избранного не трогать: кнопка одна и та '
       'же, и второе нажатие сняло бы избранное',
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
         {"action": "click", "url": "", "selector": ".favorite__status:not(.favorite__status-ok)",
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
                    WHERE `name` = 'анкета мужчины: в избранные');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: в избранные') AS сценарий,
       (SELECT JSON_LENGTH(`steps`) FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: в избранные') AS шагов,
       (SELECT CAST(`steps` AS CHAR) LIKE '%:not(.favorite__status-ok)%'
          FROM `browser_scenario`
         WHERE `name` = 'анкета мужчины: в избранные') AS не_снимает;
