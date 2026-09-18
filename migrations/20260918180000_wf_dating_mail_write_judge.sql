-- `dating_mail_write`: судья на повтор и явное «вопроса не нужно» (2026-09-18)
--
-- ДВЕ ПРАВКИ ПО ЖИВОМУ ПРОГОНУ. Десять шаблонов, написанных сегодня новым
-- промптом, показали ровно две вещи, которых мы не предусмотрели.
--
-- 1. «БЕЗ ВОПРОСА» НЕ РАБОТАЕТ МОЛЧА.
--
-- Панель, бросив жребий «вопроса не нужно», убирала живые переменные из списка —
-- и только. Расчёт был такой: нет в списке — нечего ставить, а разрешение
-- («можешь не ставить») модель прочитала бы как приглашение.
--
-- Расчёт оказался неверным наполовину. Переменной в письме действительно нет, и
-- дорогой вызов LLM на каждого адресата не идёт — это сработало. Но вопрос модель
-- дописывает САМА, обычным текстом: «What's something small that made you smile
-- recently?» — в трёх письмах из пяти, где его не просили.
--
-- Молчания данными мало: нужна прямая строка. Отсюда `mail_question` — флаг, и
-- промпт ветвится по нему открыто.
--
-- 2. СПИСОК «ТАК УЖЕ БЫЛО» ДЕРЖИТ СЛАБО.
--
-- Шесть шаблонов из десяти несли один и тот же оборот — «I value authenticity /
-- genuine connection over grand gestures», — хотя прошлые тексты модели
-- показывались. У инвайтов от этого спасает СУДЬЯ: отдельный шаг, который бракует
-- повтор и отправляет черновик на второй круг. У рассылки его не было — цепочка
-- проверяла только форму: язык, метки, переменные.
--
-- ⚠ Судья встаёт ПОСЛЕДНИМ, после всех проверок формы. Смысл дороже формы только
-- тогда, когда форма уже верна: бракуй он первым — модель правила бы стиль в
-- тексте, где не хватает половины переменных.
--
-- ⚠ Судья пользуется УЖЕ СУЩЕСТВУЮЩЕЙ петлёй повтора: «Попытка» (1312) считает
-- заходы, «Что не так» (1313) собирает замечание и возвращает на черновик, пока
-- `write_try < 3`. Нового механизма не заводится — вторая петля разошлась бы с
-- первой на первой же правке.
--
-- Идемпотентность: промпты и правила переписываются целиком, шаг и переменные
-- заводятся по условию отсутствия.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @sdraft = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf AND `position` = 0);
SET @stry = (SELECT `id` FROM `agent_workflow_step`
              WHERE `workflow_id` = @wf AND `position` = 4);
SET @sdone = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `position` = 6);
SET @smarks = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf AND `position` = 7);

SELECT 'ДО' AS этап, @wf AS workflow, @sdraft AS черновик, @stry AS попытка,
       @sdone AS готово, @smarks AS метки,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов;

-- ---------------------------------------------------------------- Переменные
INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'mail_question', 'workflow',
       'Непусто — письмо кончается вопросом к получателю. Жребий бросает DatingAi'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_question');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'letter_same', 'workflow',
       'Вердикт судьи о повторе: yes — слишком похоже на прошлые, no — годится'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'letter_same');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `description`)
SELECT 'letter_same_why', 'workflow',
       'Чем именно письмо повторяет прошлые: оборот, образ, зачин'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'letter_same_why');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_question', 'letter_same', 'letter_same_why')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ------------------------------------------- Черновик: явная строка про вопрос
--
-- ⚠ Правится ТОЧЕЧНО, заменой одного места, а не переписыванием промпта целиком:
-- в нём живут секции приёма, длины, рассказа и списка «так уже было», заведённые
-- соседней миграцией. Перепиши мы его здесь, порядок применения решал бы, чей
-- текст останется.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 'Ещё:\n- обращайся к получателю, а не к себе;',
                 CONCAT(
                   '%if mail_question%ВОПРОС: письмо кончается одним вопросом к ',
                   'нему. Не тремя: три вопроса это анкета, а не письмо.\n\n',
                   '%else%⚠ ВОПРОСА НЕ НУЖНО — ни переменной, ни своими словами. ',
                   'Не «what do you enjoy?», не «what made you smile today?», не ',
                   'вопрос в конце и не вопрос в середине. Закончи утверждением, ',
                   'признанием или рассказом: на такое отвечают не хуже, а ',
                   'человеку, которому пишут первыми, допрос ни к чему.\n\n%endif%',
                   'Ещё:\n- обращайся к получателю, а не к себе;')))
 WHERE `workflow_id` = @wf AND `position` = 0;

