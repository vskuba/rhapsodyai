-- `dating_mail_write`: разнообразие шаблона рассылки задаётся снаружи (2026-09-18)
--
-- ТРЕТИЙ РАЗ ОДИН И ТОТ ЖЕ ВЫВОД, и теперь он применён ко всем трём занятиям.
-- Инвайты: «будь разной» дало три шаблона из трёх с «you're trouble». Письма
-- избранным: то же самое, лечится жребием снаружи. Здесь — рассылка, и цена
-- ошибки выше всего: шаблон живёт СУТКАМИ, уходит сотням людей, а круг пишет по
-- три штуки в день. Три похожих текста в сутки и есть «рассылка робота».
--
-- ЧТО ПРИХОДИТ ОТ ПАНЕЛИ:
--
--   `mail_angle`    приём: знакомство, наблюдение о нём, признание, провокация,
--                   игра, честность про сайт, любопытство, настроение дня;
--   `mail_length`   от одного абзаца до трёх, по 40–60 слов. ⚠ Прежде в промпте
--                   стояло «до четырёх абзацев» — это ПОТОЛОК, а не вилка, и
--                   модель писала четыре каждый раз;
--   `mail_story`    о чём девушке рассказать про себя. Пусто — рассказа нет;
--   `mail_avoid`    десяток прошлых шаблонов этого сайта, со словами «так уже
--                   было».
--
-- ⚠⚠ РАССКАЗ О СЕБЕ ОБЯЗАН ПОДХОДИТЬ ЛЮБОЙ АНКЕТЕ — вот чем рассылка отличается
-- от письма избранному. Там пишет конкретная девушка, здесь одним текстом пишут
-- все сорок. «После репетиции» годится одной, «варила кофе и смотрела в окно» —
-- каждой. Правило «никакой конкретики» в промпте было и раньше; теперь оно
-- распространено и на рассказ, иначе новая секция его бы и нарушила первой.
--
-- ⚠ ВОПРОС ТЕПЕРЬ НЕ ВСЕГДА, и выключает его панель — молча, самими данными.
-- Вопрос приходит живой переменной `question_to_companion`; выпал «без вопроса» —
-- панель убирает живые переменные из `%mail_vars%` и из обязательных, и ставить
-- становится нечего. Отдельного флага в промпте нет намеренно: «можно не
-- ставить» модель читает как приглашение поставить.
--
-- Идемпотентность: промпт переписывается целиком, переменные заводятся по условию
-- отсутствия.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_angle%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS правка_есть,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;

-- ---------------------------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'mail_angle', 'workflow',
       'Приём для шаблона рассылки: знакомство, наблюдение, признание, игра. Жребий бросает DatingAi'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_angle');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'mail_length', 'workflow',
       'Какой длины просить письмо рассылки: от одного абзаца до трёх. Жребий бросает DatingAi'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_length');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'mail_story', 'workflow',
       'О чём девушке рассказать про себя. Пусто — рассказа в этот раз нет'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_story');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'mail_avoid', 'workflow',
       'Что уже писали этому сайту: десяток прошлых шаблонов, чтобы не повторяться'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_avoid');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_angle', 'mail_length', 'mail_story', 'mail_avoid')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- Промпт
--
-- ⚠ `%if write_hint%` остаётся первым: это замечание с повторного круга, и оно
-- должно стоять раньше всего остального, иначе модель дочитает до него, уже
-- решив, что пишет.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         CONCAT(
           '%if write_hint%НЕ ГОДИТСЯ: %write_hint%\nПерепиши, устранив это.\n\n%endif%',
           'Напиши ШАБЛОН первого письма от девушки мужчине на сайте знакомств.\n\n',
           '⚠ Это заготовка для рассылки: одним и тем же текстом напишут разные ',
           'девушки разным мужчинам. Ты не знаешь, кто именно, — и знать не ',
           'должен.\n\n',
           'Переменные (вставляй как [[имя]]):\n%mail_vars%\n\n',
           'Пожелание: %mail_hint%\n\n',
           '=== Приём на этот раз ===\n%mail_angle%\n\n',
           '=== Длина на этот раз ===\n%mail_length%\n\n',
           '%if mail_story%=== Расскажи о себе — вот про это ===\n%mail_story%\n\n%endif%',
           '%if mail_avoid%=== Так ты уже писала — не повторяйся ===\n',
           '%mail_avoid%\n\n%endif%',
           'Обязательно:\n',
           '- язык письма И НАЗВАНИЯ: %user_language%;\n',
           '- НИКАКОЙ конкретики: ни имён, ни городов, ни профессий, ни возраста. ',
           'Всё это подставится переменными. Придумаешь «Diana из Kyiv» — шаблон ',
           'станет годен одной анкете из сорока;\n',
           '- переменная, чья подпись говорит про вопрос (question_to_companion), ',
           'ставится ОТДЕЛЬНЫМ абзацем: её значение — целый вопрос, и внутри фразы ',
           'выйдет «What are What do you enjoy??».\n\n',
           'ПРИЁМ И ДЛИНА заданы выше — держись их. Это не пожелание: заготовок ',
           'пишется по три в сутки, и если каждая выходит одинаковым заходом ',
           'одинаковой длины, человек видит рассылку робота, а не живую девушку. ',
           'Если выше показано, что ты уже писала, — напиши ИНАЧЕ: другой образ, ',
           'другие слова, другое начало.\n\n',
           '%if mail_story%РАССКАЗ О СЕБЕ ОБЯЗАТЕЛЕН, и тема названа выше. Но ⚠ он ',
           'обязан подходить ЛЮБОЙ девушке: этим письмом напишут сорок разных ',
           'анкет. «После репетиции», «в моей лаборатории», «у нас в Киеве» — ',
           'брак; «варила кофе и смотрела в окно», «весь вечер не могла найти ',
           'ключи» — годится каждой. Рассказывай бытовыми подробностями, а не ',
           'общими словами: мелочь, которую не выдумывают, стоит десяти красивых ',
           'фраз.\n\n%endif%',
           'Ещё:\n',
           '- обращайся к получателю, а не к себе;\n',
           '- живо и просто, без признаний в любви;\n',
           '- о себе — общими словами, которые подойдут любой: не «я хореограф», ',
           'а «я люблю своё дело».\n\n',
           'НАЗВАНИЕ (title): 2–4 слова о том, ЧЕМ это письмо отличается от других ',
           '— тон, приём, о чём спрашивает. «Short and direct», «Curious about his ',
           'hobbies», «Warm and playful». НЕ «Letter 1», не «Template», не первые ',
           'слова письма, никаких [[переменных]] в названии.\n\n',
           'Верни JSON: {"letter": "текст письма", "letter_title": "название"}'
         ))
 WHERE `workflow_id` = @wf AND `position` = 0;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_angle%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS приём,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_story%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS рассказ,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%mail_avoid%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS список,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%до четырёх абзацев%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS потолок_остался,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;
