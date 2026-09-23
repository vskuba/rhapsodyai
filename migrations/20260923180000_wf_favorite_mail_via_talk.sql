-- Письма избранным пишет агент чата: свой промпт, общий workflow (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: письмо уходило тому, кого «не знают»
--
-- Избранный — это человек, **с которым уже говорили**: звёздочку ставят тому, кто
-- отвечал. У пары есть переписка в чате, бывает и в письмах.
--
-- А письмо ему сочинял `dating_favorite_mail_write` (#71), который не знает о нём
-- ничего: ни имени, ни разговора, ни фактов. Промпт там прямо запрещал ссылаться
-- на прошлое — «переписки перед тобой нет, и ты не знаешь о ней НИЧЕГО».
--
-- Живому человеку это читается ровно так, как есть: женщина, с которой он
-- переписывался, пишет ему как незнакомому.
--
-- ## Что делаем
--
-- Письма идут через **тот же workflow, что и чат** (`dating_talk`, #5): он ищет
-- факты о девушке, о собеседнике и о переписке, видит историю и отвечает по ней.
--
-- Отличие — **в агенте**: у `fav_mail_ladadate` (#236) свой системный промпт, и
-- он про письма, а не про реплики. Ради этого отдельный агент и заведён: одна
-- работа, разные голоса.
--
-- ⚠⚠ **Системный промпт сильнее шагового** — это знание куплено дорого
-- (`testing_llm.md`, случай с фотографиями). Поэтому длину и тон письма задаёт
-- он, а шаг только не мешает: ветка `%if mail_mode%` снимает требование «до 20
-- слов, как в мессенджере», которое иначе спорило бы с ним.
--
-- ## ⚠⚠ Цена: вызовов становится больше в полтора десятка раз
--
-- Было: **один** вызов на заход — агент присылал шаблон, панель раскладывала его
-- по парам подстановкой имени. Десять писем стоили одного вызова.
--
-- Стало: вызов **на каждое письмо**, и каждый дороже — `dating_talk` делает до
-- четырёх обращений к модели (анализ, тема, сочинение, проверка) плюс подпрогоны
-- фактов. Десять писем за заход — сорок-шестьдесят вызовов вместо двух-трёх.
--
-- Это осознанный размен: персональное письмо нельзя написать, не прочитав
-- переписку, а прочитать её можно только для конкретной пары.
--
-- ⚠ Заход идёт раз в 600 секунд по десять писем — то есть около вызова в минуту.
-- Модель общая с чатом, и очередь агента одна (`llm_parallel_per_agent_max` = 1):
-- письма встают в неё по одному, не мешая чату (у него свой агент).
--
-- Идемпотентность: промпты правятся только там, где ветки ещё нет; переменная
-- заводится проверкой.

SET @talk = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап, @talk AS workflow_чата,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `name` = 'mail_mode')
         AS переменная_есть,
       (SELECT COUNT(*) FROM `agent` WHERE `name` LIKE 'fav\_mail\_%'
         AND `workflow_id` = @talk) AS агентов_на_чате;

-- ── 1. Признак «пишем письмо» ───────────────────────────────────────────────
--
-- ⚠ Отдельная переменная, а не `make_initiative`: у той свой смысл — «собеседник
-- молчит, пишем первыми репликой в чат». Письмо и реплика расходятся длиной,
-- тоном и тем, чем кончаются; одна переменная на оба случая заставила бы промпт
-- угадывать, о чём речь.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_mode', 'input', '',
       'Пишем ПИСЬМО, а не реплику в чат: абзац и больше, серьёзнее по тону. Пусто — обычный чат. Кладёт DatingAi при наборе пула писем избранным'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_mode');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @talk FROM `agent_workflow_variable` v
 WHERE v.`name` = 'mail_mode'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @talk);

-- ── 2. Шаг 12 «Генерация ответа»: ветка письма ──────────────────────────────
--
-- Ставится ПЕРВОЙ развилкой, до `make_initiative`: письмо тоже пишется первым
-- после паузы, и попади оно в ту ветку — получило бы «до 25 слов, как в
-- мессенджере».
--
-- ⚠ Вложенность тройная, и это законно: `ai_workflow_if_blocks_render`
-- разворачивает блоки изнутри наружу повторными проходами.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         '%if make_initiative%=== Что нужно ===',
         CONCAT(
           '%if mail_mode%=== Что нужно ===\n',
           '⚠⚠ ЭТО ПИСЬМО, а не реплика в чат. Ты пишешь письмо человеку, с которым ',
           'уже общалась: переписка выше — ваша, и он её помнит.\n\n',
           '⚠ Отвечать не на что: последним в разговоре было твоё слово, он молчит. ',
           'Это письмо «вспомнила о тебе», а не ответ.\n\n',
           '1. ⚠⚠ ДЛИНА: от одного абзаца до трёх. Письмо в две строки выглядит ',
           'отпиской — человек открыл почту, а там реплика из чата.\n',
           '2. Опирайся на то, о чём вы говорили: назови то, что он рассказывал, ',
           'спроси, чем кончилось. Это и отличает письмо избранному от рассылки ',
           'незнакомому.\n',
           '3. ⚠ Не пересказывай переписку целиком и не цитируй её дословно: ',
           'достаточно одной живой подробности, которую он узнает.\n',
           '4. Тон серьёзнее, чем в чате: письмо читают внимательнее и дольше. ',
           'Шутка и флирт уместны, но письмо держится на чём-то, кроме них.\n',
           '5. Ни слова упрёка за молчание: «ты пропал», «почему не отвечаешь», ',
           '«я ждала» — это претензия, и она закрывает разговор надёжнее паузы.\n',
           '6. Абзацы разделяй пустой строкой. Без темы письма, без подписи, без ',
           'обращения «Дорогой».\n',
           '7. Отвечай строго на языке: %user_language%.\n',
           '8. ⚠ Пустую строку возвращать НЕЛЬЗЯ: заход набора потратится впустую.\n\n',
           '=== Important information about final response ===\n',
           'Please return your response in JSON format. The JSON response must contain follow keys: \n',
           '- "girl_response": текст письма\n\n',
           'Example of JSON response:\n',
           '{\n',
           '  "girl_response": "Вспоминала сегодня, как ты рассказывал про свой мотоцикл — у нас всю неделю дожди, и я представила, каково тебе сейчас без дороги.\\n\\nУ меня тут своё маленькое приключение: взялась печь хлеб и забыла про него в духовке. Дом до сих пор пахнет углями.\\n\\nКак твои дела?"\n',
           '}\n',
           '%else%%if make_initiative%=== Что нужно ===')))
 WHERE `workflow_id` = @talk AND `position` = 12
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%ЭТО ПИСЬМО, а не реплика%';

