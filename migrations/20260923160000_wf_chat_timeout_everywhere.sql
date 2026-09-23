-- chat_timeout объявлен у всех workflow, которые зовёт DatingAi (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: инвайты встали на проде через 6 минут после выкладки
--
-- В журнале воркера, 14:18:40:
--
--     [dating] круг инвайтов: сосед ответил отказом: Переменные chat_timeout
--     не объявлены входящими у этого workflow (/chat/ask → 400)
--
-- Пул опустел, круг пошёл набирать новый — и не смог. Ни одной реплики.
--
-- ## Причина: переменную добавляет ДВЕРЬ, а не вызывающий
--
-- `src/rhapsody/rhapsody_api.py:539` у DatingAi:
--
--     'variables': {'chat_timeout': RHAPSODY_API_CHAT_TIMEOUT, **(variables or {})}
--
-- То есть `chat_timeout` уезжает в **каждый** вызов `/chat/ask`, каким бы занятием
-- он ни был: инвайты, письма, переменные, ответы. Вызывающий об этом не знает —
-- `mail_agent.invite_template` кладёт только свои `invite_*`.
--
-- ⚠⚠ **Ровно та же ошибка, что вчера нашлась у `/agent/create`**
-- (`20260923150000_wf_agent_create_timeout`): там переменную добавляла ручка
-- соседа, здесь — дверь у нас. Оба раза список входящих снимался **с кода
-- занятия**, а добавку общего слоя не видел никто.
--
-- Разница только в том, что первую поймала репетиция на копии базы, а эту — прод:
-- я проверила 57 переменных списком, составленным вручную по вызовам
-- `mail_agent.py`, и `chat_timeout` в этом списке не было. Проверка подтвердила
-- то, что я в неё заложила, а не то, что вправду уходит по HTTP.
--
-- ## Что делает
--
-- Привязывает `chat_timeout` ко всем workflow, чьи агенты помечены сайтом
-- (`agent.site` не пуст) — это и есть агенты DatingAi, заводимые `mail_agent`, —
-- плюс к тем, что он зовёт напрямую.
--
-- ⚠ **Не списком имён.** Заведут седьмое занятие — оно упало бы точно так же.
-- Признак «у workflow есть агент с меткой сайта» повторяет то, как эти агенты
-- заводятся (`agent_site` в DatingAi требует метку и без неё не создаёт агента).
--
-- ⚠ `dating_invite_one` и `dating_talk_about_photo` — подпрогоны: своего агента у
-- них нет, а `/chat/ask` их не принимает вовсе. Им переменная не нужна, и
-- условие их не захватывает.
--
-- Идемпотентность: связь заводится проверкой на наличие.

SELECT 'ДО' AS этап,
       (SELECT COUNT(DISTINCT vw.workflow_id)
          FROM agent_workflow_variable_workflow vw
          JOIN agent_workflow_variable v ON v.id = vw.variable_id
         WHERE v.name = 'chat_timeout') AS у_скольких_workflow;

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, w.`id`
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow` w
    ON EXISTS (SELECT 1 FROM `agent` a
                WHERE a.`workflow_id` = w.`id`
                  AND a.`site` IS NOT NULL AND a.`site` <> '')
 WHERE v.`name` = 'chat_timeout'
   AND v.`type` = 'input'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = w.`id`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(DISTINCT vw.workflow_id)
          FROM agent_workflow_variable_workflow vw
          JOIN agent_workflow_variable v ON v.id = vw.variable_id
         WHERE v.name = 'chat_timeout') AS у_скольких_workflow,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'chat_timeout') AS строк_в_реестре;

-- Кто остался без переменной из тех, у кого есть агент с меткой сайта. Пусто —
-- все закрыты.
SELECT 'НЕ ЗАКРЫТ' AS этап, w.`name`
  FROM `agent_workflow` w
 WHERE EXISTS (SELECT 1 FROM `agent` a
                WHERE a.`workflow_id` = w.`id`
                  AND a.`site` IS NOT NULL AND a.`site` <> '')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                     JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
                    WHERE vw.`workflow_id` = w.`id` AND v.`name` = 'chat_timeout');
