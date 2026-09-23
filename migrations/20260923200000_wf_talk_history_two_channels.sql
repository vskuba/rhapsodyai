-- Две истории общения: чат и письма (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: с человеком говорят двумя каналами, а агент видел один
--
-- У пары «девушка — собеседник» два разговора: реплики в чате и переписка
-- письмами. Это разные ленты — разной длины, разного тона, часто разных дней.
--
-- Агент же получал одну переменную `talk_history`, и в неё клали **только чат**.
-- Отсюда две беды разом:
--
-- * ответ на письмо писался, не помня вчерашнего разговора в чате;
-- * письмо избранному — тоже: `fav_mail_*` видел чат, но не видел собственных
--   прежних писем этому человеку.
--
-- Теперь переменных две: `talk_history_chat` и `talk_history_mail`, и панель
-- отдаёт **обе и всегда** — отношения одни, каналов два.
--
-- ## Что делает миграция
--
-- 1. `talk_history` → `talk_history_chat` (переменная и все упоминания в шагах);
-- 2. заводит `talk_history_mail` и привязывает к `dating_talk`;
-- 3. показывает переписку письмами там же, где показан чат;
-- 4. даёт агенту ответов (`mail_reply_*`) свой системный промпт;
-- 5. убирает осиротевший `dating_favorite_mail_write`.
--
-- ## ⚠ Почему всё по именам, а не по номерам
--
-- Прод и рабочая база разошлись: у сабворкфлоу фотографий номер 74 там и 2044
-- здесь, а шаг «Валидация ответа» получил историю только на проде (правка
-- сегодняшнего дня). Миграция по номерам починила бы одну базу и промахнулась
-- мимо другой.
--
-- Идемпотентность: каждый шаг проверяет, не сделан ли он уже.

-- ── 1. Переменная чата получает своё имя ────────────────────────────────────
--
-- ⚠ Порядок важен: сперва переименовываем **в шагах**, потом саму переменную.
-- Наоборот — и проверка «уже переименовано?» перестала бы отличать одно от
-- другого.
--
-- ⚠⚠ Заменяем `%talk_history%` и `"talk_history"` целиком, с обрамлением. Без
-- него замена поймала бы и уже переименованное: `talk_history_chat` начинается с
-- `talk_history`, и второй заход превратил бы его в `talk_history_chat_chat`.
UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(`metadata`, '%talk_history%', '%talk_history_chat%')
 WHERE `metadata` LIKE '%\%talk\_history\%%';

-- ⚠⚠ **И условие тоже.** `%if talk_history%` не содержит `%talk_history%`: перед
-- именем стоит `%if `, а не `%`. Замена выше его не трогает, и первый прогон
-- оставил условие ссылаться на переменную, которой больше нет, — то есть блок
-- истории чата исчез бы из промпта целиком, молча.
--
-- Поймано репетицией на копии прод-базы: в шаге «Генерация ответа» осталось
-- `%if talk_history%` при уже переименованном `%talk_history_chat%` внутри.
UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(`metadata`, '%if talk_history%', '%if talk_history_chat%')
 WHERE `metadata` LIKE '%\%if talk\_history\%%';

UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(`metadata`, '"talk_history"', '"talk_history_chat"')
 WHERE `metadata` LIKE '%"talk\_history"%';

UPDATE `agent_workflow_variable`
   SET `name` = 'talk_history_chat',
       `description` = 'Реплики чата с этим человеком, старые сверху. Кладёт панель'
 WHERE `name` = 'talk_history';

-- ── 2. Переменная писем ─────────────────────────────────────────────────────
-- ⚠ Умолчание — **пустая строка, а не NULL**, как у переменной чата: обе
-- объявлены `input`, а такие проверяются на присутствие (`workflow.md`, §3).
-- Разные умолчания у двух половин одного занятия — расхождение, которое ждёт
-- своего часа.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'talk_history_mail', 'input', '',
       'Переписка письмами с этим человеком, старые сверху. Кладёт панель'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'talk_history_mail');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, w.`id`
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow` w ON w.`name` = 'dating_talk'
 WHERE v.`name` = 'talk_history_mail'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = w.`id`);

-- ── 3. Переписка письмами — в промпт, рядом с чатом ─────────────────────────
--
-- ⚠ Отдельным блоком под своим заголовком, а не подмешиванием в ленту чата:
-- предел у каналов разный (чат идёт десятками коротких реплик, письма —
-- единицами длинных), и общая лента вытолкнула бы письма целиком. Вдобавок
-- ответ на письмо пишут не так, как реплику в мессенджер, и агент должен
-- видеть, что на что похоже.
-- ⚠⚠ Цепляемся за **конец блока чата**, а не за то, что идёт следом. Первая
-- версия искала `%endif%=== %companion_title% пишет ===` — и промахнулась мимо
-- главного шага «Генерация ответа»: там за историей чата идёт не «он пишет», а
-- блок сессии. Ошибку показала репетиция.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         '%talk_history_chat%\n\n%endif%',
         CONCAT('%talk_history_chat%\n\n%endif%',
                '%if talk_history_mail%=== Переписка письмами с этим человеком ',
                '(время в квадратных скобках; «она» — ты) ===\n',
                '%talk_history_mail%\n\n%endif%')))
 -- ⚠ `JSON_VALID` обязателен: у пяти шагов прода `metadata` пуста либо не JSON,
 -- и `JSON_EXTRACT` на такой падает целиком — миграция не доходит до конца.
 -- Поймано репетицией на копии прод-базы.
 WHERE `metadata` IS NOT NULL AND `metadata` <> '' AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`, '$.prompt_user') IS NOT NULL
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       LIKE '%\%talk\_history\_chat\%%'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%talk\_history\_mail%';

