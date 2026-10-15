-- Панель Luxee: закладка сайта и три сценария (2026-10-15)
--
-- ЗАЧЕМ. DatingAi читает карточку анкеты Luxee кнопкой «Обновить с сайта» и
-- заводит анкеты кнопкой «Импортировать профили» — обоим нужны закладка сайта и
-- сценарии у соседа. Локально они появились прямо в базе; сюда переносится то же
-- самое, чтобы на другой установке Luxee заводился одной выкладкой.
--
-- ⚠ Имена сценариев — голые («импорт анкет», «анкета: карточка», «вход в панель»):
-- читалка на стороне DatingAi ищет сценарий точным совпадением по имени И номеру
-- сайта. У имени единственный индекс — на имя целиком, без сайта, — поэтому голые
-- имена свободны только когда прежний владелец голых имени ушёл под метку сайта:
-- первым шагом этот файл переименовывает строки Ladadate, и только потом заводит
-- Luxee под освобождённые имена. Порядок внутри файла и есть тот первый шаг.
--
-- ⚠ Отбор по адресу сайта, а не по номеру: номер закладки на другой установке
-- свой, адрес же принадлежит самому сайту.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап, id, site_id, name FROM browser_scenario
 WHERE name IN ('импорт анкет', 'анкета: карточка', 'вход в панель')
 ORDER BY id;

-- ------------------------------------------ Ladadate уходит под метку
UPDATE browser_scenario
   SET name = CONCAT(name, ' (Ladadate)')
 WHERE site_id = (SELECT id FROM browser_site WHERE url LIKE '%ladadate.com%')
   AND name IN ('импорт анкет', 'анкета: карточка', 'вход в панель');

-- ----------------------------------------------------- Закладка Luxee
INSERT INTO browser_site (name, url, position, tags)
SELECT 'Luxee', 'https://luxee.io/',
       (SELECT MAX(bs.position) + 1 FROM browser_site bs), 'dating'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM browser_site WHERE url LIKE '%luxee%');

-- ------------------------------------------------ Сценарии анкет Luxee
INSERT INTO browser_scenario (site_id, name, goal, start_url, steps,
                           variables, status)
SELECT bs.id, 'импорт анкет', 'Список анкет партнёрской панели Luxee: номер, имя, фото', 'https://luxee.io/profiles/',
       CAST('[{"key": "", "url": "{{panel_url}}", "name": "", "value": "", "action": "goto", "fields": [], "optional": false, "selector": "", "timeout_ms": 60000}, {"key": "", "url": "", "name": "", "value": "", "action": "wait_for", "fields": [], "optional": false, "selector": "button.log__in", "timeout_ms": 45000}, {"key": "", "url": "", "name": "", "value": "1500", "action": "wait_stable", "fields": [], "optional": false, "selector": "", "timeout_ms": 15000}, {"key": "", "url": "", "name": "", "value": "", "action": "click", "fields": [], "optional": false, "selector": "button.log__in", "timeout_ms": 10000}, {"key": "", "url": "", "name": "", "value": "", "action": "wait_for", "fields": [], "optional": false, "selector": "#userIdentifierId", "timeout_ms": 15000}, {"key": "", "url": "", "name": "", "value": "{{panel_login}}", "action": "fill", "fields": [], "optional": false, "selector": "#userIdentifierId", "timeout_ms": 10000}, {"key": "", "url": "", "name": "", "value": "{{panel_password}}", "action": "fill", "fields": [], "optional": false, "selector": "#passwordId", "timeout_ms": 10000}, {"key": "", "url": "", "name": "", "value": "", "action": "click", "fields": [], "optional": false, "selector": "button.global__button.form:has-text(\\"Sign in\\")", "timeout_ms": 15000}, {"key": "", "url": "**/agency/**", "name": "", "value": "", "action": "wait_url", "fields": [], "optional": false, "selector": "", "timeout_ms": 30000}, {"key": "", "url": "{{panel_url}}profiles/", "name": "", "value": "", "action": "goto", "fields": [], "optional": false, "selector": "", "timeout_ms": 45000}, {"key": "", "url": "", "name": "profiles", "value": "", "action": "extract_rows", "fields": [{"name": "number", "fields": [], "selector": "td:nth-child(1)", "attribute": "", "mandatory": true}, {"name": "name", "fields": [], "selector": "td:nth-child(3)", "attribute": "", "mandatory": false}, {"name": "photo", "fields": [], "selector": "td:nth-child(2) img", "attribute": "src", "mandatory": false}, {"name": "link", "fields": [], "selector": "a[href*=\\"/profile/update/\\"]", "attribute": "href", "mandatory": false}], "optional": false, "selector": "table tbody tr", "timeout_ms": 20000}]' AS JSON), CAST('{}' AS JSON), 'active'
  FROM browser_site bs
 WHERE bs.url LIKE '%luxee%'
   AND NOT EXISTS (SELECT 1 FROM browser_scenario s WHERE s.name = 'импорт анкет');

