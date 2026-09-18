-- `dating_invite_write`: реплики набираются ЦИКЛОМ по одной (2026-09-18)
--
-- ЧТО БЫЛО НЕ ТАК. Просили у модели сразу N реплик одним ответом. Она честно
-- пыталась, судья честно бракова́л похожие — и на живом прогоне шаг правки вернул
-- ОДНУ реплику вместо двенадцати: в пул легли двенадцать анкет с одним текстом.
--
-- Чинить это дописыванием «ровно %invite_count% штук» в каждое место промпта —
-- бесконечная игра: где-то останется единственное число, и модель пойдёт за ним.
-- Число элементов в одном ответе она держит плохо, и спорить с этим бесполезно.
--
-- ЧТО СТАЛО. Просим по ОДНОЙ реплике, а повторяем столько раз, сколько нужно:
-- движок умеет это сам (`workflow_invoke` + `repeat.count`). Число реплик теперь
-- вопрос арифметики, а не послушания модели.
--
--   dating_invite_write (обёртка)          dating_invite_one (одна реплика)
--   ├── workflow_invoke × %invite_count% ──┤ 0 время
--   └── ответ конвертом                    │ 1 черновик (ОДНА реплика)
--                                          │ 2 судья
--                                          │ 3 правка по замечанию
--                                          │ 4 накопление
--                                          └ 5 ответ: всё накопленное
--
-- ⚠⚠ КАК КОПИТСЯ РЕЗУЛЬТАТ — в этом вся соль, и правки движка не нужно.
--
-- `outputs_map` на каждом повторе ПЕРЕЗАПИСЫВАЕТ переменную родителя, так что
-- само по себе накопления не выйдет. Но `inputs_map` собирается заново **на каждом
-- повторе** и видит уже записанное. Значит ребёнок получает накопленное на входе,
-- дописывает к нему своё и возвращает целиком — а перезапись кладёт назад полный
-- список.
--
--   повтор 1: вход ''            → ребёнок вернул 'раз'
--   повтор 2: вход 'раз'         → ребёнок вернул 'раз---два'
--   повтор 3: вход 'раз---два'   → ребёнок вернул 'раз---два---три'
--
-- ⚠⚠ СУДЬЯ ПРИ ЭТОМ СТАЛ СИЛЬНЕЕ, А НЕ СЛАБЕЕ. Он судит одну реплику — но видит
-- все предыдущие этого захода и бракует похожую. Прежде он сравнивал двенадцать
-- текстов разом «в уме»; теперь сравнение попарное и конкретное.
--
-- ⚠ Приём и длина приходят от панели на весь заход — одни на все повторы.
-- Разнообразие даёт не они, а накопленное: каждая следующая реплика пишется,
-- глядя на уже написанные.
--
-- Идемпотентность: workflow и шаги заводятся по условию отсутствия, промпты
-- переписываются целиком, лишние шаги обёртки снимаются по позиции.

-- ══════════════════════════════════════════ Ребёнок: одна реплика
INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`,
                              `group_name`, `subflow`)
SELECT 2, 'dating_invite_one', 'Инвайт: одна реплика',
       'Одна первая реплика в чат: черновик, судья, правка. Зовётся циклом из dating_invite_write',
       0, 'dating', 1
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow` WHERE `name` = 'dating_invite_one');

SET @one = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_one');
SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_invite_write');

SELECT 'ДО' AS этап, @wf AS обёртка, @one AS ребёнок,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов_обёртки,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @one) AS шагов_ребёнка;

-- ---------------------------------------------------------------- Переменные
--
-- ⚠ Накопитель. Пустой на первом повторе; дальше несёт всё, что уже написано в
-- этом заходе, разделённое строкой «---».
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'invite_done', 'workflow',
       'Реплики, уже написанные в этом заходе. Растёт с каждым повтором цикла'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'invite_done');

