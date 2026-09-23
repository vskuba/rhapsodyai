-- chat_timeout объявлен у мастеров заведения агента (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: без этого заведение анкеты падает с 400
--
-- Запрет незаявленных переменных (`20260923030000_wf_inputs_declared` плюс
-- проверка в `chat.py`) отвергает всё, чего нет в списке входящих. Списки сняты
-- с кода вызывающих — но **одного вызывающего пропустили**, и он не в DatingAi,
-- а здесь же, в ручке `/agent/create`:
--
--     variables = dict(data.variables or {})
--     variables['agent_name'] = data.name
--     variables.setdefault('chat_timeout', AGENT_CREATE_CHAT_TIMEOUT)
--
-- То есть ручка добавляет `chat_timeout` **сама, всем мастерам без разбора**, и
-- вызывающий об этом не знает: DatingAi шлёт только `girl_bio`.
--
-- `agent_name` проходит — он `global`. `chat_timeout` объявлен входящим у
-- `dating_talk` и `workflow_shell_test`, но **не у `dating_girl_create`** — а
-- именно его гоняет заведение агента анкеты (`dating_girl_create_runner`).
--
-- Итог без этой миграции: `POST /agent/create` отвечает 400 «Переменные
-- chat_timeout не объявлены входящими», и **ни одна новая анкета не заводится**.
-- Старые работают: у них агент уже есть.
--
-- ⚠ Поймано прогоном миграций на копии прод-базы перед выкладкой, а не тестами:
-- локальная база уже имела нужные строки от прошлых заходов, и проверка была
-- зелёной при сломанном проде.
--
-- ## Что делает
--
-- Привязывает существующую переменную `chat_timeout` (id 101, `input`,
-- умолчание 1800) к `dating_girl_create`.
--
-- ⚠ **Новую не заводим**: одно понятие — одна строка реестра. Вторая с тем же
-- именем разошлась бы с первой при первой правке умолчания, а `/chat/ask` читает
-- обе.
--
-- ⚠⚠ **Берём мастеров списком, а не по имени.** Ручка добавляет `chat_timeout`
-- каждому, кого зовёт: сегодня мастер один (`dating_girl_create`), завтра их
-- станет два, и второй упал бы ровно так же. Условие «у workflow есть агент
-- `<имя>_runner`» повторяет то, как ручка его находит.
--
-- Идемпотентность: связь заводится проверкой на наличие.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
          JOIN `agent_workflow` w ON w.`id` = vw.`workflow_id`
         WHERE v.`name` = 'chat_timeout'
           AND EXISTS (SELECT 1 FROM `agent` a
                        WHERE a.`name` = CONCAT(w.`name`, '_runner'))) AS у_мастеров;

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, w.`id`
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow` w
    ON EXISTS (SELECT 1 FROM `agent` a
                WHERE a.`name` = CONCAT(w.`name`, '_runner'))
 WHERE v.`name` = 'chat_timeout'
   AND v.`type` = 'input'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = w.`id`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` vw
          JOIN `agent_workflow_variable` v ON v.`id` = vw.`variable_id`
          JOIN `agent_workflow` w ON w.`id` = vw.`workflow_id`
         WHERE v.`name` = 'chat_timeout'
           AND EXISTS (SELECT 1 FROM `agent` a
                        WHERE a.`name` = CONCAT(w.`name`, '_runner')))
         AS у_мастеров,
       -- ⚠ Сверка, что строка в реестре осталась одна: заведи миграция вторую —
       -- умолчания разошлись бы молча.
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'chat_timeout') AS строк_в_реестре;
