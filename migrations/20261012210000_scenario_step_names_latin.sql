-- Сценарии: имена шагов `extract` — латиницей (2026-10-12)
--
-- ЗАЧЕМ. Имя шага уезжает ключом в ответ прогона, а ключ в коде обязан быть
-- латиницей (`code_rules.md`, §1.2): кириллический не найти `grep`-ом с
-- латинской раскладки, а `с`/`c` и `о`/`o` в нём различимы только байтами.
-- Читает эти ответы DatingAi, и там они лежали ключами словарей.
--
-- ⚠⚠ ЭТО ВТОРОЙ ЗАХОД ПЕРЕЕЗДА, И ПОРЯДОК РЕШАЕТ ВСЁ.
--
--   1. DatingAi  — код учится понимать **оба** имени (`scenario_field.py`)
--   2. RhapsodyAi — этот файл: шаги переименованы
--   3. потом     — из DatingAi убираются старые имена
--
-- Выложи эту миграцию раньше первого захода, и работающий на проде код
-- перестанет понимать ответ: разом встанут импорт анкет, списки собеседников,
-- переписка из панели, отправка и избранные. Ровно эта грабля уже случалась при
-- снятии входящей переменной у соседа и стоила 91 отказа.
--
-- ⚠ ЗАМЕНА ПО ТЕКСТУ JSON, А НЕ ПО ПУТИ. Индексы шагов у разных установок свои —
-- сценарии правят руками в админке, и `$[8].name` на проде и локально указывают
-- на разное. Замена идёт по виду `"name": "..."`, то есть по тому, что от
-- установки не зависит.
--
-- ⚠ ПРОВЕРЕНО НА ПРОДЕ ДО ПРАВКИ: ни одно из переименовываемых слов не
-- встречается в сценариях нигде, кроме значения `name` или `key`, — ни в
-- селекторах, ни в подстановках. Поэтому замена не задевает ничего, кроме имён.
--
-- ⚠ `REGEXP_REPLACE` с `[[:space:]]*`, а не `REPLACE` строкой: сериализация JSON
-- у MySQL ставит пробел после двоеточия, но это её свойство, а не договор.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап, COUNT(*) AS сценариев_с_кириллицей
  FROM `browser_scenario`
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"[а-яёА-ЯЁ]';

UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"анкеты"', '"$1": "profiles"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"анкеты"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"мужчины"', '"$1": "men"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"мужчины"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"избранные"', '"$1": "favorites"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"избранные"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"диалоги"', '"$1": "dialogs"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"диалоги"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"сообщения"', '"$1": "messages"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"сообщения"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"имя"', '"$1": "name"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"имя"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"город"', '"$1": "city"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"город"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"номер"', '"$1": "number"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"номер"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"фото"', '"$1": "photo"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"фото"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"ссылка"', '"$1": "link"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"ссылка"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"статус_класс"', '"$1": "status_class"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"статус_класс"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"новый"', '"$1": "is_new"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"новый"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"когда"', '"$1": "when"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"когда"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"от_номер"', '"$1": "from_uid"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"от_номер"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"кому_номер"', '"$1": "to_uid"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"кому_номер"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"от"', '"$1": "from"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"от"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"кому"', '"$1": "to"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"кому"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"текст_подсказка"', '"$1": "text_title"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"текст_подсказка"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"текст"', '"$1": "text"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"текст"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"отправлено"', '"$1": "sent"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"отправлено"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"анкета"', '"$1": "profile"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"анкета"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"шапка"', '"$1": "head"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"шапка"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"до"', '"$1": "before"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"до"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"после"', '"$1": "after"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"после"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"разделы"', '"$1": "sections"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"разделы"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"подпись"', '"$1": "caption"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"подпись"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"счёт"', '"$1": "count"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"счёт"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"любые_карточки"', '"$1": "any_cards"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"любые_карточки"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"карточки"', '"$1": "cards"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"карточки"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"вкладки"', '"$1": "tabs"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"вкладки"';
UPDATE `browser_scenario`
   SET `steps` = CAST(REGEXP_REPLACE(CAST(`steps` AS CHAR),
        '"(name|key)"[[:space:]]*:[[:space:]]*"класс"', '"$1": "css_class"') AS JSON)
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"класс"';

-- ---------------------------------------------------------------- После
-- ⚠ Обязан быть ноль. Остаток значит, что в сценарии завелось имя, которого не
-- было в разведке, — и DatingAi его не знает: `SCENARIO_FIELD_WAS` там закрытый.
SELECT 'ПОСЛЕ' AS этап, COUNT(*) AS осталось_с_кириллицей
  FROM `browser_scenario`
 WHERE CAST(`steps` AS CHAR) REGEXP '"(name|key)"[[:space:]]*:[[:space:]]*"[а-яёА-ЯЁ]';
