-- dating_talk: три входящих переменных заведены в реестре (2026-09-22)
--
-- ЗАЧЕМ. У workflow должно быть **три входящих переменных** — то, что кладёт
-- в вызов DatingAi и без чего разговор не собрать: `girl_id`, `answer_anyway`,
-- `companion_bio`.
--
-- Значилась в реестре одна (`girl_id`). Остальные приезжали в запросе и нигде не
-- числились: работают — сборка кладёт в scope всё, что пришло, — но их **не
-- видно**. Человек, открывший `%if answer_anyway%` в промпте, не может узнать,
-- откуда она берётся и что значит пустая.
--
-- ## ⚠⚠ Что значит `input` в этой установке
--
-- **Обязательная.** Ручка чата проверяет, что такая переменная есть в раскладке,
-- и отвечает `400`, если её нет (`chat.py`, «обязательная для workflow, но
-- отсутствует в маппинге»).
--
-- Звучит опасно, а на деле безопасно — и ровно по одной причине: проверка идёт
-- **после** `ai_workflow_variables_defaults_apply`, а тот кладёт в scope
-- умолчание каждой переменной workflow, не глядя на тип. Пустое умолчание
-- (и даже `NULL` — он превращается в `''`) проверку закрывает.
--
-- ⚠ То есть `input` здесь объявляет **договор**, а не требование к каждому
-- вызову: «эти три кладёт вызывающий». Заход без них законен и проходит.
--
-- ⚠⚠ И пустое умолчание — не формальность, а сама работа правил: `%if%` считает
-- ложными пустое, `'0'` и отсутствие (`ai_workflow_variable_truthy`). «Не
-- передали» и «передали пустую» значат одно. Заведи мы `answer_anyway`
-- умолчанием `'1'`, каждый заход стал бы обязательным — то есть девушка
-- потеряла бы право промолчать на невнятицу.
--
-- ⚠ Проверено живым вызовом, а не выведено из чтения кода: чат отвечает и с
-- переданными переменными, и без них.
--
-- Идемпотентность: заведение — проверкой на наличие, смена типа — `UPDATE`,
-- который повторно ничего не меняет.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'answer_anyway') AS есть_answer_anyway,
       (SELECT `type` FROM `agent_workflow_variable`
         WHERE `name` = 'companion_bio') AS тип_companion_bio;

-- ── `answer_anyway`: здесь молчать нельзя ───────────────────────────────────

INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`)
SELECT 'answer_anyway', 'input', '',
       'Молчать нельзя: 1 — ответ обязателен, пусто или 0 — обычный заход. Кладёт DatingAi на первый ответ человеку после нашего приглашения'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable`
                    WHERE `name` = 'answer_anyway');

INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, @wf FROM `agent_workflow_variable` v
 WHERE v.`name` = 'answer_anyway'
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = @wf);

-- ── Все три — входящие ──────────────────────────────────────────────────────
--
-- ⚠ `answer_anyway` мог уже лежать `workflow`-переменной от прежнего захода
-- миграции: `UPDATE` приводит к одному виду и его, и `companion_bio`.
UPDATE `agent_workflow_variable`
   SET `type` = 'input'
 WHERE `name` IN ('girl_id', 'answer_anyway', 'companion_bio');

-- ⚠ Умолчание подтверждаем **явно**: на нём держится безопасность `input`.
-- `NULL` сборка превращает в `''` сама, но полагаться на это в договоре не
-- стоит — он читается глазами, и `NULL` в нём выглядит как «значения нет».
UPDATE `agent_workflow_variable`
   SET `default` = ''
 WHERE `name` IN ('girl_id', 'answer_anyway', 'companion_bio')
   AND `default` IS NULL;

-- Должно выйти ровно три входящих у этого workflow, все с пустым умолчанием.
SELECT 'ПОСЛЕ' AS этап, v.`name`, v.`type`, v.`default` = '' AS умолчание_пусто
  FROM `agent_workflow_variable` v
  JOIN `agent_workflow_variable_workflow` vw ON vw.`variable_id` = v.`id`
 WHERE vw.`workflow_id` = @wf AND v.`type` = 'input'
 ORDER BY v.`name`;
