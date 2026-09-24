-- Жребий переезжает в начало и становится общим на все занятия (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Шаг звался «Жребий письма» и стоял двенадцатым — перед самой развилкой веток.
-- Обе приметы оказались временными: жребий нужен не только письмам, а место
-- посреди цепочки прячет его от глаз. Теперь он **первый** и зовётся «Жребий»:
-- всё, что в заходе решается случаем, решается здесь и разом.
--
-- ⚠ Первым шагом он стоит не для красоты: жребий ни от чего не зависит, а вот
-- от него зависят промпты ниже. Шаг, который ничего не ждёт и всем нужен, —
-- ровно то, что читают в начале списка.
--
-- ## Что переехало в жребий: приём инициативы
--
-- `initiative_kind` был **входящей** переменной: приём выбирала панель
-- (`initiative.py`, `INITIATIVE_KINDS` — двенадцать приёмов с весами, дающими
-- ровно сто) и присылала готовым. Это жребий и есть, только брошенный не там.
--
-- Веса перенесены слово в слово, так что поведение не меняется — меняется место.
-- Заодно из workflow уходит одна входящая переменная: чем меньше договор с
-- панелью, тем меньше поводов ему разойтись.
--
-- ⚠⚠ **`mail_kind` остаётся входящей, и это проверено, а не забыто.** Он тоже
-- «kind», и соблазн убрать его следом велик. Но он не выбор, а **факт работы**:
-- «write» — письмо первым, «reply» — ответ на пришедшее. Выпади «reply» жребием
-- тому, кто ничего не писал, девушка ответит на несуществующее письмо. Живёт он
-- в одном месте — `transitions_before` шага «Ответ в чат», — и там ему и место.
--
-- ## ⚠⚠ Доли трёх осей приходят настройками сайта
--
-- Настройки живы в реестре DatingAi и до сих пор ни на что не влияли: переезд
-- писем на `dating_talk` унёс код, который их читал. Теперь они входящие
-- переменные с умолчаниями, равными прежним:
--
--     dice_mail_name_percent      10   в скольких письмах звать по имени
--     dice_mail_question_percent  25   в скольких кончать вопросом
--     dice_mail_story_percent     40   в скольких рассказывать о себе
--
-- ⚠ Умолчание обязательно: панель может их и не прислать (`…defaults_apply`
-- кладёт умолчание в начале захода), и тогда всё работает, как работало.
--
-- ## ⚠ Доля-«остаток» — почему без неё нельзя
--
-- Пара «да/нет» с долей из настройки иначе не пишется: второй половины мы не
-- знаем, а `{да: %percent%, нет: 75}` при настройке 40 даёт 115 — то есть отказ
-- на живом заходе из-за подвинутого ползунка. `"rest"` забирает всё, что не
-- разобрали соседи, и сумма сходится при любой настройке.
--
-- ## ⚠ Ворота рассказа отдельно от темы
--
-- Доля рассказа — одно число настройки, а тем восемь. Дели настройку на восемь —
-- и она перестанет читаться глазами. Поэтому осей две: `dice_mail_story_on`
-- решает «рассказывать ли» (значения «1»/«0» — `%if%` считает «0» ложью), а
-- `dice_mail_story` выбирает тему и бросается всегда.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @dice = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf
                AND `title` IN ('Жребий письма', 'Жребий') LIMIT 1);
SET @at = (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @dice);

SELECT 'ДО' AS этап, @dice AS шаг, @at AS место_сейчас;

-- ── Шаг в начало и под общим именем ─────────────────────────────────────────
--
-- ⚠⚠ Сдвиг только когда шаг **не** в начале: иначе повторный прогон отодвигал бы
-- остальных снова и снова, растя позиции до бесконечности.
UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf AND `position` < @at AND @at > 0;

UPDATE `agent_workflow_step`
   SET `position` = 0, `title` = 'Жребий'
 WHERE `id` = @dice;

