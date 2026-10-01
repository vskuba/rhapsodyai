-- `dating_gallery_describe`: объявляем `chat_timeout` входной (2026-10-01)
--
-- ЗАЧЕМ. Панель DatingAi кладёт `chat_timeout` в **каждый** вызов `/chat/ask`
-- сама (`rhapsody_api_chat_ask`: 240 секунд), а движок с недавних пор проверяет
-- контракт входа и отвергает незнакомую переменную:
--
--     Переменные chat_timeout не объявлены входящими у этого workflow.
--     (/chat/ask → 400)
--
-- То есть workflow без этого объявления не прогоняется вовсе — ни разу.
--
-- ⚠⚠ ПОЧЕМУ ЭТОГО НЕ ВИДНО БЫЛО РАНЬШЕ. Заглушка соседа в сюите DatingAi
-- отвечает на `/chat/ask` заготовленным текстом и контракт входа не проверяет:
-- десять зелёных тестов разбора прошли на вызове, который живой сосед
-- отвергает первым же ответом. Поймала это только сквозная проверка на
-- поднятой панели.
--
-- ⚠ Остальные dating-workflow (`dating_invite_write`, `dating_mail_vars`,
-- `dating_mail_question`) переменную объявляют — с умолчанием 1800. Повторяем
-- за ними: значение всё равно приходит от панели, а умолчание нужно тем, кто
-- гоняет workflow руками со страницы.
--
-- Отдельной миграцией, а не правкой вчерашней: та применена
-- (`20261001140000_wf_dating_gallery_describe`), и `yoyo` её второй раз не
-- выполнит.
--
-- Идемпотентность: вставка по условию отсутствия.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable` v
          JOIN `agent_workflow` w ON w.`id` = v.`workflow_id`
         WHERE w.`name` = 'dating_gallery_describe'
           AND v.`name` = 'chat_timeout') AS объявлена;

SET @wf = (SELECT `id` FROM `agent_workflow`
            WHERE `name` = 'dating_gallery_describe');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @wf, 'chat_timeout', 'input', '1800',
       'Таймаут ожидания ответа в чате, сек. Кладёт панель в каждый вызов '
       '/chat/ask; без объявления движок отвергает запрос целиком'
 WHERE @wf IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `workflow_id` = @wf AND `name` = 'chat_timeout');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `workflow_id` = @wf) AS переменных,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `workflow_id` = @wf AND `type` = 'input') AS входных;