INSERT INTO browser_scenario (site_id, name, goal, start_url, steps,
                           variables, status)
SELECT bs.id, 'анкета: карточка', 'Карточка анкеты Luxee: город, год рождения, занятие, описание', 'https://luxee.io/profile/update/',
       CAST('[{"key": "", "url": "{{panel_url}}profile/update/{{profile_id}}/", "name": "", "value": "", "action": "goto", "fields": [], "optional": false, "selector": "", "timeout_ms": 30000}, {"key": "", "url": "", "name": "", "value": "1000", "action": "wait_stable", "fields": [], "optional": false, "selector": "", "timeout_ms": 15000}, {"key": "", "url": "", "name": "", "value": "", "action": "click", "fields": [], "optional": true, "selector": "a.click-edit-info", "timeout_ms": 5000}, {"key": "", "url": "", "name": "birth_year", "value": "@value", "action": "extract", "fields": [], "optional": false, "selector": "input[name=\\"FakeProfileModel[birthday]\\"]", "timeout_ms": 15000}, {"key": "", "url": "", "name": "city", "value": "", "action": "extract", "fields": [], "optional": false, "selector": "select[name=\\"FakeProfileModel[city_id]\\"] + .select2 .select2-selection__rendered", "timeout_ms": 15000}, {"key": "", "url": "", "name": "occupation", "value": "@value", "action": "extract", "fields": [], "optional": true, "selector": "input[name=\\"FakeProfileModel[occupation]\\"]", "timeout_ms": 10000}, {"key": "", "url": "", "name": "about", "value": "@value", "action": "extract", "fields": [], "optional": true, "selector": "textarea[name=\\"FakeProfileModel[bio]\\"]", "timeout_ms": 10000}]' AS JSON), CAST('{}' AS JSON), 'active'
  FROM browser_site bs
 WHERE bs.url LIKE '%luxee%'
   AND NOT EXISTS (SELECT 1 FROM browser_scenario s WHERE s.name = 'анкета: карточка');

INSERT INTO browser_scenario (site_id, name, goal, start_url, steps,
                           variables, status)
SELECT bs.id, 'вход в панель', 'Вход учёткой агентства в партнёрскую панель Luxee: cookie-сессия для чтения анкет', 'https://luxee.io/',
       CAST('[{"key": "", "url": "{{panel_url}}", "name": "", "value": "", "action": "goto", "fields": [], "optional": false, "selector": "", "timeout_ms": 60000}, {"key": "", "url": "", "name": "", "value": "", "action": "wait_for", "fields": [], "optional": false, "selector": "button.log__in", "timeout_ms": 45000}, {"key": "", "url": "", "name": "", "value": "1500", "action": "wait_stable", "fields": [], "optional": false, "selector": "", "timeout_ms": 15000}, {"key": "", "url": "", "name": "", "value": "", "action": "click", "fields": [], "optional": false, "selector": "button.log__in", "timeout_ms": 10000}, {"key": "", "url": "", "name": "", "value": "", "action": "wait_for", "fields": [], "optional": false, "selector": "#userIdentifierId", "timeout_ms": 15000}, {"key": "", "url": "", "name": "", "value": "{{panel_login}}", "action": "fill", "fields": [], "optional": false, "selector": "#userIdentifierId", "timeout_ms": 10000}, {"key": "", "url": "", "name": "", "value": "{{panel_password}}", "action": "fill", "fields": [], "optional": false, "selector": "#passwordId", "timeout_ms": 10000}, {"key": "", "url": "", "name": "", "value": "", "action": "click", "fields": [], "optional": false, "selector": "button.global__button.form:has-text(\\"Sign in\\")", "timeout_ms": 15000}, {"key": "", "url": "**/agency/**", "name": "", "value": "", "action": "wait_url", "fields": [], "optional": false, "selector": "", "timeout_ms": 30000}]' AS JSON), CAST('{}' AS JSON), 'active'
  FROM browser_site bs
 WHERE bs.url LIKE '%luxee%'
   AND NOT EXISTS (SELECT 1 FROM browser_scenario s WHERE s.name = 'вход в панель');

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, s.id, s.site_id, s.name, s.status FROM browser_scenario s
  JOIN browser_site bs ON bs.id = s.site_id
 WHERE bs.url LIKE '%luxee%' OR s.name LIKE '% (Ladadate)'
 ORDER BY s.id;
