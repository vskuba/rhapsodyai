-- Инвайты: время уходит из реплики совсем (2026-09-26)
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека)
--
-- Человек убрал из промптов инвайта **и** показ времени (`dice_invite_time`), **и**
-- страну (`invite_country`). Значит осиротели ещё две переменные:
--
--     invite_time_percent  доля жребия — бросать больше нечего
--     dice_invite_time     выход жребия — его никто не читает
--
-- ⚠ Это продолжение правила «убираем то, чего не читают», а не новое решение:
-- объявленная, но не читаемая переменная обещает влияние, которого нет. Человек,
-- увидев её в реестре, задаст значение — и в промпте ничего не изменится.
--
-- ## ⚠ Довод, по которому время вообще заводили, — в силе, и это надо знать
--
-- «Доброе утро» в девять вечера выдаёт робота вернее всего остального; ради этого
-- время и показывали. Мера была в доле: 94 инвайта из 202 за сутки поминали время,
-- когда его давали всегда. Теперь решено не показывать вовсе — и если решение
-- пересмотрят, возвращать придётся три вещи: долю, выход жребия и секцию промпта.
--
-- ## ⚠⚠ Шаг `datetime_current_get` удаляется тоже — он стал ничьим
--
-- Его результата в промптах больше нет, а значит шаг считал время, которое никто
-- не читает. Человек убрал его локально; миграция делает то же на проде — иначе
-- прод остался бы с шагом, а локаль без, и «синхронизировано» перестало бы быть
-- правдой.
--
-- ⚠⚠ Вместе с шагом осиротела входящая `datetime_current_get_zone`: её читал
-- **только он** (`inputs_map`), больше никто. Панель её тоже перестаёт присылать —
-- иначе ручка отвергнет вызов, как уже отвергала пять прежних.
--
-- ⚠ Позиции после удаления пересчитываются, чтобы не осталось дырки: номер шага
-- человек читает глазами в редакторе и в трассе. Переходы от этого не страдают —
-- они по `step_id`, а не по соседству.
--
-- ⚠ Если время когда-нибудь вернут, вернуть придётся четыре вещи: шаг, пояс, долю
-- и секцию промпта. Это дороже, чем держать мёртвый шаг, — но мёртвый шаг в
-- трассе читается как работа, и цена его именно в этом.

