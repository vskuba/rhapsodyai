-- Панель Luxee: переменные прогона сценариев (2026-10-15)

-- Сценарии Luxee подставляют {{panel_url}}, {{panel_login}} и {{panel_password}};
-- без них сосед не принимает прогон («не переданы переменные», 422). Локально их
-- завели через админку; здесь то же самое, шифротексты — под ключ этой установки.
-- Закладка находится по адресу, а не по номеру: номер на другой установке свой.

INSERT INTO browser_site_variable (site_id, name, value, is_secret, position)
SELECT bs.id, v.name, v.value, v.is_secret, v.pos
  FROM browser_site bs,
       (SELECT 'panel_url' AS name,
               CAST('https://luxee.io/' AS CHAR) AS value, 0 AS is_secret, 1 AS pos
        UNION ALL SELECT 'panel_login', CAST('enc:v1:gAAAAABq0T7drpOS1DddpBL7BnuV8hP8xCEY2a8cqg1ArYUmWsR7CnnPjH5sKljo-TmZuojlgozTT6xcdLSc6a8iI2BrTkjok9-MsHZLoqhQe_OEvXeoXsY=' AS CHAR), 1, 2
        UNION ALL SELECT 'panel_password', CAST('enc:v1:gAAAAABq0T7dxhzmRcgOOyYB9R6NfDKFahiDphrrqApF0bA1dBd0JvuBIpTazkD8wQsonjFKGcWxinZ01vDb1tgSIVIJKHs87Q==' AS CHAR), 1, 3) v
 WHERE bs.url LIKE '%luxee%'
   AND NOT EXISTS (SELECT 1 FROM browser_site_variable sv
                    WHERE sv.site_id = bs.id AND sv.name = v.name);

SELECT 'ПОСЛЕ' AS этап, v.site_id, v.name, v.is_secret, LEFT(v.value, 12) AS начало
  FROM browser_site_variable v JOIN browser_site bs ON bs.id = v.site_id
 WHERE bs.url LIKE '%luxee%' ORDER BY v.position;
