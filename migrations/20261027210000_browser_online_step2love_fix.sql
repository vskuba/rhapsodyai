-- Лента «Все онлайн» Step2Love: починка сценария «анкеты мужчин: список» (2026-10-27)

-- ЗАЧЕМ. Круг ленты ходил на сайт с 14:51 и 47 раз подряд падал на шаге 6:
-- `Timeout 30000ms exceeded ... waiting for navigation to "**billing.php**"`.
-- Клик по кнопке входа возвращался за 173–180 мс, навигации не случалось — панель
-- отвечала медленнее, чем ждал шаг. Для сравнения: соседская «гости: список»
-- (id 541) тем же сайтом и теми же шагами снимает успешно, у неё те же ожидания
-- по 60 секунд. Эта миграция подравнивает тайминги и выставляет сценарий заново
-- живым (`status` RhapsodyAi сам помечает `broken` после неудач, на `/run` это не
-- влияет, но страницу «Сценарии» читает человек, и `broken` там выглядит поломкой).

-- ⚠ Отбор по адресу сайта, а не по номеру: номер закладки на другой установке
-- свой, адрес же принадлежит самому сайту. Имя с меткой сайта `(Step2Love)` —
-- та же договорённость, что у прочих сценариев этого сайта; читалка DatingAi
-- (`_scenario_named`) её срезает.

-- ⚠ Шаг 6 (`wait_url billing.php`) здесь и **optional: true** — от гостевого
-- зеркала это единственное отступление по решению, не по недосмотру: навигация
-- после входа occasionally запаздывает даже за 60 секунд, и с `false` прогон
-- умирал безликим «timeout waiting for navigation». С `true` он идёт дальше и
-- падает на шаге 8 понятной строкой «нет кнопки авто-логина» — это ровно то же
-- самое событие (панель не пуста, но сессии нет), только названное своим именем.

-- ⚠ Шаг 12 (`wait_for td:has(p.gal_id)`) — optional: в ленте онлайна пустая
-- страница к ночи обычное дело; гостям это не грозило, им и не нужно.

-- ⚠ Полю `photo` обязателен: без него карусель на странице рисует буквы вместо
-- лиц. Селектор взят гостевой, той же страницы разметки; `status_class` оставлен
-- как был — по нему драйвер сайта помечает статус, на лентах онлайна это не
-- решающе, но терять разбор незачем.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап, s.id, s.status, JSON_LENGTH(s.steps) AS шагов
      ,JSON_EXTRACT(s.steps, '$[5].timeout_ms') AS шаг6_ждёт
  FROM browser_scenario s JOIN browser_site bs ON bs.id = s.site_id
 WHERE s.name = 'анкеты мужчин: список (Step2Love)'
   AND bs.url LIKE '%mystep2love.com%';

-- ------------------------------------------------- Сценарий починен
UPDATE browser_scenario s JOIN browser_site bs ON bs.id = s.site_id
   SET s.steps = CAST('[{"action": "goto", "selector": "", "url": "{{panel_url}}login/", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_for", "selector": "input[name=\\"login_lg\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "fill", "selector": "input[name=\\"login_lg\\"]", "url": "", "value": "{{panel_login}}", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "fill", "selector": "input[name=\\"pass_lg\\"]", "url": "", "value": "{{panel_password}}", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "click", "selector": "form[name=\\"login_form\\"] input[type=\\"submit\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_url", "selector": "", "url": "**billing.php**", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": true, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "goto", "selector": "", "url": "{{panel_url}}my_profiles.php", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_for", "selector": "button[onclick*=\\"autologinsettoken({{profile_login}})\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "click", "selector": "button[onclick*=\\"autologinsettoken({{profile_login}})\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_ms", "selector": "", "url": "", "value": "10000", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "goto", "selector": "", "url": "https://mystep2love.com/online/", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_for", "selector": "td:has(p.gal_id)", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": true, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "extract_rows", "selector": "td:has(p.gal_id)", "url": "", "value": "", "key": "", "name": "men", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": [{"name": "number", "fields": [], "selector": "p.gal_id", "attribute": "", "mandatory": true}, {"name": "name", "fields": [], "selector": "p.gal_name a", "attribute": "", "mandatory": true}, {"name": "link", "fields": [], "selector": "p.gal_name a", "attribute": "href", "mandatory": false}, {"name": "photo", "fields": [], "selector": "img", "attribute": "src", "mandatory": false}, {"name": "status_class", "fields": [], "selector": "p img[src$=\\".png\\"]", "attribute": "src", "mandatory": false}]}]' AS JSON),
      s.status = 'active'
 WHERE s.name = 'анкеты мужчин: список (Step2Love)'
   AND bs.url LIKE '%mystep2love.com%';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, s.id, s.status, JSON_LENGTH(s.steps) AS шагов
      ,JSON_EXTRACT(s.steps, '$[5].timeout_ms') AS шаг6_ждёт
      ,JSON_EXTRACT(s.steps, '$[12].fields[*].name') AS поля
  FROM browser_scenario s JOIN browser_site bs ON bs.id = s.site_id
 WHERE s.name = 'анкеты мужчин: список (Step2Love)'
   AND bs.url LIKE '%mystep2love.com%';