-- Ребёнку нужны те же переменные, что и прежнему промпту, плюс накопитель.
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @one FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('invite_slots', 'invite_angle', 'invite_length', 'invite_avoid',
                    'invite_country', 'invite_time', 'invite_draft', 'invite_ok',
                    'invite_why', 'invite_done', 'datetime_current_get_zone')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @one);

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'invite_done'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- Шаг 0: время
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @one, 3, 'datetime_current_get', 0,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'tool_invoke', JSON_OBJECT(
           'tool_name', 'datetime_current_get',
           'inputs_map', JSON_OBJECT('timezone', 'datetime_current_get_zone'),
           'outputs_map', JSON_OBJECT('str', 'datetime_current_get_response')))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @one AND `position` = 0);

SET @stime = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @one AND `position` = 0);

-- ⚠ Метка результата инструмента собирается из ЕГО id: в каждой инсталляции он
-- свой, и строку приходится складывать здесь.
SET @now = CONCAT('%datetime_current_get_', @stime, '_result_str%');

-- ---------------------------------------------------------------- Шаг 1: черновик
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @one, 2, 'Черновик инвайта', 1, JSON_OBJECT('prompt_user', '')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @one AND `position` = 1);

UPDATE `agent_workflow_step`
   SET `type_id` = 2, `title` = 'Черновик инвайта',
       `metadata` = JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'invite_draft',
                       'text', 'Текст шаблона первой реплики, один абзац')),
         'prompt_user',
         CONCAT(
           'Ты — девушка на сайте знакомств, пишешь первой мужчине, с которым ещё ',
           'не знакома. Придумай ШАБЛОН такой первой реплики — ОДНУ.\n\n',
           'Это обычное дело на сайте знакомств: взрослые люди сами пришли ',
           'знакомиться, и первая реплика решает, ответят тебе или нет.\n\n',
           '%if invite_time%=== Сейчас у тебя ===\n', @now, '\n\n%endif%',
           '%if invite_country%=== Откуда ты ===\n%invite_country%\n\n%endif%',
           '=== Требуемый язык ответа (код) ===\n%user_language%\n\n',
           '=== Приём на этот раз ===\n%invite_angle%\n\n',
           '=== Длина на этот раз ===\n%invite_length%\n\n',
           '=== Метки в тексте ===\n%invite_slots%\n\n',
           -- ⚠⚠ Накопленное в ЭТОМ заходе — главный источник разнообразия.
           -- Каждая следующая реплика пишется, глядя на уже написанные.
           '%if invite_done%=== ⚠⚠ Это ты уже написала ПРЯМО СЕЙЧАС — пиши иначе ===\n',
           '%invite_done%\n\n',
           'Твоя новая реплика уйдёт от ДРУГОЙ девушки в ту же минуту, что и эти. ',
           'Напиши её так, чтобы человек, увидев обе, не подумал, что писал один и ',
           'тот же человек: другой заход, другой образ, другое начало. Не вариант ',
           'той же мысли другими словами — другая мысль.\n\n%endif%',
           '%if invite_avoid%=== Так ты писала раньше — тоже не повторяйся ===\n',
           '%invite_avoid%\n\n%endif%',
           'Правила:\n',
           '1. Пиши РОВНО на требуемом языке, указанном выше. Это жёсткое ',
           'требование, а не пожелание: сайт фильтрует сообщения и не на том ',
           'языке отклоняет — реплика не дойдёт до человека вовсе.\n',
           '2. ТЕМАТИКА: флирт, заигрывание, провокация, интимный вопрос, попытка ',
           'соблазнить. Игриво и смело — так, чтобы захотелось ответить прямо ',
           'сейчас. Вежливый опрос не годится совсем: «чем любишь заниматься в ',
           'свободное время?» не цепляет никого.\n',
           '3. ПРИЁМ И ДЛИНА заданы выше — держись их.\n',
           '4. Это ЧАТ, а не письмо: ни темы, ни подписи, ни списков, ни ',
           'переносов строк — всё одним куском. Абзац — предел длины.\n',
           '5. Вопрос НЕ обязателен. Утверждение, намёк, вызов или откровенное ',
           'признание работают не хуже — «спорим, ты сейчас улыбнулся» отвечать ',
           'хочется сильнее, чем «как дела?».\n',
           '6. Ставь ровно те метки, что названы выше в «Метки в тексте», — и ',
           'никаких других. Метку пиши точно как показано, в двойных квадратных ',
           'скобках. Панель заменит её именем; выдуманная метка уйдёт человеку ',
           'прямо в скобках.\n',
           '7. [[girl_name]] — это ТВОЁ имя, ты называешь им СЕБЯ: «меня зовут ',
           '[[girl_name]]». Не пиши о себе в третьем лице. [[companion_name]] — ',
           'имя того, кому пишешь.\n',
           '8. Никаких имён словами, если метки не просили: текст уйдёт разным ',
           'людям, и чужое имя в нём — провал.\n',
           '%if invite_time%9. ВРЕМЯ и МЕСТО названы выше — держись их. Пишешь про ',
           'вечер утром или про выходной в среду — реплика выдаёт робота вернее ',
           'всего остального.\n%endif%',
           '10. Границы: без грубости, без физиологии и прямых непристойностей — ',
           'такое отклоняет фильтр сайта. Без ссылок, контактов и просьб написать ',
           'в мессенджер: это признак спама, за него закрывают учётку.\n\n',
           'Верни строго JSON с одним ключом:\n',
           '- "invite_draft": сам текст шаблона, ОДНОЙ строкой, без кавычек ',
           'вокруг и без пояснений\n\n',
           'Примеры ответа — три разной длины, чтобы было видно вилку:\n',
           '{"invite_draft": "Спорим, ты сейчас улыбнулся?"}\n',
           '{"invite_draft": "У меня к тебе неприличный вопрос, но сначала скажи — ',
           'ты из тех, кто краснеет?"}\n',
           '{"invite_draft": "Знаешь, я обычно не пишу первой, но сегодня мне ',
           'скучно настолько, что я решила рискнуть."}'))
 WHERE `workflow_id` = @one AND `position` = 1;

