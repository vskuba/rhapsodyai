-- Workflow `dating_mail_write`: агент пишет шаблон письма (2026-09-07)
--
-- ЗАЧЕМ. В DatingAi шаблоны рассылки пишут руками: текст на четыре абзаца, с
-- переменными вида `[[girl_name]]`, и таких шаблонов нужен не один — одинаковое
-- письмо, ушедшее сотне человек, выдаёт рассылку первым же. Теперь черновик
-- пишет агент, а человек правит.
--
-- ⚠ ЧЕМУ УЧИТ ПРОМПТ, И ПОЧЕМУ ИМЕННО ЭТОМУ.
--
-- 1. **Не более четырёх абзацев.** Письмо на сайте знакомств читают с телефона;
--    простыня не будет прочитана — зато будет отправлена тысяче человек.
-- 2. **Вопросы про интересы собеседника.** Письмо без вопроса не получает
--    ответа, а рассылка затевается ради ответов. Сведения о собеседнике при этом
--    приходят переменной: агент спрашивает про то, что у человека в профиле, а не
--    вообще.
-- 3. **Переменные — только из списка.** Их реестр ведёт человек в панели, и
--    выдуманное имя не подставится ничем: письмо с ним просто не уйдёт.
--
-- ⚠ ПОЧЕМУ ОДИН ШАГ `return_response_llm`, А НЕ `llm_to_json`. Тому нужны
-- заранее известные ключи, а нам нужен **текст письма** — один кусок, который
-- человек будет править глазами. Оборачивать его в JSON ради одного поля значило
-- бы добавить разбор там, где разбирать нечего.
--
-- ⚠ ПОЧЕМУ ПЕРЕМЕННЫЕ ТИПА `workflow`, А НЕ `input`. `input` движок проверяет и
-- отвергает запрос без них (HTTP 400). Здесь все три приходят из `POST /chat/ask`,
-- и умолчания нужны на случай, когда вызывающий их не передал: агент напишет
-- письмо общего вида, а не уронит разговор.
--
-- Идемпотентность: всё вставляется по условию отсутствия.

-- ---------------------------------------------------------------- До
SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow` WHERE `name` = 'dating_mail_write') AS workflow_есть,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('mail_vars', 'girl_card', 'companion_card', 'mail_hint')) AS переменных;

-- ------------------------------------------- Сам workflow
INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`, `subflow`)
SELECT 2, 'dating_mail_write', 'Черновик письма',
       'Пишет шаблон письма рассылки: до четырёх абзацев, с вопросами про интересы собеседника и переменными из реестра сайта',
       0, 0
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write');

-- ------------------------------------------- Единственный шаг
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 1, 'Письмо', 0,
       JSON_OBJECT(
         'transitions_after', JSON_ARRAY(),
         'prompt_user',
         CONCAT(
           'Ты пишешь письмо от девушки мужчине на сайте знакомств. ',
           'Это первое письмо: они не знакомы.\n\n',
           '=== От кого письмо ===\n%girl_card%\n\n',
           '=== Кому письмо ===\n%companion_card%\n\n',
           '=== Переменные, которые можно вставить ===\n%mail_vars%\n\n',
           '=== Пожелание к письму ===\n%mail_hint%\n\n',
           'Правила:\n',
           '1. Не больше четырёх абзацев. Письмо читают с телефона: длинное не дочитают.\n',
           '2. Обязательно задай вопрос про интересы собеседника — опирайся на то, ',
           'что о нём известно выше. Письмо без вопроса не получает ответа.\n',
           '3. Вставляй переменные в виде [[имя]] — ровно те, что в списке. ',
           'Других не выдумывай: их нечем подставить, и письмо не уйдёт.\n',
           '4. Обращайся к нему по имени через переменную, а не словом «привет».\n',
           '5. Пиши живо и просто, без канцелярита и без признаний в любви: ',
           'это первое письмо незнакомому человеку.\n',
           '6. Ответ — только текст письма. Без заголовков, пояснений и markdown.'
         ))
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_step`
                    WHERE `workflow_id` = @wf AND `position` = 0);

-- ------------------------------------------- Переменные
--
-- `mail_vars` и `girl_card` уже заведены workflow `dating_mail_vars` — переменные
-- в этой базе общие, и вторая с тем же именем сделала бы подстановку
-- неоднозначной. Заводим только недостающие.
INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'companion_card', 'workflow', '(о собеседнике ничего не известно)',
       'Что известно об адресате: имя, возраст, страна, текст профиля'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'companion_card');

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'mail_hint', 'workflow', 'обычное первое письмо',
       'Пожелание человека: о чём письмо, какой тон'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `name` = 'mail_hint');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` IN ('mail_vars', 'girl_card', 'companion_card', 'mail_hint')
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ---------------------------------------------------------------- После
SELECT 'ПОСЛЕ' AS этап,
       (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_write') AS workflow_id,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `workflow_id` = @wf) AS переменных;