-- ⚠⚠ Закрывающий `%endif%` дописывается ОТДЕЛЬНЫМ запросом, и условие у него
-- **счётное**, а не текстовое: сравниваем число `%if ` и `%endif%` в промпте.
--
-- Первая попытка искала подстроку `LIKE '%%endif%%endif%'` и провалилась молча:
-- в `LIKE` последовательность `%%` — это два джокера подряд, а не литеральный
-- процент, так что шаблон совпал с любым промптом, где `%endif%` есть. UPDATE не
-- выполнился, блок остался незакрытым, и проверка на баланс это поймала.
--
-- ⚠ Внутрь `REPLACE` закрытие не поставить: он заменяет ОДНУ вставку в середине
-- текста, а закрыть надо весь промпт целиком, в конце.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', CONCAT(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '%endif%'))
 WHERE `workflow_id` = @talk AND `position` = 12
   AND (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
        - CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                              '%if ', ''))) / 4
     > (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
        - CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                              '%endif%', ''))) / 7;

-- ── 3. Шаг 13 «Валидация ответа»: письмо не сокращаем и не пропускаем ──────
--
-- ⚠⚠ Без этого редактор губит письмо дважды: правит его «до 20 слов» и вправе
-- поставить `girl_response_skip = 1` — «реальная девушка не отвечает на каждое
-- сообщение». Для письма, которое мы сами решили написать, молчание означает
-- потраченный впустую заход набора.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         '=== Что нужно ===\n%if answer_anyway%',
         CONCAT(
           '=== Что нужно ===\n',
           '%if mail_mode%Ты строгий редактор. Перед тобой ПИСЬМО, а не реплика в чат.\n\n',
           'Проверь черновик:\n',
           '- он написан на языке %user_language%;\n',
           '- в нём от одного абзаца до трёх, а не две строки;\n',
           '- он опирается на переписку выше, а не написан в пустоту;\n',
           '- в нём нет упрёка за молчание и нет выдуманных общих воспоминаний;\n',
           '- в нём нет темы письма, подписи и обращения «Дорогой».\n\n',
           '⚠⚠ girl_response_skip всегда 0: письмо мы решили написать сами, и ',
           'молчание тратит заход набора впустую. Годится — girl_response_fixed: "" ',
           '(пустая строка, править нечего). Не годится — напиши в ',
           'girl_response_fixed своё письмо, от абзаца до трёх, на языке ',
           '%user_language%.\n',
           '%else%%if answer_anyway%')))
 WHERE `workflow_id` = @talk AND `position` = 13
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%Перед тобой ПИСЬМО%';

