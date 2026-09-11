-- LadaDate: отправка в чат по HTTP вместо сценария (2026-09-11)
--
-- ЗАЧЕМ. DatingAi отправлял реплику в чат сценарием — **60 секунд на сообщение**
-- (замер удачного прогона #522: 59 725 мс). Для пула инвайтов в двадцать реплик
-- это двадцать минут монопольного браузера: очередь прогонов у соседа идёт по
-- одному. Ручка делает то же за миллисекунды.
--
-- ЧТО ВЫЯСНИЛ ПЕРЕХВАТ СЕТИ (`net_watch` / `net_dump`, прогон под анкетой 849 с
-- собеседником в чате). Чат оказался обычным XHR поверх jQuery, без сокета:
--
--     POST /chat-send
--     Content-Type: application/x-www-form-urlencoded; charset=UTF-8
--     id=604366&body=Henry%252C%2520do%2520you%2520prefer…
--
-- Ответ: {"IsSuccess":true,"AccountId":"845089","ChatMinutes":0}
--
-- ⚠ ТЕЛО ЗАКОДИРОВАНО ДВАЖДЫ. В `chat-app.js` стоит `escape(mes)` **внутри**
-- form-urlencode: `%252C` → `%2C` → запятая. Устаревший `escape` не-ASCII пишет
-- как `%uXXXX`, чего нет ни в одном стандарте. Отсюда `"encode":
-- "js_escape_form"` — DatingAi воспроизводит эту пару как есть
-- (`site_base_encode`), а не «делает правильно»: одним слоем у собеседника на
-- месте запятой оказался бы `%2C`.
--
-- ⚠ `/chat-select` ПЕРЕД ОТПРАВКОЙ НЕ НУЖЕН. Страница его делает всегда, но `id`
-- приходит в теле самой отправки. Проверено прямым HTTP по снятой сессии:
-- `chat-send` без `select` вернул `IsSuccess: true`, и реплика легла в диалог.
--
-- ⚠ ПРИЗНАК УДАЧИ — `"IsSuccess":true`, А НЕ КОД 200. Сайт отвечает 200 и на
-- отказ: у ответа есть ветка `ERROR_INSUFFICIENT_FUNDS` — у агентства кончились
-- минуты чата. Смотри мы на код, «письмо не ушло» читалось бы как «ушло».
--
-- ⚠ ДОСТАТОЧНО COOKIE. Проверено по одному: без `X-Requested-With`, без `Referer`,
-- вообще без всего кроме `User-Agent` ручка отвечает тем же JSON. Поэтому
-- `presence.headers` здесь нет — лишний заголовок описывал бы требование, которого
-- сайт не выдвигает.
--
-- ⚠ `answer_language` ЗАДАЁТСЯ ЯВНО. Фильтр сайта отклоняет кириллицу («Message
-- not delivered. Unacceptable words: …»), и язык — вопрос доставки, а не вкуса.
-- Его читают и автоответ, и инвайты.
--
-- Идемпотентность: `presence` у сайта сейчас `NULL`, и ставится он целиком только
-- когда пуст. Непустой не трогаем — там могли завестись `chat` или `driver`, и
-- перезапись стёрла бы их молча.

SET @site = (SELECT `id` FROM `browser_site` WHERE `name` = 'Ladadate');

SELECT 'ДО' AS этап, @site AS сайт,
       (SELECT presence IS NULL FROM `browser_site` WHERE `id` = @site) AS presence_пуст;

UPDATE `browser_site`
   SET `presence` = CAST('{
         "base": "https://ladadate.com",
         "answer_language": "en",
         "send": {
           "transport": "http",
           "path": "/chat-send",
           "body": "id={{to}}&body={{text}}",
           "content_type": "application/x-www-form-urlencoded; charset=UTF-8",
           "encode": "js_escape_form",
           "ok_mark": "\\"IsSuccess\\":true"
         }
       }' AS JSON)
 WHERE `id` = @site
   AND (`presence` IS NULL OR JSON_LENGTH(`presence`) = 0);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`presence`, '$.send.path'))
          FROM `browser_site` WHERE `id` = @site) AS путь,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`presence`, '$.send.encode'))
          FROM `browser_site` WHERE `id` = @site) AS кодирование,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`presence`, '$.send.ok_mark'))
          FROM `browser_site` WHERE `id` = @site) AS признак_удачи;
