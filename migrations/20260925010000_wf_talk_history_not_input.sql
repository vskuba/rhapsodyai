-- Ленты разговора больше не входящие у `dating_talk` (2026-09-25)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- `talk_history_chat` и `talk_history_mail` объявлены **входящими**: так было,
-- пока их присылал DatingAi. Теперь их кладёт сам workflow — шаги «История: чат»
-- и «История: письма» читают `companion_session` (`…_wf_talk_companion_session`),
-- а панель не шлёт их вовсе.
--
-- Объявление осталось и стало враньём: панель переменных показывала их в группе
-- «📥 Входящие переменные», то есть «приходит снаружи», — а рождаются они внутри.
-- Увидела это новая трасса переменных: «Входящие переменные» и тут же
-- «КЛАДУТ: 6. Ленты разговора».
--
-- ## ⚠⚠ Снимаем **только у `dating_talk`**, а у подпрогона оставляем
--
-- Та же переменная объявлена входящей у `dating_talk_about_photo` — и там это
-- правда: родитель передаёт её `inputs_map`-ом шага «Ветка: письма и фото».
--
--     dating_talk              кладёт сам      → объявление снимаем
--     dating_talk_about_photo  получает от родителя → объявление остаётся
--
-- ⚠ Поэтому правится **связь** (`agent_workflow_variable_workflow`), а не тип
-- переменной: тип один на все workflow, и сменив его, мы соврали бы уже про
-- подпрогон.
--
-- ## ⚠ Что это меняет в поведении
--
-- Присылка этих переменных в `/chat/ask` для `dating_talk` станет отвечать `400`
-- («не объявлена входящей»). Это и нужно: значение всё равно перезаписал бы шаг,
-- а молчаливое принятие оставляло бы вид, будто присланное работает.
--
-- ⚠⚠ Вместе с этим едет правка тестов: `Marks` научился **искать, но не слать**
-- (`made=`), иначе `MARKS.vars()` продолжал бы их отправлять и ловил бы `400`.
--
-- ## ⚠ Порядок выкладки
--
-- Сперва код (DatingAi перестал слать — уже сделано), потом это. Наоборот —
-- панель получила бы `400` на каждом ответе в чат.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @sub = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk_about_photo');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @wf
           AND v.`name` IN ('talk_history_chat', 'talk_history_mail')) AS у_чата,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @sub
           AND v.`name` IN ('talk_history_chat', 'talk_history_mail')) AS у_подпрогона;

-- ── Снятие ──────────────────────────────────────────────────────────────────
--
-- ⚠ Сама переменная остаётся в реестре: её объявление живо у подпрогона, и
-- удаление строки унесло бы его заодно.
DELETE x FROM `agent_workflow_variable_workflow` x
  JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
 WHERE x.`workflow_id` = @wf
   AND v.`name` IN ('talk_history_chat', 'talk_history_mail');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @wf
           AND v.`name` IN ('talk_history_chat', 'talk_history_mail')) AS осталось_у_чата,
       -- ⚠⚠ У подпрогона обязано уцелеть: он вправду получает их от родителя, и
       -- сняв объявление там, мы сломали бы ветку письма-фото.
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow` x
          JOIN `agent_workflow_variable` v ON v.`id` = x.`variable_id`
         WHERE x.`workflow_id` = @sub
           AND v.`name` IN ('talk_history_chat', 'talk_history_mail')) AS цело_у_подпрогона,
       -- ⚠ И сами переменные обязаны остаться в реестре.
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` IN ('talk_history_chat', 'talk_history_mail')) AS есть_в_реестре,
       -- ⚠ Шаги, которые их кладут, на месте: без них снятие объявления
       -- означало бы, что ленты не берутся ниоткуда.
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.tool_invoke.tool_name'))
               = 'companion_session_history') AS шагов_чтения;
