-- Luxee: вход в панель ждёт кабинет `/profile/`, а не `/agency/` (2026-11-16)
--
-- ЗАЧЕМ. Панель Luxee теперь читается операторской учёткой (раздел «Models
-- admin»: Profiles, Communication, Clients). После входа сайт отвечает
-- `redirect_url: https://luxee.io/profile/`, а сценарии ждали прежний кабинет
-- агентства `**/agency/**` — на новой учётке шаг `wait_url` вставал бы на
-- тридцати секундах ожидания при удавшемся входе.
--
-- Шаг входа одинаков у двух сценариев Luxee — «вход в панель» и «импорт
-- анкет», — и правится в обоих: учётка у них общая (переменные сайта
-- `panel_login`/`panel_password`), и сменить её одному значит сломать другого.
--
-- ⚠ Остальные шаги «импорта анкет» (таблица на `/profiles/`) писаны под
-- прежний кабинет и этой правкой не чинятся: новая страница анкет — плитки,
-- а не таблица. Это отдельная работа.
--
-- ⚠ Отбор по адресу сайта, а не по номеру закладки: номер на другой установке
-- свой.

SELECT 'ДО' AS этап, s.id, s.name,
       JSON_SEARCH(s.steps, 'one', '**/agency/**') AS где
  FROM browser_scenario s JOIN browser_site b ON b.id = s.site_id
 WHERE b.url LIKE '%luxee.io%';

UPDATE browser_scenario s JOIN browser_site b ON b.id = s.site_id
   SET s.steps = CAST(REPLACE(CAST(s.steps AS CHAR), '"**/agency/**"',
                              '"**/profile/**"') AS JSON)
 WHERE b.url LIKE '%luxee.io%'
   AND s.name IN ('вход в панель', 'импорт анкет')
   AND JSON_SEARCH(s.steps, 'one', '**/agency/**') IS NOT NULL;

SELECT 'ПОСЛЕ' AS этап, s.id, s.name,
       JSON_SEARCH(s.steps, 'one', '**/profile/**') AS где
  FROM browser_scenario s JOIN browser_site b ON b.id = s.site_id
 WHERE b.url LIKE '%luxee.io%';
