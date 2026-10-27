-- Гостевая лента Step2Love: сценарий «гости: список» (2026-10-27)
--
-- ЗАЧЕМ. DatingAi снимает список визитов на анкету кнопкой на странице и кругом
-- гостей (`guests_round.py`); имя сценария и разбор ответа — у драйвера сайта
-- `step2love`. Локально сценарий появился прямо в базе; сюда переносится то же
-- самое, чтобы на другой установке лента заводилась одной выкладкой.
--
-- ⚠ Имя — голое: другим сайтам оно пока не нужно, а индекс имени у соседа один
-- на всю таблицу. Если второй сайт заведёт свою ленту до этой выкладки — ему
-- достаётся метка, и читалка DatingAi такое нахождение терпит (`_scenario_named`).
--
-- ⚠ Отбор по адресу сайта, а не по номеру: номер закладки на другой установке
-- свой, адрес же принадлежит самому сайту.
--
-- ⚠ Даты визитов в карточке нет — она лежит в ячейке **голым текстом**, без
-- тега, и не достаётся ни одним CSS-селектором. Поэтому рядом с `extract_rows`
-- идёт `read_text` всей страницы: по нему драйвер и доклеивает даты по маркеру
-- «(ID: …)». Убрать второй шаг — и лента останется без дат молча.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап, id, site_id, name FROM browser_scenario
 WHERE name = 'гости: список'
 ORDER BY id;

-- --------------------------------------------- Сценарий ленты Step2Love
INSERT INTO browser_scenario (site_id, name, goal, start_url, steps,
                              variables, status)
SELECT bs.id, 'гости: список',
       'снять список гостей из кабинета девушки: список визитов на её анкету',
       'https://agency.step2love.com/my_profiles.php',
       CAST('[{"action": "goto", "selector": "", "url": "{{panel_url}}login/", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_for", "selector": "input[name=\\"login_lg\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "fill", "selector": "input[name=\\"login_lg\\"]", "url": "", "value": "{{panel_login}}", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "fill", "selector": "input[name=\\"pass_lg\\"]", "url": "", "value": "{{panel_password}}", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "click", "selector": "form[name=\\"login_form\\"] input[type=\\"submit\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_url", "selector": "", "url": "**billing.php**", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "goto", "selector": "", "url": "{{panel_url}}my_profiles.php", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_for", "selector": "button[onclick*=\\"autologinsettoken({{profile_login}})\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "click", "selector": "button[onclick*=\\"autologinsettoken({{profile_login}})\\"]", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_ms", "selector": "", "url": "", "value": "10000", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "goto", "selector": "", "url": "https://mystep2love.com/guests/", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "wait_for", "selector": "td:has(p.gal_id)", "url": "", "value": "", "key": "", "name": "", "timeout_ms": 60000, "optional": true, "submit": false, "shot": "", "shot_selector": "", "fields": []}, {"action": "extract_rows", "selector": "td:has(p.gal_id)", "url": "", "value": "", "key": "", "name": "guests", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": [{"name": "number", "selector": "p.gal_id", "attribute": "", "mandatory": true, "fields": []}, {"name": "name", "selector": "p.gal_name a", "attribute": "", "mandatory": true, "fields": []}, {"name": "link", "selector": "p.gal_name a", "attribute": "href", "mandatory": false, "fields": []}, {"name": "photo", "selector": "img", "attribute": "src", "mandatory": false, "fields": []}]}, {"action": "read_text", "selector": "body", "url": "", "value": "", "key": "", "name": "guests_text", "timeout_ms": 60000, "optional": false, "submit": false, "shot": "", "shot_selector": "", "fields": []}]' AS JSON),
       CAST('{}' AS JSON), 'active'
  FROM browser_site bs
 WHERE bs.url LIKE '%mystep2love.com%'
   AND NOT EXISTS (SELECT 1 FROM browser_scenario s WHERE s.name = 'гости: список');

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, id, site_id, name, status FROM browser_scenario
 WHERE name = 'гости: список'
 ORDER BY id;
