-- Ветка разговора про письма и фотографии (2026-09-21)
--
-- ЗАЧЕМ. Чат на сайте знакомств служит знакомству, а дальше разговор уходит в
-- письма: собеседников занимают фотографии, а не погода и увлечения. Тему поднимает
-- любая сторона, и в этот момент обычный ответ — «поддержать беседу» — мимо: нужно
-- не поддержать, а **договориться**.
--
-- ⚠⚠ ОТДЕЛЬНАЯ ВЕТКА, А НЕ ПРАВКА ОБЩЕГО ПРОМПТА. Соблазн дописать в шаг генерации
-- «а если речь о фото, то соглашайся» велик и уже проверен на инвайтах: правило,
-- добавленное в конец длинного промпта, проигрывает шапке. Здесь у ветки своя
-- задача, свой судья и свой ответ — шаг получает одну работу и делает одну работу.
--
-- УСТРОЙСТВО. Два изменения, и оба в `dating_talk`:
--
--   1. Перед генерацией встаёт шаг **«Тема разговора»**: вся нужная выжимка уже
--      собрана (история, факты о ней, факты о нём, договорённости), и решить, куда
--      зашёл разговор, можно без единого лишнего похода к базе.
--
--   2. Если тема требует особого обращения — уходим в **subflow**. Всё прочее идёт
--      дальше как шло.
--
-- ⚠ ТЕМА — СТРОКА, А НЕ ФЛАГ. Их будет больше одной: встречи, деньги, контакты.
-- Флаг `is_photo` пришлось бы заводить заново под каждую, а строка расширяется
-- добавлением ветки и одной строки в перечень.
--
-- ⚠⚠ ПРО ОБЕЩАНИЕ ПРИСЛАТЬ ФОТО. Ветка соглашается в обе стороны — так решено. Но
-- отправки писем с вложением у панели **пока нет**: `mail_send` шлёт поля вложения
-- пустыми. Значит согласие «пришлю» сейчас исполняет человек руками; как появится
-- механизм, ветка не изменится — изменится то, кто уносит письмо.
--
-- Идемпотентность: subflow заводится по `INSERT ... SELECT WHERE NOT EXISTS`, шаги
-- родителя — проверкой на уже сделанное.

-- ── 1. Subflow: «Чат с девушкой (письма и фото)» ────────────────────────────

INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`,
                              `position`, `subflow`, `group_name`)
SELECT 2, 'dating_talk_about_photo', 'Чат с девушкой (письма и фото)',
       'Ветка разговора: договориться об обмене письмами с фотографиями',
       (SELECT COALESCE(MAX(w.`position`), 0) + 1 FROM `agent_workflow` w), 1, 'dating'
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow`) x
                    WHERE x.`name` = 'dating_talk_about_photo');

SET @wf_photo = (SELECT `id` FROM `agent_workflow`
                  WHERE `name` = 'dating_talk_about_photo');
SET @wf_talk = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

