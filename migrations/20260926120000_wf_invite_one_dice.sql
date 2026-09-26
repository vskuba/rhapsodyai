-- `dating_invite_one`: жребий отдельным шагом, инструментом `dice` (2026-09-26)
--
-- ## ⚠⚠ ЗАЧЕМ (указание человека, не почин модели)
--
-- Все вероятности инвайта бросала **панель** и присылала готовые значения:
-- приём, длину, набор меток имён, показывать ли время. Workflow получал итог и не
-- знал, что это жребий, — а рядом, в `dating_talk`, тот же вопрос уже решён шагом
-- `dice` (шаг «Жребий», id 1650 локально). Два способа на одно дело.
--
-- Теперь жребий живёт **здесь, рядом с промптом, который им пользуется**: новая
-- грань разнообразия стоит правки одного места, а не четырёх (настройка в реестре,
-- код панели, объявление переменной, промпт).
--
-- ## Что бросается
--
--     dice_invite_angle   приём — 8 вариантов равными долями
--     dice_invite_length  длина — 4 варианта равными долями
--     dice_invite_man_name   обращаться к нему по имени — «1» или «0»
--     dice_invite_girl_name  называть своё имя — «1» или «0»
--     dice_invite_time    показывать ли время — «1» или «0»
--
-- ⚠ Приставка `dice_` обязательна и она про чтение: встретив `%dice_invite_angle%`,
-- человек сразу знает — значение не прислали снаружи и не придумала модель, его
-- бросил шаг жребия, и настроено оно там же (`src/tool/dice/dice.py`).
--
-- ## ⚠⚠ Метки имён — ДВЕ независимые переменные, а не одна на сочетания
--
-- Первая версия собирала их одной переменной с четырьмя готовыми фразами (как их
-- писала панель, `mail_agent._slots`). Человек, открыв жребий, увидел верное: у
-- «обоих имён» и «её имени» стояли **нули** — и спросил, почему там не метки, как
-- у четвёртого варианта.
--
-- Ответ вскрыл изъян выбора. Нули были неизбежны:
--
--     её имя     настройки сайта для доли НЕТ вовсе (`INVITE_GIRL_NAME_CHANCE = 0`)
--     оба имени  это ПРОИЗВЕДЕНИЕ двух долей, а `dice` арифметики над ними не знает
--
-- То есть одна переменная загоняла в перемножение, которого инструмент не умеет, и
-- показывала это человеку двумя нулями — а нули в форме читаются как поломка.
--
-- Две независимые переменные `1/0` от этого свободны: у каждой своя доля-метка,
-- ни одного нуля, никакого перемножения. Цена — фразу «какие метки ставить»
-- собирают условные блоки в промптах, и делать это приходится в **трёх** местах:
-- метки читают черновик, судья и правка.
--
-- ⚠ Случай «не выпало ни одной» **не** третий блок с двойным отрицанием, а
-- безусловная фраза в конце: «других меток не ставь, а если выше не названо ни
-- одной — имён быть не должно вовсе». Она верна всегда и заодно запрещает лишние
-- метки — то, за чем следит судья.
--
-- ## ⚠⚠ Доли-метки и умолчания переменных
--
-- `%invite_name_percent%` и `%invite_time_percent%` — настройки сайта DatingAi, и
-- панель их сейчас **не присылает**: она считала жребий сама. Поэтому обе
-- объявлены переменными workflow **с умолчанием** (10): пока панель молчит,
-- жребий работает по умолчанию, а начнёт присылать — заработает настройка сайта.
--
-- ⚠ Без умолчания метка доехала бы до инструмента как есть, и он отверг бы заход:
-- «доля не число». То есть первый же прогон после наката упал бы.
--
-- ## ⚠ Что панель продолжает присылать, и это не мусор
--
-- `invite_angle`, `invite_length`, `invite_slots`, `invite_time` остаются
-- объявленными: панель их присылает, а промпты больше не читают. Снимать их надо
-- **с той стороны** — вместе с правкой `src/dating/invite.py`, иначе заход начнёт
-- падать на неизвестной входящей переменной. Здесь они просто перестают влиять.
--
-- ## Идемпотентность
--
-- Шаг ищется по инструменту (`tool_invoke.tool_name = 'dice'`) внутри этого
-- workflow, а не по имени и не по позиции: имя человек вправе переименовать, а
-- позиция сдвигается. Повторный накат ничего не добавит и не сдвинет.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_one');