SET @one = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_one');
SET @wrap = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` IN (@one, @wrap)
           AND v.`name` IN ('invite_time_percent', 'dice_invite_time',
                            'datetime_current_get_zone')) AS привязок,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wrap
           AND JSON_EXTRACT(`metadata`, '$.workflow_invoke') IS NOT NULL
         LIMIT 1) AS доводов_подвызова,
       -- ⚠ Сверяем, что человек и правда убрал время из жребия: миграция снимает
       -- долю, и если жребий её ещё читает — он откажет на первом заходе.
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')) LIKE '%invite_time_percent%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @one
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'dice') AS жребий_ещё_просит_долю;

-- ── 1. Секции времени и страны уходят из промптов ───────────────────────────
--
-- ⚠⚠ **У судьи они остались, и это ловушка.** Человек убрал время и страну из
-- промпта **черновика** — того, который читает глазами, — а у судьи те же две
-- секции стоят своими словами: «Сейчас у неё», «Откуда она». Локально их нет,
-- потому что правил он вручную оба? Нет: сверка показала, что нет только у
-- черновика.
--
-- Поймано **сверкой промптов** копии прода с локалью, а не чтением: секции
-- отличаются одним словом («у тебя» против «у неё»), и глазами их принимают за одну.
--
-- ⚠ Вырезаем блок целиком — вместе с условием и `[<endif>]`, — а не только метку:
-- оставленный `[<if dice_invite_time>]…[<endif>]` с пустым телом дал бы судье
-- заголовок без времени под ним, и он читал бы его как факт.
--
-- ⚠ Метка времени внутри блока ссылается на **прод-номер шага** (`_788_`), которого
-- локально нет вовсе. Ещё один повод резать по границам блока, а не по метке.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REGEXP_REPLACE(
           REGEXP_REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
             -- ⚠⚠⚠ Флаг `'n'` обязателен: блок **многострочный** (между условием
             -- и `[<endif>]` стоят переводы строк), а `.` их по умолчанию не
             -- покрывает. Без флага шаблон не совпадает ни с чем, и миграция
             -- проходит молча — секция у судьи остаётся. Ровно это и случилось:
             -- поймано сверкой промптов, а не отказом.
             --
             -- ⚠ Доводы `REGEXP_REPLACE` после замены: позиция 1, «заменить все» 0,
             -- затем флаги. Пропустить их нельзя — флаг стоит пятым.
             '\\[<if dice_invite_time>\\].*?\\[<endif>\\]', '', 1, 0, 'n'),
             '\\[<if invite_country>\\].*?\\[<endif>\\]', '', 1, 0, 'n'))
 WHERE `workflow_id` = @one
   AND JSON_EXTRACT(`metadata`, '$.prompt_user') IS NOT NULL
   AND (JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          LIKE '%[<if dice_invite_time>]%'
     OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          LIKE '%[<if invite_country>]%');

-- ── 2. Описание жребия: доля времени уходит из `spec` ───────────────────────
--
-- ⚠⚠ **Это главное здесь, и без него прод разошёлся бы с локалью.** Человек убрал
-- `dice_invite_time` из жребия руками, а предыдущая миграция (`…120000`) его туда
-- вставляет — значит на проде он появится и останется: следующие шаги снимают
-- переменные, но не трогают само описание.
--
-- Поймано сверкой: прогнал три миграции на копии прод-состояния и сравнил её
-- описание жребия с локальным. Разошлось ровно на этой переменной.
--
-- ⚠ Убираем **по ключу**, а не перезаписью всего `spec`: перезапись затёрла бы
-- правки долей, если их поправят руками до наката.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.inputs_map.spec',
         CONCAT('_const_', JSON_REMOVE(
           CAST(SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
             '$.tool_invoke.inputs_map.spec')), 8) AS JSON),
           '$.dice_invite_time')))
 WHERE `workflow_id` = @one
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.tool_invoke.tool_name')) = 'dice'
   -- ⚠ Только когда доля там есть: иначе повторный накат пересобирал бы `spec`
   -- заново без нужды, а `JSON_REMOVE` несуществующего ключа вернул бы тот же JSON
   -- с переставленными ключами — и «локаль = прод» перестало бы сверяться побайтно.
   AND JSON_EXTRACT(CAST(SUBSTRING(JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
         '$.tool_invoke.inputs_map.spec')), 8) AS JSON),
         '$.dice_invite_time') IS NOT NULL;

-- ⚠ И выход жребия из `outputs_map`: он объявлял, куда кладётся выпавшее. Остался
-- бы — жребий писал бы переменную, которой никто не читает.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REMOVE(`metadata`,
         '$.tool_invoke.outputs_map.dice_invite_time')
 WHERE `workflow_id` = @one
   AND JSON_EXTRACT(`metadata`,
         '$.tool_invoke.outputs_map.dice_invite_time') IS NOT NULL;

-- ── 3. Карта доводов подвызова ──────────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_REMOVE(`metadata`,
         '$.workflow_invoke.inputs_map.invite_time_percent',
         '$.workflow_invoke.inputs_map.datetime_current_get_zone')
 WHERE `workflow_id` = @wrap
   AND (JSON_EXTRACT(`metadata`,
          '$.workflow_invoke.inputs_map.invite_time_percent') IS NOT NULL
     OR JSON_EXTRACT(`metadata`,
          '$.workflow_invoke.inputs_map.datetime_current_get_zone') IS NOT NULL);

-- ── 4. Шаг времени и его пояс ───────────────────────────────────────────────
--
-- ⚠ Ищем по инструменту, а не по имени: имя человек вправе переименовать.
SET @time_step = (SELECT `id` FROM `agent_workflow_step`
                   WHERE `workflow_id` = @one
                     AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                           '$.tool_invoke.tool_name')) = 'datetime_current_get'
                   LIMIT 1);

DELETE FROM `agent_workflow_step`
 WHERE `id` = @time_step AND @time_step IS NOT NULL;

-- ⚠⚠ **Позиции НЕ пересчитываются, и это решение, а не недосмотр.**
--
-- Шаг стоял нулевым, и после удаления нумерация начинается с единицы — дырка
-- безвредна: порядок задаёт `ORDER BY position`, а не непрерывность. Зато сдвиг
-- **создал бы расхождение**: человек удалил шаг локально руками, позиции там
-- остались 1..6, и миграция, сдвинув их на проде к 0..5, развела бы две базы,
-- которые мы только что свели.
--
-- ⚠ Первая версия сдвигала, и репетиция это показала: на копии локали (где шага
-- уже нет) сдвиг молчал, а на проде сработал бы — то есть расхождение вышло бы
-- только на проде, где его труднее всего замечать.

-- ── 5. Объявления у обоих workflow ──────────────────────────────────────────
--
-- ⚠ Сама строка справочника остаётся: `agent_workflow_variable` общий, и та же
-- переменная может быть привязана к чужому workflow, о котором эта миграция не
-- знает. Снимаем только привязку.
DELETE vw FROM `agent_workflow_variable_workflow` vw
  JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
 WHERE vw.`workflow_id` IN (@one, @wrap)
   AND v.`name` IN ('invite_time_percent', 'dice_invite_time',
                    'datetime_current_get_zone');

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Привязок не остаётся ни одной — это и есть цель.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` IN (@one, @wrap)
           AND v.`name` IN ('invite_time_percent', 'dice_invite_time',
                            'datetime_current_get_zone')) AS привязок,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wrap
           AND JSON_EXTRACT(`metadata`, '$.workflow_invoke') IS NOT NULL
         LIMIT 1) AS доводов_подвызова,
       -- ⚠ Доли, которые ЧИТАЮТСЯ жребием, уцелели: их две, и потеряй их — жребий
       -- отказал бы на первом заходе («доля не число»).
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE vw.`workflow_id` = @one
           AND v.`name` IN ('invite_name_percent',
                            'invite_girl_name_percent')) AS доли_жребия,
       -- ⚠⚠ Ни одного следа времени и страны в промптах — ни у черновика, ни у
       -- судьи, ни у правки. Считаем шаги, где что-то осталось.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @one
           AND (JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%dice_invite_time%'
             OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%invite_country%'
             OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%datetime_current_get_%')) AS промптов_со_временем,
       -- ⚠⚠ Жребий больше не бросает время: ни в описании, ни в выходах.
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')) LIKE '%dice_invite_time%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @one
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'dice') AS жребий_ещё_бросает_время,
       -- ⚠ Шага времени больше нет, и пояса вместе с ним.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @one
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'datetime_current_get') AS шагов_времени,
       -- ⚠⚠ Позиции без дырок и без двойников: сдвиг мог наложиться.
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step`
           WHERE `workflow_id` = @one
           GROUP BY `position` HAVING COUNT(*) > 1) AS x) AS позиций_с_двойниками,
       (SELECT MIN(`position`) FROM `agent_workflow_step`
         WHERE `workflow_id` = @one) AS первая_позиция;