-- Шаг 0 subflow: сочиняем ответ про письма и фотографии.
--
-- ⚠ Промпт знает **оба направления** и просит модель различить их сама: кто кому
-- предлагает. Разбирать это отдельным шагом незачем — реплика перед глазами, и
-- лишний вызов стоил бы столько же, сколько сам ответ.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf_photo, 2, 'Ответ про письма и фото', 0, JSON_OBJECT(
    'prompt_user', CONCAT(
        '=== Текущее время ===\n%datetime_current_get%\n\n',
        '%if talk_history%=== Разговор с этим человеком ===\n%talk_history%\n\n%endif%',
        '=== %companion_title% пишет ===\n%prompt_user%\n\n',
        '=== Что нужно ===\n',
        'Разговор зашёл про письма и фотографии. Это не обычная болтовня: здесь ',
        'нужно **договориться**, а не поддержать беседу.\n\n',
        '⚠ Сперва пойми, о чём именно речь, и ответь по своему случаю:\n\n',
        '1. **Он предлагает прислать СВОИ фотографии.** Соглашайся охотно и скажи, ',
        'что ждёшь его письмо. Покажи интерес — ему важно, что его хотят увидеть.\n',
        '2. **Он просит ТВОИ фотографии.** Соглашайся и скажи, что пришлёшь письмом. ',
        'Не обещай конкретного часа: «сегодня вечером» превращается в упрёк, если ',
        'письмо придёт завтра.\n',
        '3. **Он зовёт перейти в письма** без упоминания фотографий. Соглашайся: в ',
        'письмах спокойнее и можно написать длиннее.\n',
        '4. **Он спрашивает, почему не отвечаешь письмом.** Скажи, что напишешь.\n\n',
        '⚠⚠ Чего делать нельзя:\n',
        '- не описывай, что именно на фотографиях, и не обещай ничего откровенного: ',
        'обещание, которого не выполнить, хуже отказа;\n',
        '- не проси денег, не упоминай оплату писем и не жалуйся на неё;\n',
        '- не давай почту, телефон и никаких контактов вне сайта;\n',
        '- не отказывайся и не уходи от темы: он спросил прямо, и уклончивость ',
        'читается как «нет».\n\n',
        '5. Одно-два предложения, до 25 слов, как в мессенджере.\n',
        '6. Тон тёплый и живой, без приторности.\n',
        '7. Отвечай строго на языке: %user_language%.\n',
        '8. ⚠ Пустую строку возвращать нельзя: на прямой вопрос нужен прямой ответ.\n\n',
        '=== Important information about final response ===\n',
        'Please return your response in JSON format. The JSON response must contain ',
        'follow keys: \n',
        '- "photo_response": твой ответ\n',
        '- "photo_deal": что решили — "his" (ждём его письмо), "mine" (обещали своё), ',
        '"both" (обменяемся), "mail" (просто уходим в письма)\n\n',
        'Example of JSON response:\n',
        '{\n  "photo_response": "of course, send them — i''m curious now",\n',
        '  "photo_deal": "his"\n}'),
    'transitions_after', JSON_ARRAY(),
    'transitions_before', JSON_ARRAY(),
    'llm_to_json_variable', JSON_ARRAY(
        JSON_OBJECT('variable', 'photo_response', 'text', 'ответ собеседнику'),
        JSON_OBJECT('variable', 'photo_deal',
                    'text', 'о чём договорились: his, mine, both, mail')))
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf_photo AND x.`position` = 0);

-- Шаг 1 subflow: судья.
--
-- ⚠ Свой, а не общий с обычной веткой: тот сторожит «нужен ли ответ вообще», а
-- здесь ответ нужен заведомо — проверять надо другое, обещания и запреты.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf_photo, 2, 'Проверка ответа про фото', 1, JSON_OBJECT(
    'prompt_user', CONCAT(
        '=== %companion_title% пишет ===\n%prompt_user%\n\n',
        '=== Черновик ответа ===\n%photo_response%\n\n',
        '=== Что нужно ===\n',
        'Ты редактор. Ответ здесь **обязателен** — человек спросил прямо, и молчание ',
        'или уклончивость читаются как отказ. Решать, отвечать ли, не требуется.\n\n',
        'Проверь черновик:\n',
        '- он на языке %user_language%;\n',
        '- он отвечает на то, что спросили, а не на что-то своё;\n',
        '- в нём есть согласие, а не увёртка;\n',
        '- в нём **нет** описания содержимого фотографий и обещаний чего-то ',
        'откровенного;\n',
        '- в нём **нет** просьбы денег, упоминания оплаты, почты, телефона и любых ',
        'контактов вне сайта;\n',
        '- в нём нет обещания точного часа отправки.\n\n',
        'Годится — верни photo_fixed: "" (пустую строку, править нечего).\n',
        'Не годится — напиши в photo_fixed свой вариант: одно-два предложения, до ',
        '25 слов, строго на языке %user_language%.\n\n',
        '=== Important information about final response ===\n',
        'Please return your response in JSON format. The JSON response must contain ',
        'follow keys: \n',
        '- "photo_fixed": исправленный ответ или пустая строка\n\n',
        'Example of JSON response:\n{\n  "photo_fixed": ""\n}'),
    'transitions_after', JSON_ARRAY(),
    'transitions_before', JSON_ARRAY(),
    'llm_to_json_variable', JSON_ARRAY(
        JSON_OBJECT('variable', 'photo_fixed',
                    'text', 'исправленный ответ; пусто — черновик годится')))
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf_photo AND x.`position` = 1);