-- ---------------------------------------------------------------- Шаг 2: судья
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @one, 2, 'Судья', 2, JSON_OBJECT('prompt_user', '')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @one AND `position` = 2);

UPDATE `agent_workflow_step`
   SET `type_id` = 2, `title` = 'Судья',
       `metadata` = JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'invite_ok', 'text', 'yes — годен, no — брак'),
           JSON_OBJECT('variable', 'invite_why',
                       'text', 'Чем плох, одной фразой. Пусто, если годен')),
         'prompt_user',
         CONCAT(
           'Ты — редактор. Проверь, годится ли этот текст как ПЕРВАЯ реплика ',
           'девушки мужчине в чате сайта знакомств. Он уйдёт живым людям без ',
           'правки, поэтому суди строго.\n\n',
           '=== Текст на проверку ===\n%invite_draft%\n\n',
           -- ⚠⚠ Сверка с накопленным — то, ради чего цикл и заводился.
           '%if invite_done%=== ⚠⚠ Эти реплики написаны ПРЯМО СЕЙЧАС, в этом же ',
           'заходе ===\n%invite_done%\n\n',
           'Они уйдут от других наших девушек в ту же минуту. Если проверяемый ',
           'текст похож хоть на одну из них — тот же заход, тот же образ, та же ',
           'мысль другими словами, — это БРАК (no): два человека получат почти ',
           'одинаковое сообщение от двух незнакомок, и это выдаёт агентство.\n\n%endif%',
           '%if invite_avoid%=== Так писали раньше ===\n%invite_avoid%\n\n%endif%',
           '%if invite_time%=== Сейчас у неё ===\n', @now, '\n\n%endif%',
           '%if invite_country%=== Откуда она ===\n%invite_country%\n\n%endif%',
           '=== Что просили ===\nЯзык (код): %user_language%\nМетки: %invite_slots%\n\n',
           'Забракуй (no), если верно ХОТЬ ОДНО:\n',
           '1. Текст похож на одну из написанных прямо сейчас (см. выше). Это ',
           'самая дорогая ошибка здесь.\n',
           '2. Это не реплика, а что-то другое: отказ модели («I can\'t help…», ',
           '«извините»), рассуждение, пояснение, заголовок, список, несколько ',
           'вариантов на выбор.\n',
           '3. Язык не тот, что просили.\n',
           '4. Метки не те. Во всём проекте их две: [[girl_name]] и ',
           '[[companion_name]]. Любая третья — брак. Брак и тогда, когда ',
           'запрошенная метка пропущена или поставлена дважды.\n',
           '5. О себе сказано в третьем лице: «[[girl_name]] думает, что…» — это ',
           'её собственная реплика, она говорит «я».\n',
           '6. В тексте есть чьё-то имя словами (не меткой), ссылка, адрес почты, ',
           'телефон, мессенджер, просьба денег или перехода на другой сайт.\n',
           '7. Больше одного абзаца, есть переносы строк, подпись, тема письма, ',
           'markdown или кавычки вокруг всего текста.\n',
           '8. Комплимент внешности, «я увидела твоё фото», просьба написать ',
           'первым, грубость, откровенная пошлость.\n',
           '9. Время или место названы неверно: «сегодня вечером» утром, «хороших ',
           'выходных» в среду, чужой сезон или чужой праздник.\n',
           '10. Текст пресный и не цепляет: «привет, как дела?», «чем любишь ',
           'заниматься в свободное время?» — на такое не отвечают.\n\n',
           'Во всех остальных случаях — yes. Короткая дерзкая фраза в три слова ',
           'это нормально и даже хорошо.\n\n',
           'Верни строго JSON с ключами:\n',
           '- "invite_ok": "yes" или "no"\n',
           '- "invite_why": чем плох, одной фразой по-русски; пустая строка, если yes\n\n',
           'Пример ответа:\n',
           '{"invite_ok": "no", "invite_why": "повторяет вторую реплику захода: ',
           'тот же заход «докажи, что не такой»"}'))
 WHERE `workflow_id` = @one AND `position` = 2;