-- ------------------------------------------- Судья на повтор
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 2, 'Судья: не повтор ли?', 8,
       JSON_OBJECT(
         'transitions_before', JSON_ARRAY(),
         'transitions_after', JSON_ARRAY(),
         'llm_to_json_variable', JSON_ARRAY(
           JSON_OBJECT('variable', 'letter_same',
                       'text', 'yes — повторяет прошлые, no — годится'),
           JSON_OBJECT('variable', 'letter_same_why',
                       'text', 'Чем повторяет, одной фразой. Пусто, если годится')),
         'prompt_user',
         CONCAT(
           'Ты — редактор. Перед тобой новый шаблон письма для рассылки и те, ',
           'что писали этому сайту раньше. Ответь на один вопрос: не повтор ли ',
           'это?\n\n',
           '=== Новый текст ===\n%letter%\n\n',
           '%if mail_avoid%=== Так уже писали раньше ===\n%mail_avoid%\n\n%endif%',
           'Считай повтором (yes), если верно ХОТЬ ОДНО:\n',
           '1. Тот же зачин: письмо начинается той же мыслью или почти теми же ',
           'словами, что одно из прошлых.\n',
           '2. Тот же образ: та же картинка (тёплый напиток и плед, дождь за ',
           'окном, «просматривала анкеты, и твоя зацепила»), тот же ход мысли.\n',
           '3. Те же дежурные обороты о себе: «я ценю искренность», «настоящая ',
           'связь важнее громких жестов», «я за простые честные разговоры». Такие ',
           'фразы не говорят о человеке ничего и лезут в каждое письмо.\n',
           '4. Тот же приём на том же месте: письмо отличается от прошлого только ',
           'подставленными словами.\n\n',
           '⚠ Разное настроение при одном приёме — это НЕ повтор. Два письма ',
           'могут оба быть про выходные и остаться разными: важно, узнает ли ',
           'человек, получивший оба, одну и ту же заготовку.\n\n',
           '⚠ Если прошлых текстов выше не показано — отвечай no: сравнивать не ',
           'с чем, и придираться не с чего.\n\n',
           'Верни строго JSON с ключами:\n',
           '- "letter_same": "yes" или "no"\n',
           '- "letter_same_why": чем повторяет, одной фразой по-русски; пустая ',
           'строка, если годится\n\n',
           'Пример ответа:\n',
           '{"letter_same": "yes", "letter_same_why": "тот же оборот «я ценю ',
           'искренность больше громких жестов», что в шаблоне №3"}'
         ))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 8);

SET @sjudge = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf AND `position` = 8);

-- ------------------------------------------- Переходы судьи
--
-- Повтор — в петлю правки, годится — в ответ.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after',
         JSON_ARRAY(
           JSON_OBJECT('variable', 'letter_same', 'operator', '==',
                       'value', 'yes', 'step_id', CAST(@stry AS CHAR)),
           JSON_OBJECT('variable', 'letter_same', 'operator', '!=',
                       'value', 'yes', 'step_id', CAST(@sdone AS CHAR))))
 WHERE `id` = @sjudge;

-- ------------------------------------------- Проверка меток ведёт к судье
--
-- ⚠ Прежде «метки на месте» означало «готово». Теперь между ними стоит судья:
-- форма верна — спрашиваем про смысл.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after',
         JSON_ARRAY(
           JSON_OBJECT('variable', 'letter_marks_missing', 'operator', '!=',
                       'value', '', 'step_id', CAST(@stry AS CHAR)),
           JSON_OBJECT('variable', 'letter_marks_missing', 'operator', 'empty',
                       'value', '', 'step_id', CAST(@sjudge AS CHAR))))
 WHERE `id` = @smarks;

-- ------------------------------------------- Замечание судьи уезжает в правку
--
-- ⚠ Строка дописывается в ТУ ЖЕ переменную `write_hint`, которой пользуются
-- проверки формы: петля повтора одна на всех, и второй её вид означал бы, что
-- черновик возвращается на правку двумя разными путями.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(
         `metadata`, '$.variable_conversion[1].text',
         CONCAT(
           '%if !letter_vars_qty%в письме нет ни одной переменной [[имя]] — имена ',
           'написаны словами. %endif%',
           '%if !letter_lang_ok%письмо написано не на языке %user_language%. %endif%',
           '%if letter_vars_extra%таких переменных нет в списке: %letter_vars_extra% ',
           '— убери их или замени разрешёнными. %endif%',
           '%if letter_marks_inline%переменные %letter_marks_inline% встроены в ',
           'фразу — поставь каждую отдельным абзацем: их значение это целый вопрос. ',
           '%endif%',
           '%if letter_marks_missing%в письме нет переменных: %letter_marks_missing% ',
           '— их надо вставить как [[имя]], а не писать словами. Вопрос получателю ',
           'не сочиняй сам: на его месте ставится переменная. %endif%',
           '%if letter_same_why%это повтор прошлых писем: %letter_same_why% Напиши ',
           'ИНАЧЕ: другой зачин, другой образ, другие слова. Те люди уже получили ',
           'прежний текст. %endif%'))
 WHERE `workflow_id` = @wf AND `position` = 5;

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       @sjudge AS шаг_судьи,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[1].step_id'))
          FROM `agent_workflow_step` WHERE `id` = @smarks) AS метки_ведут_к,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[0].step_id'))
          FROM `agent_workflow_step` WHERE `id` = @sjudge) AS повтор_ведёт_к,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.transitions_after[1].step_id'))
          FROM `agent_workflow_step` WHERE `id` = @sjudge) AS годится_ведёт_к,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%ВОПРОСА НЕ НУЖНО%'
          FROM `agent_workflow_step` WHERE `id` = @sdraft) AS запрет_вопроса,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.variable_conversion[1].text'))
               LIKE '%letter_same_why%'
          FROM `agent_workflow_step` WHERE `workflow_id` = @wf AND `position` = 5) AS замечание_судьи;