-- ⚠⚠ Обёртка нужна тут не для порядка: **доли приходят снаружи через неё**.
-- Панель зовёт `dating_invite_write`, та передаёт доводы в подвызов, и ребёнок
-- получает их уже оттуда. Объяви доли только у ребёнка — ручка отвергнет вызов
-- («Переменные invite_girl_name_percent … не объявлены»), потому что панель шлёт их
-- обёртке. Поймано прогоном LLM-тестов: они падали не на утверждении, а на вызове.
SET @wrap = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');

-- ⚠ Тип шага берём из справочника по имени: номера типов у баз свои.
SET @tool = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'tool_invoke');

SET @dice = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                      '$.tool_invoke.tool_name')) = 'dice' LIMIT 1);

SELECT 'ДО' AS этап, @wf AS workflow, @tool AS тип_шага,
       COALESCE(@dice, 0) AS жребий_уже_есть,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ── 1. Доли из настроек сайта — переменными с умолчанием ─────────────────────
--
-- ⚠ Тип `input`: значение приходит снаружи, от панели. Умолчание — чтобы жребий
-- работал и пока она молчит.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'invite_name_percent', 'input',
       'Доля инвайтов с обращением по имени, %',
       '10'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'invite_name_percent');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'invite_time_percent', 'input',
       'Доля инвайтов, где показываем время и место, %',
       '10'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'invite_time_percent');

-- ⚠⚠ Доля имени ДЕВУШКИ: умолчание **ноль**, и это решение, а не забывчивость.
-- «Я Diana, и мне скучно» в первой реплике звучит как визитка бота: живой человек
-- называет имя, когда его спросят (тот же довод записан в `invite.py`).
--
-- ⚠ Настройки сайта под неё пока нет — панель держала ноль константой. Переменная
-- заведена, чтобы доля **была выразима**: понадобится — появится настройка, и
-- жребий её подхватит, не меняя ни одной строки здесь.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`, `default`)
SELECT 'invite_girl_name_percent', 'input',
       'Доля инвайтов, где девушка называет своё имя, %',
       '0'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'invite_girl_name_percent');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, one.`wf` FROM `agent_workflow_variable` v
  JOIN (SELECT @wf AS `wf` UNION SELECT @wrap) AS one
 WHERE v.`name` IN ('invite_name_percent', 'invite_time_percent',
                    'invite_girl_name_percent')
   AND one.`wf` IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = one.`wf`);

-- ⚠ И в карту доводов подвызова: объявление у обёртки только разрешает переменную,
-- а доносит её до ребёнка именно карта. Без этой вставки жребий получил бы метку
-- вместо числа и отказал бы: «доля не число».
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.workflow_invoke.inputs_map.invite_name_percent', 'invite_name_percent',
         '$.workflow_invoke.inputs_map.invite_time_percent', 'invite_time_percent',
         '$.workflow_invoke.inputs_map.invite_girl_name_percent',
           'invite_girl_name_percent')
 WHERE `workflow_id` = @wrap
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map') IS NOT NULL;

-- ── 2. Выходы жребия — переменные workflow ──────────────────────────────────
--
-- ⚠ Тип `workflow`, а не `input`: их кладёт шаг, а не вызывающий. Объявление нужно
-- для редактора — он показывает, откуда переменная взялась.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT one.`name`, 'workflow', one.`description` FROM (
        SELECT 'dice_invite_angle' AS `name`,
               'Жребий: приём этого захода' AS `description`
  UNION SELECT 'dice_invite_length', 'Жребий: длина этого захода'
  UNION SELECT 'dice_invite_man_name', 'Жребий: обращаться к нему по имени (1/0)'
  UNION SELECT 'dice_invite_girl_name', 'Жребий: называть своё имя (1/0)'
  UNION SELECT 'dice_invite_time', 'Жребий: показывать ли время и место (1/0)'
) AS one
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` v
                    WHERE v.`name` = one.`name`);

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('dice_invite_angle', 'dice_invite_length', 'dice_invite_time',
                    'dice_invite_man_name', 'dice_invite_girl_name')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ── 3. Шаги после первого сдвигаются на один ────────────────────────────────