SET @sjudge = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @one AND `position` = 2);

-- ---------------------------------------------------------------- Шаг 3: правка
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @one, 2, 'Правка по замечанию', 3, JSON_OBJECT('prompt_user', '')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @one AND `position` = 3);

UPDATE `agent_workflow_step`
   SET `type_id` = 2, `title` = 'Правка по замечанию',
       `metadata` = JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'invite_draft', 'text', 'Исправленный текст'),
           JSON_OBJECT('variable', 'invite_ok', 'text', 'Всегда fixed')),
         'prompt_user',
         CONCAT(
           'Редактор забраковал черновик первой реплики. Напиши вместо него новый ',
           '— ОДИН, — так, чтобы замечание было снято.\n\n',
           '=== Забракованный текст ===\n%invite_draft%\n\n',
           '=== Замечание редактора ===\n%invite_why%\n\n',
           '%if invite_done%=== Эти реплики уже написаны в этом заходе ===\n',
           '%invite_done%\n\nНовая должна отличаться от них по существу: другой ',
           'заход, другой образ, другая мысль.\n\n%endif%',
           '=== Что требуется ===\n',
           '⚠ Замечание редактора выше — служебный текст, он написан по-русски для ',
           'человека. Язык замечания к реплике отношения не имеет: пиши РОВНО на ',
           'языке с кодом ниже.\n',
           'Язык (код): %user_language%\nМетки: %invite_slots%\n\n',
           'Требования те же: ОДНА реплика в чат, один абзац, игривый дразнящий ',
           'тон, ровно запрошенные метки и никаких других (во всём проекте их две: ',
           '[[girl_name]] и [[companion_name]]), никаких имён словами, ссылок и ',
           'контактов. [[girl_name]] — твоё собственное имя, говори о себе в первом ',
           'лице.\n\n',
           'Не объясняй правку и не извиняйся: нужен только новый текст.\n\n',
           'Верни строго JSON с ключами:\n',
           '- "invite_draft": новый текст шаблона одной строкой\n',
           '- "invite_ok": строка "fixed"\n\n',
           'Пример ответа:\n',
           '{"invite_draft": "Спорим, ты сейчас улыбнулся?", "invite_ok": "fixed"}'))
 WHERE `workflow_id` = @one AND `position` = 3;

