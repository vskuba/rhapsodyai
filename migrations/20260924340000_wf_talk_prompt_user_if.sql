-- `prompt_user` несёт слова собеседника, и только их (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Промпт сам объявляет, что там лежит:
--
--     === %companion_title% пишет ===
--     %prompt_user%
--
-- А панель клала туда **задание агенту**, по-русски, в трёх случаях из четырёх:
--
--     он замолчал       «Собеседница не ответила… Продолжи разговор»
--     письмо первым     «Напиши письмо этому человеку: разговор затих…»
--     ответ на письмо   «Ответь на последнее письмо этого человека»
--
-- Модель читала это как сказанное человеком — и тут же ниже, в том же промпте,
-- видела «Отвечать не на что: он молчит». Два соседних абзаца противоречили друг
-- другу, и виноват был не промпт, а то, что мы клали в чужое поле своё.
--
-- ⚠ Задание при этом **уже целиком лежит в промпте ветки** («=== Что нужно ===»),
-- а ветку выбирают флаги `mail_mode`, `mail_kind`, `make_initiative` — проверкой
-- `transitions_before` **до** шага сочинения. Текст в `prompt_user` не решал
-- ничего, кроме одного случая, и тот чинится флагом (см. ниже).
--
-- ## Что делает миграция
--
-- Оборачивает блок «он пишет» в `%if prompt_user%` — семь шагов. Больше ничего:
-- сама запись обмена берёт `prompt_user` с самого начала
-- (`…_wf_talk_companion_session`).
--
-- ## ⚠ Что меняется у панели вместе с этим
--
-- Путь «он замолчал, пишем первыми» шёл веткой чата, и единственным, что
-- сообщало ей «заговори», был тот самый русский текст. Убрав его, панель обязана
-- слать `make_initiative = 1` — тогда заход идёт веткой «Инициатива», у которой
-- это и написано в задании. Правка в `DatingAi/src/dating/answer.py`.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE CONCAT('%пишет ===', CHAR(10), '\%prompt\_user\%%')) AS блоков_без_условия,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` LIKE 'Разговор: записать%'
           AND (`metadata` LIKE '%"question": "prompt_user"%'
             OR `metadata` LIKE '%"question":"prompt_user"%')) AS записей_на_prompt_user;

-- ── Блок «он пишет» показывается, только если есть что показать ──────────
--
-- ⚠ Без условия пустой `prompt_user` оставил бы в промпте голый заголовок
-- «=== Gerard пишет ===» и пустую строку под ним. Модель читает это как «он
-- прислал пустоту» — хуже, чем не показывать раздел вовсе.
--
-- ⚠⚠ Замена идёт по **распакованной строке** (`JSON_UNQUOTE` → `REPLACE` →
-- `JSON_SET`): внутри JSON переносы строк лежат экранированными, и повторить эту
-- лесенку в SQL-литерале уже дважды не удалось — замена проходила «удачно», не
-- изменив ничего (`…_wf_talk_companion_key`).
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 CONCAT('=== %companion_title% пишет ===', CHAR(10),
                        '%prompt_user%', CHAR(10)),
                 CONCAT('%if prompt_user%=== %companion_title% пишет ===', CHAR(10),
                        '%prompt_user%', CHAR(10), '%endif%')))
 WHERE `workflow_id` = @wf
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       LIKE CONCAT('%', '=== \%companion\_title\% пишет ===', CHAR(10),
                   '\%prompt\_user\%', CHAR(10), '%')
   -- ⚠⚠ Уже обёрнутое пропускаем: обёртка содержит внутри себя тот же блок, и
   -- без этой строки повторный прогон оборачивал его вторично —
   -- `%if prompt_user%%if prompt_user%===…%endif%%endif%`.
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%\%if prompt\_user\%=== \%companion\_title\% пишет%';

SELECT 'ПОСЛЕ' AS этап,
       -- ⚠ Голых блоков не осталось. Считаем «блок есть, а обёртки нет»:
       -- искать один блок бесполезно — обёртка содержит его внутри себя.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE CONCAT('%', '=== \%companion\_title\% пишет ===', CHAR(10),
                           '\%prompt\_user\%', CHAR(10), '%')
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               NOT LIKE '%\%if prompt\_user\%=== \%companion\_title\% пишет%')
         AS осталось_без_условия,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%\%if prompt\_user\%=== \%companion\_title\% пишет%') AS под_условием,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` LIKE 'Разговор: записать%'
           AND (`metadata` LIKE '%"question": "prompt_user"%'
             OR `metadata` LIKE '%"question":"prompt_user"%')) AS записей_на_prompt_user,
       -- ⚠ JSON обязан уцелеть: правка идёт через распаковку и сборку строки,
       -- и сломанный `metadata` уронил бы прогон целиком.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND NOT JSON_VALID(`metadata`)) AS битых_метаданных,
       -- ⚠⚠ Двойной обёртки быть не должно. Она безвредна на вид (условие
       -- истинно дважды), но означает, что повтор не идемпотентен — и следующая
       -- правка того же места сработает не там, где думали.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%\%if prompt\_user\%\%if prompt\_user\%%') AS обёрнуто_дважды;