--
-- ⚠⚠ Сдвиг **только когда жребия ещё нет**: повторный накат иначе раздвигал бы
-- позиции каждый заход, и номера шагов уезжали бы в пустоту. Ровно этим уже
-- ошиблись однажды (`…070000_wf_talk_channel_positions`).
--
-- ⚠ Сверху вниз (`ORDER BY position DESC`) — иначе UPDATE наткнулся бы на
-- собственный результат, если по позиции есть уникальный ключ.
UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` >= 1 AND @dice IS NULL
 ORDER BY `position` DESC;

-- ── 4. Сам жребий ───────────────────────────────────────────────────────────
--
-- ⚠ Приставка `_const_` у `spec` обязательна: без неё движок пойдёт искать
-- переменную с именем «{"dice_invite_angle":…}» и передаст инструменту `None`.
--
-- ⚠ Позиция 1 — сразу после `datetime_current_get`: время нужно черновику, а
-- жребий решает, показывать ли его. Оба стоят до первого вызова модели.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf, @tool, 'Жребий', 1, JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'to_next_step', TRUE,
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'dice',
           'inputs_map', JSON_OBJECT('spec', CONCAT('_const_', JSON_OBJECT(
             'dice_invite_angle', JSON_OBJECT(
               'прямой вопрос ему — о нём самом, о том, чем занят прямо сейчас', 12.5,
               'наблюдение о нём: скажи, каким он тебе показался, и попроси подтвердить', 12.5,
               'дерзкий вызов или спор: подначь его, поспорь на что-нибудь', 12.5,
               'признание о себе: скажи, почему написала первой, чего тебе хочется', 12.5,
               'интимный вопрос — смелый, но без физиологии: о желаниях, о тайнах', 12.5,
               'игровое предложение: «давай так…», игра, условие, ставка', 12.5,
               'жалоба-приманка: тебе скучно, одиноко, не спится — пусть спасает', 12.5,
               'провокация ожиданием: намекни, что у тебя есть что сказать, но не говори', 12.5),
             'dice_invite_length', JSON_OBJECT(
               'коротко — три-пять слов, одной фразой', 25,
               'средне — одно предложение слов на десять-пятнадцать', 25,
               'длинно — 15–20 слов, можно двумя фразами', 25,
               'абзацем — 25–35 слов, но всё одним куском', 25),
             -- ⚠⚠ Метки имён — **две независимые переменные**, а не одна на
             -- сочетания: у каждой своя доля-метка, и перемножать ничего не надо.
             -- Фразы для промпта собирают условные блоки — см. ниже.
             'dice_invite_man_name', JSON_OBJECT(
               '1', '%invite_name_percent%',
               '0', 'rest'),
             'dice_invite_girl_name', JSON_OBJECT(
               '1', '%invite_girl_name_percent%',
               '0', 'rest'),
             -- ⚠ «1» и «0», а не «да»/«нет»: значение читается условным блоком
             -- `[<if dice_invite_time>]`, а он считает ложью пустое, «0» и «false».
             -- Тот же приём у `dice_mail_story_on` в `dating_talk`.
             'dice_invite_time', JSON_OBJECT(
               '1', '%invite_time_percent%',
               '0', 'rest')))),
           'outputs_map', JSON_OBJECT(
             'dice_invite_angle', 'dice_invite_angle',
             'dice_invite_length', 'dice_invite_length',
             'dice_invite_man_name', 'dice_invite_man_name',
             'dice_invite_girl_name', 'dice_invite_girl_name',
             'dice_invite_time', 'dice_invite_time')))
 WHERE @wf IS NOT NULL AND @tool IS NOT NULL AND @dice IS NULL;

-- ── 5. Промпты читают жребий, а не присланное ───────────────────────────────
--
-- ⚠ Приём, длина и время — простая замена метки: значение одно, место одно.
--
-- ⚠⚠ А метки имён стали **двумя** переменными, и вместо значения на их месте
-- теперь условные блоки. Собираются они прямо в промпте — это единственное место,
-- где выражение разрешено (`workflow.md`, §3.0), и здесь оно по делу: текст для
-- модели, а не решение.
--
-- ⚠ Хвост «других меток не ставь…» — **безусловный**: он верен при любом жребии и
-- закрывает случай «не выпало ни одной», не требуя третьего блока с двойным
-- отрицанием.
SET @slots = CONCAT(
  '[<if dice_invite_man_name>]Поставь в текст метку [[companion_name]] — ровно ',
  'один раз, там, где обращаешься к нему по имени. Панель подставит только ПЕРВОЕ ',
  'имя («John», а не «John Smith»), так что пиши обращение так, как зовут в чате.',
  '\n[<endif>]',
  '[<if dice_invite_girl_name>]Поставь в текст метку [[girl_name]] — ровно один ',
  'раз, там, где называешь своё имя.\n[<endif>]',
  'Других меток не ставь. Если выше не названо ни одной метки — имён в тексте ',
  'быть не должно вовсе: ни своего, ни обращения по имени. Реплика обращена к нему ',
  'и без этого.');

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(REPLACE(REPLACE(
           JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
           '%invite_angle%', '%dice_invite_angle%'),
           '%invite_length%', '%dice_invite_length%'),
           '%invite_slots%', @slots),
           '[<if invite_time>]', '[<if dice_invite_time>]'))
 WHERE `workflow_id` = @wf
   AND JSON_EXTRACT(`metadata`, '$.prompt_user') IS NOT NULL
   -- ⚠ Только те, где ещё стоит старая метка: повторный накат не нужен, а
   -- условие делает его безвредным.
   AND (JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          LIKE '%\%invite_angle\%%'
     OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          LIKE '%\%invite_length\%%'
     OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          LIKE '%\%invite_slots\%%'
     OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          LIKE '%[<if invite_time>]%');

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠⚠ Жребий ровно один: два бросали бы разное, и второй перекрывал бы
       -- первого молча.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'dice') AS жребиев,
       -- ⚠ Позиции без двойников: сдвиг мог наложиться.
       (SELECT COUNT(*) FROM (
          SELECT `position` FROM `agent_workflow_step`
           WHERE `workflow_id` = @wf
           GROUP BY `position` HAVING COUNT(*) > 1) AS x) AS позиций_с_двойниками,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       -- ⚠⚠ Прежних меток не остаётся ни одной: пропущенная означала бы, что шаг
       -- ждёт присланного значения, которого промпт больше не получает.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND (JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%\%invite_angle\%%'
             OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%\%invite_length\%%'
             OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%\%invite_slots\%%'
             OR JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                  LIKE '%[<if invite_time>]%')) AS осталось_прежних,
       -- ⚠ И новые метки на месте — в трёх шагах, что читают метки имён.
       -- ⚠⚠ Блоки имён обязаны стоять во ВСЕХ трёх шагах, что читали метки:
       -- черновик, судья и правка. Пропусти любой — судья требовал бы метки,
       -- которых черновику не заказывали.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
                 LIKE '%[<if dice_invite_man_name>]%') AS шагов_с_блоком_имён,
       -- ⚠ И ни одного нуля в долях жребия: ради этого всё и переделано.
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.inputs_map.spec')) LIKE '%: 0,%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.tool_invoke.tool_name')) = 'dice') AS есть_нулевые_доли,
       -- ⚠⚠⚠ **Переходы ведут на существующие шаги.** Эта проверка добавлена не
       -- впрок: локально я сам занёс битый переход — восстанавливая шаги из
       -- прод-дампа, записал метаданные целиком, вместе с `step_id: 792`. На проде
       -- 792 — это «Накопить», локально «Накопить» = 1501, и переход судьи
       -- «invite_ok == yes» повёл в пустоту.
       --
       -- Молчать такая беда умеет долго: прогон идёт, черновик пишется, судья
       -- решает — и только на ветке «годно» заход спотыкается. Нашёл её человек
       -- глазами в редакторе, а не прогон.
       --
       -- ⚠ Сама миграция переходов не трогает: она вставляет шаг с пустыми
       -- переходами и правит промпты. Проверка стоит здесь потому, что это
       -- последнее место, где на шаги смотрят целиком, — и потому что цена
       -- пропуска измерена.
       (SELECT COUNT(*) FROM `agent_workflow_step` s
          JOIN JSON_TABLE(
                JSON_MERGE_PRESERVE(
                  COALESCE(JSON_EXTRACT(s.`metadata`,
                    '$.transitions_before[*].step_id'), JSON_ARRAY()),
                  COALESCE(JSON_EXTRACT(s.`metadata`,
                    '$.transitions_after[*].step_id'), JSON_ARRAY())),
                '$[*]' COLUMNS (`to` CHAR(20) PATH '$')) AS j
         WHERE s.`workflow_id` = @wf AND j.`to` REGEXP '^[0-9]+$'
           AND NOT EXISTS (SELECT 1 FROM `agent_workflow_step` t
                            WHERE t.`id` = j.`to`)) AS переходов_в_пустоту;