-- ---------------------------------------------------------------- Шаг 4: накопление
--
-- ⚠⚠ Здесь и работает цикл: к пришедшему на входе дописывается новая реплика, и
-- всё это уходит обратно родителю. Разделитель — строка «---» отдельной строкой,
-- его же ищет панель (`mail_agent.INVITE_SPLIT`).
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @one, 5, 'Накопить', 4, JSON_OBJECT('variable_conversion', JSON_ARRAY())
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @one AND `position` = 4);

UPDATE `agent_workflow_step`
   SET `type_id` = 5, `title` = 'Накопить',
       `metadata` = JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'variable_conversion', JSON_ARRAY(
           JSON_OBJECT('variable', 'invite_done',
                       'text', '%if invite_done%%invite_done%\n---\n%endif%%invite_draft%')))
 WHERE `workflow_id` = @one AND `position` = 4;

-- ---------------------------------------------------------------- Шаг 5: ответ
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @one, 4, 'Ответ обёртке', 5,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'continue_workflow', false,
         'prompt_user', '%invite_done%')
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @one AND `position` = 5);

SET @sdone = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @one AND `position` = 4);

-- Переход судьи: годен — мимо правки, сразу в накопление.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after',
         JSON_ARRAY(JSON_OBJECT('variable', 'invite_ok', 'operator', '==',
                                'value', 'yes', 'step_id', CAST(@sdone AS CHAR))))
 WHERE `id` = @sjudge;

-- ══════════════════════════════════════════ Обёртка: цикл и ответ панели
--
-- ⚠ Прежние шаги обёртки (черновик, судья, правка) уехали к ребёнку — снимаем их.
DELETE FROM `agent_workflow_step` WHERE `workflow_id` = @wf;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
VALUES (@wf, 6, 'Цикл: реплика за репликой', 0,
        JSON_OBJECT(
          'transitions_before', JSON_ARRAY(),
          'transitions_after', JSON_ARRAY(),
          'workflow_invoke', JSON_OBJECT(
            'workflow_id', @one,
            -- ⚠⚠ `count` рендерится из переменной: движок подставляет значения в
            -- метаданные шага ДО разбора, и «%invite_count%» станет числом.
            'repeat', JSON_OBJECT('count', '%invite_count%', 'max_iterations', 50),
            -- ⚠⚠ `invite_done` стоит и во входах, и в выходах — в этом весь цикл.
            -- Вход собирается заново на каждом повторе и несёт накопленное;
            -- выход кладёт назад дополненное.
            'inputs_map', JSON_OBJECT(
              'invite_done', 'invite_done',
              'invite_slots', 'invite_slots',
              'invite_angle', 'invite_angle',
              'invite_length', 'invite_length',
              'invite_avoid', 'invite_avoid',
              'invite_country', 'invite_country',
              'invite_time', 'invite_time',
              'datetime_current_get_zone', 'datetime_current_get_zone'),
            'outputs_map', JSON_OBJECT('invite_done', 'invite_done')))),
       (@wf, 4, 'Ответ панели', 1,
        JSON_OBJECT(
          'transitions_before', JSON_ARRAY(),
          'transitions_after', JSON_ARRAY(),
          'continue_workflow', false,
          -- ⚠ Вердикт здесь всегда `yes`: каждую реплику уже просудил ребёнок, и
          -- до накопления доходит только прошедшая. Конверт же панель ждёт —
          -- разбирает его один код на все занятия (`mail_agent._envelope`).
          'prompt_user', CONCAT('VERDICT: yes\n', 'WHY: \n', 'TEXT: %invite_done%')));

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов_обёртки,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @one) AS шагов_ребёнка,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.workflow_invoke.repeat.count'))
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0) AS повторов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.workflow_invoke.workflow_id'))
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 0) AS зовёт,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[0].step_id'))
          FROM `agent_workflow_step` WHERE `id` = @sjudge) AS судья_ведёт_к,
       @sdone AS шаг_накопления;