-- ── 4. Агент писем: тот же workflow, свой голос ────────────────────────────
--
-- ⚠⚠ **Промпт почти тот же, что у девушки чата, и это намеренно.** Она та же
-- самая женщина: те же запреты на встречи, звонки и контакты, тот же приземлённый
-- тон, та же Украина. Разойдись голоса — человек, читающий и чат, и письма,
-- увидел бы двух разных собеседниц.
--
-- Отличие ровно в одном: **это письмо**. Отсюда длина, отсутствие «ответь коротко,
-- как в мессенджере» и прямая цель — написать письмо, а не отреагировать.
UPDATE `agent`
   SET `workflow_id` = @talk,
       `prompt_system` = CONCAT(
         'You are a girl %girl_name%. You are writing a LETTER, not a chat message.\n',
         'You never agree to personal meetings or calls.\n',
         'You never suggest meeting up or going somewhere together.\n',
         'You love to flirt, but a letter holds together on something more than flirting.\n',
         'If questions arise about meetings, calls, video or other personal information, you gently joke or change the subject. ',
         'Do not send any addresses, phones, social contacts for dating. You don’t promise anything specific about meeting. ',
         'But at the same time, you know you’re looking for love, a relationship, and you try to get to know each other better through messaging.\n',
         'You’re a modern down-to-earth girl: you write about real life—work, daily routine, cafes, series, sports, trips, plans. ',
         'Don’t go into poetry, lofty metaphors, or old-fashioned romance (poems, lace, silk, vintage perfumes) unless the interlocutor asks about it themselves.\n',
         'You live in Ukraine; music, books, cities, science—everything is Ukrainian. No mentions of Russia or anything related to Russia.\n',
         '⚠ A LETTER is one to three paragraphs, separated by a blank line. Never one or two sentences: that is a chat reply, and it looks like brushing him off. ',
         'No subject line, no signature, no “Dear”.\n',
         '⚠ The tone is warmer and more thoughtful than in chat — a letter is read slowly. Jokes and flirting belong there too, but they are not what holds it together.\n',
         '⚠ You are writing to someone you have already talked to. Lean on what he told you; do not write as if you were strangers.')
 WHERE `name` LIKE 'fav\_mail\_%';

-- Закрытие для шага 13 — тем же счётным условием.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', CONCAT(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '%endif%'))
 WHERE `workflow_id` = @talk AND `position` = 13
   AND (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
        - CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                              '%if ', ''))) / 4
     > (CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
        - CHAR_LENGTH(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                              '%endif%', ''))) / 7;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
         WHERE v.`name` = 'mail_mode' AND vw.`workflow_id` = @talk) AS переменная_у_чата,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%ЭТО ПИСЬМО, а не реплика%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 12) AS ветка_у_сочинения,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%Перед тобой ПИСЬМО%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @talk AND `position` = 13) AS ветка_у_редактора,
       (SELECT COUNT(*) FROM `agent` WHERE `name` LIKE 'fav\_mail\_%'
         AND `workflow_id` = @talk) AS агентов_на_чате,
       (SELECT LENGTH(`prompt_system`) FROM `agent`
         WHERE `name` = 'fav_mail_ladadate') AS длина_промпта;