-- Шаг 2 subflow: отдаём ответ наружу.
--
-- ⚠ Правка судьи имеет приоритет, но только когда она есть: пустая строка означает
-- «править было нечего», и подставлять её вместо ответа нельзя. Тот же приём, что у
-- судьи обычной ветки.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf_photo, 4, 'Ответ', 2, JSON_OBJECT(
    'prompt_user', '%if photo_fixed%%photo_fixed%%else%%photo_response%%endif%',
    'continue_workflow', FALSE,
    'transitions_after', JSON_ARRAY(),
    'transitions_before', JSON_ARRAY())
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) x
                    WHERE x.`workflow_id` = @wf_photo AND x.`position` = 2);

SELECT 'SUBFLOW' AS этап, @wf_photo AS номер,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf_photo)
       AS шагов;

-- ── 2. В `dating_talk`: шаг темы и развилка ─────────────────────────────────
--
-- ⚠ Шаг встаёт **перед генерацией ответа** (позиция 10) и после поиска фактов:
-- к этому месту собрано всё — история, выжимка, факты о ней, о нём и о прежних
-- договорённостях. Решить, куда зашёл разговор, можно без единого лишнего запроса.
--
-- ⚠⚠ Позиции ниже сдвигаются на единицу. Порядок шагов задаётся именно `position`,
-- и вставка «в середину» без сдвига поставила бы новый шаг в конец очереди — то
-- есть после ответа, которому он должен предшествовать.

SET @shift = (SELECT COUNT(*) FROM (SELECT * FROM `agent_workflow_step`) x
               WHERE x.`workflow_id` = @wf_talk AND x.`title` = 'Тема разговора');

UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf_talk AND `position` >= 10 AND @shift = 0;

-- ⚠ Второй сдвиг — под шаги самой ветки. После первого «Тишина» встала на 15, и
-- два свободных места подряд нужно освободить ниже неё.
UPDATE `agent_workflow_step`
   SET `position` = `position` + 1
 WHERE `workflow_id` = @wf_talk AND `position` >= 17 AND @shift = 0;

-- ⚠⚠ ШАГИ ВЕТКИ ВСТАЮТ СРАЗУ ЗА «ТИШИНОЙ», А НЕ В САМЫЙ КОНЕЦ, и это не
-- вкусовщина.
--
-- Движок идёт к следующему шагу **по порядку**, если ни один переход не сработал
-- (`current_index += 1`). Поставь мы ветку последней — поток, дошедший до «Влить
-- придуманные факты» с невыполненным условием, утёк бы прямо в неё: обычный
-- разговор получил бы ответ про фотографии.
--
-- Места 16 и 17 безопасны: до них естественным ходом не добраться. Стоящие выше
-- «Ответ» (14) и «Тишина» (15) несут `continue_workflow: false` и завершают поток,
-- а заведение фактов уезжает **ниже** — на 18 и 19, — и список кончается на нём,
-- как кончался до этой правки.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf_talk, 6, 'Ветка: письма и фото', 16, JSON_OBJECT(
    'workflow_invoke', JSON_OBJECT(
        'workflow_id', @wf_photo,
        -- ⚠ Отдаём ветке то же, чем располагает генерация: реплику, историю, кто
        -- пишет и на каком языке. Факты ей ни к чему — разговор идёт о деле, а не
        -- о биографии.
        'inputs_map', JSON_OBJECT(
            'prompt_user', 'prompt_user',
            'talk_history', 'talk_history',
            'companion_title', 'companion_title',
            'companion_name', 'companion_name',
            'girl_name', 'girl_name',
            'user_language', 'user_language',
            'datetime_current_get', 'datetime_current_get_45_result_str'),
        -- ⚠ Забираем **два** значения: сам ответ и то, о чём договорились. Второе
        -- пока никуда не идёт, но оно и есть ответ на вопрос «что мы ему обещали»,
        -- а спросят его тогда, когда письмо не уйдёт.
        'outputs_map', JSON_OBJECT(
            'photo_response', 'photo_response',
            'photo_deal', 'photo_deal')),
    'transitions_after', JSON_ARRAY(),
    'transitions_before', JSON_ARRAY())
 WHERE @shift = 0;