-- ── Описание жребия целиком ─────────────────────────────────────────────────
--
-- ⚠ Записываем **заменой, а не правкой по кусочкам**: осей стало шесть, и
-- собирать их `JSON_SET`-ами значило бы шесть мест, где можно ошибиться в одном.
--
-- ⚠⚠ Литералом, без промежуточной `@переменной`: она не держит тип JSON — ровно
-- на этом сегодня сломались три ветки (`…_wf_talk_branch_json_string_fix`).
-- Здесь нужна строка, и всё же привычку заводить не будем.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.tool_invoke.inputs_map.spec', CONCAT('_const_', '{"dice_mail_opening": {"начни с того, чем она была занята, когда вспомнила о нём": 20, "начни сразу с мысли или вопроса — без предисловия о себе": 20, "начни с того, что рассказывал он, и вернись к этому": 20, "начни с короткой новости о себе, будто с порога": 20, "начни с наблюдения о нём — что ей в нём показалось": 20}, "dice_mail_name": {"назови его по имени один раз, в первой фразе": "%dice_mail_name_percent%", "по имени не обращайся вовсе": "rest"}, "dice_mail_question": {"закончи письмо вопросом к нему": "%dice_mail_question_percent%", "закончи письмо утверждением, признанием или рассказом — без вопроса": "rest"}, "dice_mail_story_on": {"1": "%dice_mail_story_percent%", "0": "rest"}, "dice_mail_story": {"как прошёл её день — обычные мелочи, без событий": 12.5, "забавный случай, который приключился с ней на днях": 12.5, "чего ей хочется: желание, мечта, то, о чём думает перед сном": 12.5, "случай из жизни, который она запомнила надолго": 12.5, "её опыт общения с мужчинами: что нравится, что отталкивает": 12.5, "её привычка или маленькая странность, о которой мало кто знает": 12.5, "что она делала на выходных или собирается делать": 12.5, "место, куда ей хочется съездить, и почему именно туда": 12.5}, "dice_initiative_kind": {"расскажи короткую историю из своего дня — что-то обычное и живое: работа, дорога, кофе, сосед, погода. Без морали и без вопроса в конце": 14, "задай ему лёгкий вопрос о нём: чем занят, как прошёл день, что за музыка или сериал сейчас. Один вопрос, не три": 13, "пофлиртуй: намекни, что думала о нём, или скажи что-то тёплое — но коротко и без приторности": 12, "подколи его по-доброму: поддразни за что-то, что он говорил раньше, или за мужские привычки вообще": 10, "скажи что-то спорное и спроси, согласен ли он: про еду, привычки, сериалы, утро или вечер. Спор ради разговора, а не ссоры": 9, "предложи игру: «выбери одно из двух» или «угадай». Дай ему готовый выбор, чтобы отвечать было легко": 8, "расскажи короткую смешную нелепость, которая случилась с тобой сегодня. Смеяться надо над собой, а не над ним": 8, "признайся в чём-то маленьком и личном: чего боишься, что откладываешь, какая привычка дурацкая. Коротко, без исповеди": 7, "пожалуйся на скуку и спроси, чем себя занять. Просьба о совете — самый простой повод ответить": 6, "спроси про его планы на вечер или выходные и скажи про свои": 6, "пошути мрачно и с самоиронией — чёрный юмор без жестокости и без политики. Одна фраза": 4, "скажи откровенную глупость или нелепицу просто так, без повода — ту, что скорее рассмешит, чем озадачит": 3}}'),
         '$.tool_invoke.outputs_map', JSON_OBJECT(
             'dice_mail_opening', 'dice_mail_opening',
             'dice_mail_name', 'dice_mail_name',
             'dice_mail_question', 'dice_mail_question',
             'dice_mail_story_on', 'dice_mail_story_on',
             'dice_mail_story', 'dice_mail_story',
             'dice_initiative_kind', 'dice_initiative_kind'))
 WHERE `id` = @dice;

-- ── Настройки сайта как входящие переменные ─────────────────────────────────
--
-- ⚠ Тип `input`, а не `workflow`: их присылает панель из настроек сайта. Умолчание
-- равно тому, что стоит в реестре DatingAi, — не пришлют, и заход пойдёт как шёл.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_name_percent', 'input', '10',
       'Доля писем, где собеседника зовут по имени, %. Настройка сайта' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_name_percent');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_question_percent', 'input', '25',
       'Доля писем, кончающихся вопросом, %. Настройка сайта' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_question_percent');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_story_percent', 'input', '40',
       'Доля писем с рассказом девушки о себе, %. Настройка сайта' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_story_percent');

-- ── Новые выходы жребия ─────────────────────────────────────────────────────
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_mail_story_on', 'workflow', '',
       'Рассказывать ли о себе: 1 или 0. Жребий шага' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_mail_story_on');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'dice_initiative_kind', 'workflow', '',
       'Каким приёмом заговорить первой. Жребий шага' FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'dice_initiative_kind');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('dice_mail_name_percent', 'dice_mail_question_percent',
                    'dice_mail_story_percent', 'dice_mail_story_on',
                    'dice_initiative_kind')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = @wf);

-- ── Приём инициативы больше не приходит снаружи ─────────────────────────────
--
-- ⚠⚠ Рвём **связь с этим workflow**, а саму переменную не удаляем: реестр
-- `agent_workflow_variable` общий на все workflow, и `initiative_kind` может
-- понадобиться соседнему. Удали строку — и сломается тот, о ком мы не думали.
--
-- ⚠ После этого панель, приславшая `initiative_kind`, получит `400`: ручка
-- отвергает незаявленное. Поэтому DatingAi перестаёт его слать той же правкой —
-- порядок выкладки здесь имеет значение.
DELETE x FROM `agent_workflow_variable_workflow` x
  JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
 WHERE x.`workflow_id` = @wf AND v.`name` = 'initiative_kind';

-- ── Промпт «Инициатива»: приём из жребия ────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%initiative_kind%', '%dice_initiative_kind%'))
 WHERE `workflow_id` = @wf AND `title` = 'Инициатива';

-- ── Промпты писем: рассказ теперь за воротами ───────────────────────────────
--
-- ⚠ Тема бросается всегда, а спрашиваем — только когда ворота открыты. Иначе
-- пришлось бы держать долю рассказа размазанной по восьми темам.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%if dice_mail_story%', '%if dice_mail_story_on%'))
 WHERE `workflow_id` = @wf AND `title` IN ('Письмо первым', 'Ответ на письмо');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT `title` FROM `agent_workflow_step` WHERE `id` = @dice) AS имя,
       (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @dice) AS место,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS шагов_на_нуле,
       (SELECT JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.tool_invoke.outputs_map'))
          FROM `agent_workflow_step` WHERE `id` = @dice) AS осей,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @wf AND v.`name` = 'initiative_kind')
         AS приём_ещё_входящий,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%\%initiative_kind\%%') AS промптов_со_старой_меткой;
