-- Описания переменных разговора врут о том, кто их кладёт (2026-10-01)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Описание — единственное, что человек читает в редакторе переменных, не открывая
-- шаги. Семь описаний говорят неправду, и обе неправды одного рода: они называют
-- **источник**, которого больше нет.
--
--     talk_history_chat        «Кладёт панель»          → панель не шлёт её с 25.09
--     talk_history_mail        «Кладёт панель»          → то же
--     talk_history_chat_kind   «Кладёт шаг „Ключи“»     → шага «Ключи» в workflow нет
--     talk_history_chat_limit  «Кладёт шаг „Ключи“»     → то же
--     talk_history_mail_kind   «Кладёт шаг „Ключи“»     → то же
--     talk_history_mail_limit  «Кладёт шаг „Ключи“»     → то же
--     talk_session_kind        «Кладёт шаг „Ключи“»     → то же
--
-- ## Откуда они берутся на самом деле
--
-- **Ленты.** DatingAi перестал их слать (`talk_history.py` удалён), а
-- `…_wf_talk_history_not_input` сняла у `dating_talk` объявление входящей: теперь
-- присылка отвечает `400`. Кладут их свои же шаги — «История: чат» (поз. 3) и
-- «История: письма» (поз. 4) зовут `companion_session_history`, а «Переменные:
-- история» (поз. 5) переносит ответ инструмента в переменную.
--
-- ⚠ Строки `talk_history_chat` и `talk_history_mail` принадлежат **подпрогону**
-- `dating_talk_about_photo` (`workflow_id`), и там они правда входящие — родитель
-- передаёт их `inputs_map`-ом шага «Ветка: письма и фото» (поз. 33). Поэтому
-- описание не «кладёт шаг», а «передаёт родитель»: в своём workflow это честный
-- вход, и сказать иначе значило бы соврать второй раз.
--
-- **Канал и предел.** Их кладёт шаг «Переменные» — позиция 0, тип
-- `variable_conversion`. Шага с заголовком «Ключи» в `dating_talk` нет вовсе: все
-- 36 заголовков проверены, совпадений ноль. Заголовок, вероятно, менял человек в
-- редакторе — ровно тот случай, ради которого сторожа повтора в соседних миграциях
-- смотрят на имя инструмента, а не на подпись шага.
--
-- ## ⚠ Почему это не «косметика»
--
-- Описание читают, когда правят промпт и когда ищут, где рвётся цепочка. «Кладёт
-- панель» отправляет искать поломку в DatingAi — в код, которого там больше нет, а
-- `talk_history_chat` в запросе он встретит `400`-м. Полчаса на поиск того, чего
-- нет, эта строка уже стоила.
--
-- ## Что не меняется
--
-- Ни тип переменной, ни владелец (`workflow_id`), ни шаги. Правится только
-- `description` — текст для человека.
--
-- Идемпотентность: `UPDATE` по имени и владельцу, второй прогон меняет ноль строк.

SET @talk = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @photo = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk_about_photo');

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап, v.`name`, v.`type`, v.`description`
  FROM `agent_workflow_variable` v
 WHERE (v.`workflow_id` = @photo AND v.`name` IN ('talk_history_chat', 'talk_history_mail'))
    OR (v.`workflow_id` = @talk AND v.`name` IN ('talk_history_chat_kind',
                                                 'talk_history_chat_limit',
                                                 'talk_history_mail_kind',
                                                 'talk_history_mail_limit',
                                                 'talk_session_kind'))
 ORDER BY v.`name`;

-- --------------------------------------------- 1. Ленты: вход у подпрогона
UPDATE `agent_workflow_variable`
   SET `description` = 'Реплики чата с этим человеком, старые сверху. Передаёт родитель dating_talk шагом «Ветка: письма и фото»'
 WHERE `workflow_id` = @photo AND `name` = 'talk_history_chat';

UPDATE `agent_workflow_variable`
   SET `description` = 'Переписка письмами с этим человеком, старые сверху. Передаёт родитель dating_talk шагом «Ветка: письма и фото»'
 WHERE `workflow_id` = @photo AND `name` = 'talk_history_mail';

-- --------------------------------------------- 2. Канал и предел: шаг «Переменные»
UPDATE `agent_workflow_variable`
   SET `description` = 'Канал ленты чата: chat. Кладёт шаг «Переменные»'
 WHERE `workflow_id` = @talk AND `name` = 'talk_history_chat_kind';

UPDATE `agent_workflow_variable`
   SET `description` = 'Сколько последних обменов чата брать. Кладёт шаг «Переменные»'
 WHERE `workflow_id` = @talk AND `name` = 'talk_history_chat_limit';

UPDATE `agent_workflow_variable`
   SET `description` = 'Канал ленты писем: mail. Кладёт шаг «Переменные»'
 WHERE `workflow_id` = @talk AND `name` = 'talk_history_mail_kind';

UPDATE `agent_workflow_variable`
   SET `description` = 'Сколько последних обменов письмами брать. Кладёт шаг «Переменные»'
 WHERE `workflow_id` = @talk AND `name` = 'talk_history_mail_limit';

UPDATE `agent_workflow_variable`
   SET `description` = 'Канал записи разговора: письма или чат. Кладёт шаг «Переменные»'
 WHERE `workflow_id` = @talk AND `name` = 'talk_session_kind';

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап, v.`name`, v.`type`, v.`description`
  FROM `agent_workflow_variable` v
 WHERE (v.`workflow_id` = @photo AND v.`name` IN ('talk_history_chat', 'talk_history_mail'))
    OR (v.`workflow_id` = @talk AND v.`name` IN ('talk_history_chat_kind',
                                                 'talk_history_chat_limit',
                                                 'talk_history_mail_kind',
                                                 'talk_history_mail_limit',
                                                 'talk_session_kind'))
 ORDER BY v.`name`;
