-- Выражение канала вернулось на локаль — доводим до прода (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- В шаге «Переменные» (позиция 0) значение `talk_session_kind` снова оказалось
-- выражением:
--
--     было:  [<if mail_mode>]mail[<else>]chat[<endif>]
--     надо:  chat        — простой текст, а «mail» ставят два шага почтовых веток
--
-- Это уже решённый вопрос: выражение убрала `…060000_wf_talk_no_expressions`, и на
-- **проде оно убрано** — там лежит `chat`, а шаги «Канал: письмо первым» и
-- «Канал: ответ на письмо» перекрывают его на `mail`. Отстала локальная база.
--
-- ## ⚠⚠⚠ Как оно вернулось — и чего это стоит знать
--
-- Возврат жребия (`…080000`) восстанавливал шаг **байт в байт из состояния до
-- правок**, и вместе с жребием вернулось соседнее значение того же шага. То есть
-- «восстановить как было» — операция **не точечная**: она отменяет и то, что
-- правили другой миграцией, если оно лежит в тех же метаданных.
--
-- ⚠ Отсюда правило: восстанавливая шаг целиком, сверяй его с **продом**, а не с
-- памятью о том, что там было. Прод прошёл все миграции по порядку и потому
-- является истиной для таких случаев; локальная база — черновая площадка, на ней
-- состояние могло откатиться руками.
--
-- ## На проде миграция ничего не меняет
--
-- Условие проверяет, что лежит именно выражение. На проде лежит `chat` — UPDATE
-- никого не тронет, и это не «на всякий случай», а способ иметь **один** файл на
-- две базы вместо ручной правки локали.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

-- ⚠ Шаг ищем по содержимому, а не по имени: он звался и «Ключ собеседника», и
-- «Ключи», и «Переменные» — имя меняли трижды, а вторая склейка `girl_unique_id`
-- стоит в нём с самого начала.
SET @keys = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.variable_conversion[1].variable')) = 'girl_unique_id' LIMIT 1);

-- ⚠⚠ `JSON_SEARCH` отдаёт **путь** (`$[6]`), а не номер: склейка его в
-- `$.variable_conversion[$[6]].text` даёт «Invalid JSON path expression». Цифры
-- вынимаются отдельно.
--
-- ⚠ Номером место брать нельзя вдвойне: `…080000` удалила из этого массива запись
-- `dice_spec` и сдвинула всё, что было за ней.
SET @slot = (SELECT REGEXP_REPLACE(JSON_UNQUOTE(JSON_SEARCH(
                      JSON_EXTRACT(`metadata`, '$.variable_conversion[*].variable'),
                      'one', 'talk_session_kind')), '[^0-9]', '')
               FROM `agent_workflow_step` WHERE `id` = @keys);

SELECT 'ДО' AS этап,
       COALESCE(@keys, 0) AS шаг,
       COALESCE(@slot, '—') AS место,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 CONCAT('$.variable_conversion[', @slot, '].text')))
          FROM `agent_workflow_step`
         WHERE `id` = @keys AND @slot IS NOT NULL AND @slot <> '') AS лежит,
       -- ⚠ Обе почтовые ветки обязаны быть на месте: без них `chat` встанет
       -- безусловно, и письма пойдут в канал чата.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` LIKE 'Канал:%') AS шагов_канала;

-- ⚠⚠ Условие «лежит выражение» обязательно. Без него миграция затирала бы значение
-- всегда — и однажды затёрла бы правку человека, сделанную после неё.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REPLACE(`metadata`,
         CONCAT('$.variable_conversion[', @slot, '].text'), 'chat')
 WHERE `id` = @keys AND @keys IS NOT NULL
   AND @slot IS NOT NULL AND @slot <> ''
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         CONCAT('$.variable_conversion[', @slot, '].text'))) LIKE '%[<if %'
   -- ⚠ Два шага канала на месте — иначе правка оставила бы workflow без «mail»
   -- вовсе, и это хуже выражения.
   AND (SELECT COUNT(*) FROM (SELECT `id` FROM `agent_workflow_step`
          WHERE `workflow_id` = @wf AND `title` LIKE 'Канал:%') AS x) = 2;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 CONCAT('$.variable_conversion[', @slot, '].text')))
          FROM `agent_workflow_step`
         WHERE `id` = @keys AND @slot IS NOT NULL AND @slot <> '') AS лежит,
       -- ⚠⚠ Считаем выражения **в значении канала**, а не «по всему workflow».
       --
       -- Первая версия проверки считала любое условие в `variable_conversion` — и
       -- насчитала 19 шагов в базе, из которых 18 законны: там условным блоком
       -- собирается **текст промпта** (`developer_prompt`, `qa_prompt`, склейка
       -- накопленных фактов). Это разрешено — промпт и есть единственное место для
       -- выражения. Незаконно выражение, которое **решает**: `talk_session_kind`
       -- выбирает канал, а канал уже выбран маршрутом.
       --
       -- Считай такая проверка всё подряд — она осталась бы красной навсегда, то
       -- есть перестала бы что-либо значить.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND `metadata` LIKE '%talk_session_kind%'
           AND `metadata` LIKE '%[<if %') AS шагов_с_выражением_канала,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` LIKE 'Канал:%'
           AND `metadata` LIKE '%"mail"%') AS ветки_кладут_mail;
