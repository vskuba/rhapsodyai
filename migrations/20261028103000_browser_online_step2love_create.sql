-- Лента «Все онлайн» Step2Love: сценарий «анкеты мужчин: список» заводится, если его нет (2026-10-28)

-- ЗАЧЕМ. На проде лента «Все онлайн» для Step2Love не снималась никогда: круг
-- ходит, а сценария в базе нет — DatingAi честно рапортует «у сайта нет сценария
-- — заведите его в RhapsodyAi». Локально он был заведён руками в базу, и прошлая
-- миграция (`20261027210000`) лишь чинила существующий, на пустой установке он
-- не создаёт ничего. Эта — заводит, ровно в том виде, в каком сценарий починен
-- той миграцией: те же 13 шагов, те же ожидания.

-- ⚠ Отбор по адресу сайта, а не по номеру: номер закладки на другой установке
-- свой, адрес же принадлежит самому сайту. Имя — с меткой `(Step2Love)`: индекс
-- имени у соседа один на всю таблицу, голое имя уже занято Ladadate.

-- ⚠ Guard на `NOT EXISTS` — по паре «имя + адрес сайта», а не по одному имени:
-- установка, где сценарий уже есть (наша локальная, например), проходит мимо и
-- не трогает настроенное.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап, s.id, bs.url, s.name, s.status
  FROM browser_scenario s JOIN browser_site bs ON bs.id = s.site_id
 WHERE s.name LIKE 'анкеты мужчин: список%'
   AND bs.url LIKE '%mystep2love.com%';

-- ----------------------------------------- Сценарий заведён (если не был)
INSERT INTO browser_scenario (site_id, name, goal, start_url, steps,
                              variables, status)
SELECT bs.id, 'анкеты мужчин: список (Step2Love)',
       'снять ленту мужчин в сети со страницы /online/: вход в кабинет девушки через кнопку «Логин» в панели агентства',
       'https://agency.step2love.com/my_profiles.php',
       CAST('[{\"action\": \"goto\", \"selector\": \"\", \"url\": \"{{panel_url}}login/\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"wait_for\", \"selector\": \"input[name=\\"login_lg\\"]\", \"url\": \"\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"fill\", \"selector\": \"input[name=\\"login_lg\\"]\", \"url\": \"\", \"value\": \"{{panel_login}}\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"fill\", \"selector\": \"input[name=\\"pass_lg\\"]\", \"url\": \"\", \"value\": \"{{panel_password}}\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"click\", \"selector\": \"form[name=\\"login_form\\"] input[type=\\"submit\\"]\", \"url\": \"\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"wait_url\", \"selector\": \"\", \"url\": \"**billing.php**\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": true, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"goto\", \"selector\": \"\", \"url\": \"{{panel_url}}my_profiles.php\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"wait_for\", \"selector\": \"button[onclick*=\\"autologinsettoken({{profile_login}})\\"]\", \"url\": \"\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"click\", \"selector\": \"button[onclick*=\\"autologinsettoken({{profile_login}})\\"]\", \"url\": \"\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"wait_ms\", \"selector\": \"\", \"url\": \"\", \"value\": \"10000\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"goto\", \"selector\": \"\", \"url\": \"https://mystep2love.com/online/\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"wait_for\", \"selector\": \"td:has(p.gal_id)\", \"url\": \"\", \"value\": \"\", \"key\": \"\", \"name\": \"\", \"timeout_ms\": 60000, \"optional\": true, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": []}, {\"action\": \"extract_rows\", \"selector\": \"td:has(p.gal_id)\", \"url\": \"\", \"value\": \"\", \"key\": \"\", \"name\": \"men\", \"timeout_ms\": 60000, \"optional\": false, \"submit\": false, \"shot\": \"\", \"shot_selector\": \"\", \"fields\": [{\"name\": \"number\", \"fields\": [], \"selector\": \"p.gal_id\", \"attribute\": \"\", \"mandatory\": true}, {\"name\": \"name\", \"fields\": [], \"selector\": \"p.gal_name a\", \"attribute\": \"\", \"mandatory\": true}, {\"name\": \"link\", \"fields\": [], \"selector\": \"p.gal_name a\", \"attribute\": \"href\", \"mandatory\": false}, {\"name\": \"photo\", \"fields\": [], \"selector\": \"img\", \"attribute\": \"src\", \"mandatory\": false}, {\"name\": \"status_class\", \"fields\": [], \"selector\": \"p img[src$=\\".png\\"]\", \"attribute\": \"src\", \"mandatory\": false}]}]' AS JSON),
       CAST('{}' AS JSON), 'active'
  FROM browser_site bs
 WHERE bs.url LIKE '%mystep2love.com%'
   AND NOT EXISTS (SELECT 1 FROM browser_scenario s
                     WHERE s.site_id = bs.id
                       AND s.name LIKE 'анкеты мужчин: список%');

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, s.id, bs.url, s.name, s.status, JSON_LENGTH(s.steps) AS шагов
  FROM browser_scenario s JOIN browser_site bs ON bs.id = s.site_id
 WHERE s.name LIKE 'анкеты мужчин: список%'
   AND bs.url LIKE '%mystep2love.com%';