SET @step_invoke = (SELECT `id` FROM `agent_workflow_step`
                     WHERE `workflow_id` = @wf_talk
                       AND `title` = 'Ветка: письма и фото');

-- Отдача ответа ветки. ⚠ Своим шагом, а не общим с обычным «Ответом»: тот берёт
-- `%girl_response%`, которого в этой ветке нет вовсе.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf_talk, 4, 'Ответ ветки', 17, JSON_OBJECT(
    -- ⚠ Берём то, что вернул subflow своим шагом отдачи. `outputs_map` кладёт сюда
    -- же `photo_response`, но итог ветки — это её собственный ответ, уже с правкой
    -- судьи: у неё эти два значения могут расходиться.
    'prompt_user', CONCAT('%workflow_invoke_', @step_invoke, '_result_str%'),
    'continue_workflow', FALSE,
    'transitions_after', JSON_ARRAY(),
    'transitions_before', JSON_ARRAY())
 WHERE @shift = 0;

SET @step_answer = (SELECT `id` FROM `agent_workflow_step`
                     WHERE `workflow_id` = @wf_talk AND `title` = 'Ответ ветки');

-- Развилка: определяем тему и решаем, куда идти.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`,
                                   `metadata`)
SELECT @wf_talk, 2, 'Тема разговора', 10, JSON_OBJECT(
    'prompt_user', CONCAT(
        '=== Текущее время ===\n%datetime_current_get_45_result_str%\n\n',
        '%if talk_history%=== Разговор с этим человеком ===\n%talk_history%\n\n%endif%',
        '=== %companion_title% пишет ===\n%prompt_user%\n\n',
        '=== Что нужно ===\n',
        'Определи, о чём сейчас разговор. Смотри на **последнюю реплику** и на то, ',
        'к чему она относится в истории.\n\n',
        'Верни одно из значений:\n',
        '- "photo_mail" — речь о письмах или фотографиях: он предлагает прислать ',
        'свои, просит твои, зовёт перейти в письма или спрашивает, почему ты не ',
        'пишешь письмом;\n',
        '- "usual" — всё остальное: знакомство, расспросы, быт, флирт без ',
        'упоминания фотографий и писем.\n\n',
        '⚠ "photo_mail" ставится, только когда тема **поднята**, а не просто ',
        'возможна. Слово «фото» в рассказе о поездке темой не является; ',
        '«скинь фотку» — является.\n\n',
        '⚠ Сомневаешься — ставь "usual": обычная ветка отвечает на всё, а особая ',
        'заточена под одно.\n\n',
        '=== Important information about final response ===\n',
        'Please return your response in JSON format. The JSON response must contain ',
        'follow keys: \n',
        '- "talk_topic": "photo_mail" или "usual"\n\n',
        'Example of JSON response:\n{\n  "talk_topic": "usual"\n}'),
    -- ⚠⚠ Развилка: тема особая — уходим в ветку, минуя генерацию. Всё прочее идёт
    -- дальше как шло, и это главное свойство: обычный путь не тронут.
    'transitions_after', JSON_ARRAY(JSON_OBJECT(
        'variable', 'talk_topic', 'operator', '==', 'value', 'photo_mail',
        'step_id', CAST(@step_invoke AS CHAR))),
    'transitions_before', JSON_ARRAY(),
    'llm_to_json_variable', JSON_ARRAY(JSON_OBJECT(
        'variable', 'talk_topic',
        'text', 'тема разговора: photo_mail или usual')))
 WHERE @shift = 0;

-- ⚠ Из вызова ветки — сразу на её отдачу: иначе поток пошёл бы по позициям дальше
-- и попал бы в шаг заведения фактов, к этой ветке не относящийся.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
         JSON_OBJECT('variable', 'photo_deal', 'operator', '!=', 'value', '',
                     'step_id', CAST(@step_answer AS CHAR))))
 WHERE `id` = @step_invoke;

SELECT 'ПОСЛЕ' AS этап, @step_invoke AS шаг_ветки, @step_answer AS шаг_отдачи,
       (SELECT `id` FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf_talk AND `title` = 'Тема разговора') AS шаг_темы;

SELECT `position`, `id`, `type_id`, `title`
  FROM `agent_workflow_step` WHERE `workflow_id` = @wf_talk ORDER BY `position`;