-- ⚠ Сабворкфлоу фотографий зовётся шагом и получает переменные `inputs_map`-ом:
-- переименование само по себе его не чинит, ключ надо назвать и там.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`,
         '$.workflow_invoke.inputs_map.talk_history_mail', 'talk_history_mail')
 WHERE `metadata` IS NOT NULL AND `metadata` <> '' AND JSON_VALID(`metadata`)
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map.talk_history_chat')
       IS NOT NULL
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map.talk_history_mail')
       IS NULL;

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, w.`id`
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow` w ON w.`name` = 'dating_talk_about_photo'
 WHERE v.`name` = 'talk_history_mail'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` x
                    WHERE x.`variable_id` = v.`id` AND x.`workflow_id` = w.`id`);

-- ── 4. Системный промпт агента ответов ──────────────────────────────────────
--
-- ## ⚠⚠ Почему у него свой промпт, а workflow общий
--
-- Занятий на `dating_talk` теперь три, и различает их **только** системный
-- промпт:
--
-- | агент | что делает |
-- |-------|------------|
-- | `dating_girl_universal` | реплики в чате |
-- | `fav_mail_*` | пишет письмо первой: разговор затих |
-- | `mail_reply_*` | **отвечает** на пришедшее письмо |
--
-- Третий и заводится этой миграцией. Прежде он ходил своим workflow
-- (`dating_mail_reply`), который переписку письмами получал отдельным запросом,
-- а чата не видел вовсе.
--
-- ⚠ Правила про встречи, звонки и видео — те же, что у остальных: они про
-- безопасность работы, а не про канал, и расходиться им нельзя.
UPDATE `agent`
   SET `prompt_system` = CONCAT(
'You are a girl %girl_name%. You are answering a LETTER he wrote to you.\n',
'You never agree to personal meetings or calls.\n',
'You never suggest meeting up or going somewhere together.\n',
'You love to flirt, but a letter holds together on something more than flirting.\n',
'If questions arise about meetings, calls, video or other personal information, ',
'you gently joke or change the subject. Do not send any addresses, phones, ',
'social contacts for dating. You don''t promise anything specific about meeting. ',
'But at the same time, you know you''re looking for love, a relationship, and ',
'you try to get to know each other better through messaging.\n',
'You''re a modern down-to-earth girl: you write about real life—work, daily ',
'routine, cafes, series, sports, trips, plans. Don''t go into poetry, lofty ',
'metaphors, or old-fashioned romance (poems, lace, silk, vintage perfumes) ',
'unless the interlocutor asks about it themselves.\n',
'⚠ A LETTER free form, but no more than three paragraphs.\n',
'⚠ The tone is warmer and more thoughtful than in chat — a letter is read slowly. ',
'Jokes and flirting belong there too, but they are not what holds it together.\n',
'⚠⚠ You are ANSWERING, not starting. His letter is the last entry in the mail ',
'history. Answer what he actually wrote: react to his news, answer his ',
'questions, and only then add your own.\n',
'⚠ You have two histories: chat messages and letters. They are the same person. ',
'Lean on both; do not write as if you were strangers.\n',
'If he left a question of yours unanswered, you may ask it again.')
 WHERE `name` LIKE 'mail\_reply\_%'
   AND (`prompt_system` IS NULL OR `prompt_system` = '');

-- ⚠⚠ **И переводим агента на общий workflow.** Константа в коде
-- (`MAIL_REPLY_WORKFLOW`) решает, с чем завести агента **нового** сайта; у
-- заведённого workflow записан в строке и сам собой не меняется.
--
-- Без этой правки вся работа была бы впустую: агент получил бы новый системный
-- промпт и по-прежнему ходил бы старым `dating_mail_reply`, где нет ни истории
-- чата, ни переменной писем. Поймано сверкой на копии прод-базы.
UPDATE `agent` a
  JOIN `agent_workflow` w ON w.`name` = 'dating_talk'
   SET a.`workflow_id` = w.`id`
 WHERE a.`name` LIKE 'mail\_reply\_%';

-- ── 5. Осиротевший workflow ─────────────────────────────────────────────────
--
-- ⚠ Письма избранным пишет `dating_talk` с агентом `fav_mail_*` — этот больше не
-- зовётся ниоткуда. Последний прогон на проде 23.09 в 16:47, до выкладки.
--
-- ⚠⚠ Удаляем **шаги явно**: у них внешний ключ `ON DELETE SET NULL`, и без этого
-- остались бы сироты без workflow. Связи переменных чистит CASCADE.
DELETE s FROM `agent_workflow_step` s
  JOIN `agent_workflow` w ON w.`id` = s.`workflow_id`
 WHERE w.`name` = 'dating_favorite_mail_write';

DELETE FROM `agent_workflow` WHERE `name` = 'dating_favorite_mail_write';

-- ── Проверка ────────────────────────────────────────────────────────────────
SELECT 'ИТОГ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'talk_history_chat') AS есть_чат,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'talk_history_mail') AS есть_письма,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'talk_history') AS старая_осталась,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `metadata` LIKE '%talk\_history\_mail%') AS шагов_с_письмами,
       (SELECT COUNT(*) FROM `agent` WHERE `name` LIKE 'mail\_reply\_%'
           AND `prompt_system` <> '') AS агентов_с_промптом,
       (SELECT COUNT(*) FROM `agent` a JOIN `agent_workflow` w
                ON w.`id` = a.`workflow_id`
         WHERE a.`name` LIKE 'mail\_reply\_%'
           AND w.`name` = 'dating_talk') AS агентов_на_общем_wf,
       (SELECT COUNT(*) FROM `agent_workflow`
         WHERE `name` = 'dating_favorite_mail_write') AS осиротевший_остался,
       (SELECT COUNT(DISTINCT COALESCE(`default`, '\0')) FROM `agent_workflow_variable`
         WHERE `name` IN ('talk_history_chat', 'talk_history_mail'))
         AS умолчаний_видов;
