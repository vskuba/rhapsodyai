-- «анкета мужчины: карточка»: запасное фото из галереи (2026-09-08)
--
-- ЧТО БЫЛО. Главный портрет (`img.ratio-1x15-img`) у одного из двух мужчин пришёл
-- заглушкой `/images/placeholder-loading.svg`: сайт грузит картинки лениво, и в
-- `src` успевает попасть она. Карточка осталась без лица — а собеседник без имени
-- и аватарки в списке читается как мусор.
--
-- ЧТО ВМЕСТО. Снимаем **и галерею** (`img[src*="content/photos"]`). Разбор в
-- DatingAi берёт первое, что не заглушка: сперва портрет, потом галерею. Миниатюра
-- с суффиксом `-s` хуже портрета, но несравнимо лучше пустого места.
SET @id = (SELECT `id` FROM `browser_scenario` WHERE `name` = 'анкета мужчины: карточка');

UPDATE `browser_scenario`
   SET `steps` = JSON_ARRAY_APPEND(`steps`, '$',
         CAST('{"action": "extract_rows", "url": "",
                "selector": "img[src*=\\"content/photos\\"]", "value": "",
                "name": "фото_галерея", "key": "",
                "fields": [{"name": "src", "selector": ":scope", "attribute": "src",
                            "mandatory": false, "fields": []}],
                "optional": true, "timeout_ms": 15000}' AS JSON))
 WHERE `id` = @id;

SELECT JSON_LENGTH(`steps`) AS шагов FROM `browser_scenario` WHERE `id` = @id;
