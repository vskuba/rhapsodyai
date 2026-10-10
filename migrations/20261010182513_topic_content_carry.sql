-- Содержимое тем: метки-иглы, пороги, вопросы и подпоток (2026-10-10)
--
-- ЗАЧЕМ. Шаг `topic_action` на проде есть (его перевела
-- `20261010180756_branch_drop.sql`), но работать ему нечем: метки темы там
-- прежние — фразы, которые в живом тексте не встречаются, вопросов нет вовсе,
-- поле «переменная с историей» пустое, а подпоток состоит из старого шага
-- пересказа. Эта миграция переносит настроенное содержимое.
--
-- ⚠⚠ НИ ОДНОГО НОМЕРА СТРОКИ В ПЕРЕНОСЕ НЕТ. Локально группа 155, тема 77,
-- подпоток зовётся `dating_talk_topic`; на проде номера свои, а подпоток и
-- вовсе `dating_talk_about_photo` — его там ни разу не переименовывали.
-- Поэтому:
--   * группа и тема ищутся по `name` в ноде;
--   * подпоток — по ДОРОГЕ от шага темы (`topic_action.workflow_id`), а не по
--     имени: имя у него на каждой установке своё;
--   * переходы между новыми шагами проставляются ПОСЛЕ вставки.
--
-- ⚠ Миграция идемпотентна: повторный прогон не заведёт вторых вопросов и
-- вторых шагов — каждый кусок прикрыт проверкой на существование.
--
-- Устройство слоя — `.claude/docs/workflow_branch.md`, §6.

-- ── 0. Что было до ──────────────────────────────────────────────────────────

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_topic_question`) AS вопросов,
       (SELECT `tags_qty_accept` FROM `agent_workflow_topic`
         WHERE `name` = 'photo_mail' LIMIT 1) AS порог_меток,
       (SELECT COUNT(*) FROM `agent_workflow_variable`
         WHERE `name` = 'talk_history_topic') AS переменная_истории;

-- ── 1. Кого правим: ищем по именам и по дороге шага ─────────────────────────

SET @node_id = (SELECT `node_id` FROM `agent_workflow_topic_group`
                 WHERE `name` = 'deal' LIMIT 1);

SET @talk_id = (SELECT `id` FROM `agent_workflow`
                 WHERE `name` = 'dating_talk' LIMIT 1);

SET @topic_step = (
    SELECT s.`id` FROM `agent_workflow_step` s
      JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
     WHERE s.`workflow_id` = @talk_id AND t.`name` = 'topic_action'
     LIMIT 1
);

-- ⚠⚠ Подпоток берётся из метаданных шага, а не по имени: это единственный
-- ответ, который не зависит от того, как его на этой установке назвали.
SET @sub_id = (
    SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.topic_action.workflow_id'))
      FROM `agent_workflow_step` WHERE `id` = @topic_step
);

SET @topic_id = (SELECT t.`id` FROM `agent_workflow_topic` t
                   JOIN `agent_workflow_topic_group` g ON g.`id` = t.`topic_group_id`
                  WHERE g.`name` = 'deal' AND t.`name` = 'photo_mail' LIMIT 1);

-- ── 2. Тема: метки-иглы и два порога ────────────────────────────────────────
--
-- ⚠⚠ Метки переписаны из фраз в КОРОТКИЕ СЛОВА. Прежние (`exchange of
-- letters`, `send a pic`) писались, чтобы их выбирала модель; код ищет их в
-- тексте беседы, и на 255 живых прогонах ни одна не встретилась ни разу —
-- люди пишут «send me a pic». Разбор — `workflow_branch.md`, §6.1.

UPDATE `agent_workflow_topic`
   SET `tags` = 'letter, letters, mail, photo, photos, pic, pics, send, show',
       `tags_qty_accept` = 2,
       `questions_qty_yes_accept` = 1
 WHERE `id` = @topic_id;

-- ── 3. Вопросы темы ─────────────────────────────────────────────────────────
--
-- ⚠⚠ Страховка — по ТЕКСТУ вопроса, а не «у темы вопросов нет вовсе». Со
-- вторым условием первая вставка делала счёт ненулевым, и два следующих
-- вопроса молча не заводились: на репетиции доехал один из трёх.
--
-- ⚠ Вопрос, который человек правил или удалил, заведётся заново — это цена
-- адресации по тексту. Своего ключа у вопроса нет, а номер строки в перенос
-- не возьмёшь: он на каждой установке свой.

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @topic_id, 'Does either of them hint at exchanging letters?', 1, 1
  FROM (SELECT 1) AS x
 WHERE @topic_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_topic_question`) AS already
                    WHERE already.`topic_id` = @topic_id
                      AND already.`question` = 'Does either of them hint at exchanging letters?');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @topic_id, 'Does either of them offer to exchange photos?', 1, 2
  FROM (SELECT 1) AS x
 WHERE @topic_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_topic_question`) AS already
                    WHERE already.`topic_id` = @topic_id
                      AND already.`question` = 'Does either of them offer to exchange photos?');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @topic_id, 'Does either of them offer to send a photo?', 1, 3
  FROM (SELECT 1) AS x
 WHERE @topic_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_topic_question`) AS already
                    WHERE already.`topic_id` = @topic_id
                      AND already.`question` = 'Does either of them offer to send a photo?');

-- ── 4. Подпоток: имя и описание ─────────────────────────────────────────────

UPDATE `agent_workflow`
   SET `name` = 'dating_talk_topic',
       `title` = 'Чат: тема разговора',
       `description` = 'Подпоток темы: задаёт вопросы темы, считает ответы «yes» и накапливает инструкции поднятых тем'
 WHERE `id` = @sub_id;

-- ── 5. Переменные подпотока ─────────────────────────────────────────────────
--
-- ⚠⚠ Накопитель объявляется ВХОДЯЩИМ: родитель передаёт в него набранное
-- прежними темами, и без `input` контракт вызова его не примет. Прежде он был
-- `workflow` — то есть рождался пустым на каждом заходе.

UPDATE `agent_workflow_variable`
   SET `type` = 'input', `default` = ''
 WHERE `workflow_id` = @sub_id AND `name` = 'branch_angle_instruction';

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub_id, 'topic_answers', 'workflow', '', 'Ответы на вопросы темы: номер — yes/no'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) AS v
                    WHERE v.`workflow_id` = @sub_id AND v.`name` = 'topic_answers');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub_id, 'topic_answers_yes_qty', 'workflow', '0', 'Сколько ответов «yes»'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) AS v
                    WHERE v.`workflow_id` = @sub_id AND v.`name` = 'topic_answers_yes_qty');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @sub_id, 'topic_raised', 'workflow', '', 'Тема поднята: «1» либо пусто'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) AS v
                    WHERE v.`workflow_id` = @sub_id AND v.`name` = 'topic_raised');

-- ── 6. Шаги подпотока ───────────────────────────────────────────────────────
--
-- ⚠⚠ Старый шаг пересказа снимается: он просил модель изложить своими словами
-- инструкцию, которую человек уже написал в теме. Вызов модели в подпотоке
-- ровно один — вопросы.

DELETE FROM `agent_workflow_step`
 WHERE `workflow_id` = @sub_id AND `title` = 'Ответ ветки';

SET @type_llm = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'llm_to_json');
SET @type_var = (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'variable_conversion');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @sub_id, @type_llm, 'Вопросы темы', 0, '{"prompt_user": "=== Current time ===\\n%datetime_current_get%\\n\\n[<if talk_history_chat>]=== Conversation with %companion_title% in chat ===\\n%talk_history_chat%\\n\\n[<endif>][<if talk_history_mail>]=== Correspondence by letters with %companion_title% (time in square brackets; \\"she\\" — you) ===\\n%talk_history_mail%\\n\\n[<endif>][<if prompt_user>]=== %companion_title% writes now ===\\n%prompt_user%\\n\\n[<endif>]=== Questions ===\\n%topic_action_questions%\\n\\n=== What is needed ===\\nAnswer every question above with \\"yes\\" or \\"no\\". Nothing else.\\n\\n\\"yes\\" — only if the conversation above contains it plainly, in words someone actually wrote.\\n\\"no\\" — if it is absent, merely implied, guessed, or only possible.\\n\\n⚠ A question asks what is in the text, not what could happen next.\\n⚠ Judge the latest turn of the conversation, not its whole past: an offer made long ago and already answered is not being made now.\\n⚠ Questions are independent. \\"yes\\" to one is not a reason to answer \\"yes\\" to its neighbour, even when they sound alike.\\n⚠ Most conversations are about nothing on this list. \\"no\\" to every question is a normal and expected answer.\\n\\n=== Important information about final response ===\\nPlease return your response in JSON format. The JSON response must contain follow keys:\\n- \\"topic_answers\\": every question number with its answer, comma separated\\n- \\"topic_answers_yes_qty\\": how many answers are \\"yes\\" — a number\\n\\n⚠ Answer every number from the list above, and use no numbers that are not in it.\\n\\nExample of JSON response:\\n{\\n  \\"topic_answers\\": \\"1: no, 2: no, 3: no\\",\\n  \\"topic_answers_yes_qty\\": 0\\n}\\n\\nOne more example of JSON response:\\n{\\n  \\"topic_answers\\": \\"1: yes, 2: no, 3: yes\\",\\n  \\"topic_answers_yes_qty\\": 2\\n}", "llm_to_json_variable": [{"variable": "topic_answers", "text": ""}, {"variable": "topic_answers_yes_qty", "text": ""}], "transitions_before": [], "transitions_after": [], "to_next_step": true}'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) AS s
                    WHERE s.`workflow_id` = @sub_id AND s.`title` = 'Вопросы темы');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @sub_id, @type_var, 'Тема поднята?', 1, '{"variable_conversion": [{"variable": "topic_raised", "text": "[<if topic_answers_yes_qty >= topic_action_questions_qty_yes_accept>]1[<endif>]"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) AS s
                    WHERE s.`workflow_id` = @sub_id AND s.`title` = 'Тема поднята?');

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @sub_id, @type_var, 'Инструкции: накопить', 2, '{"variable_conversion": [{"variable": "branch_angle_instruction", "text": "[<if branch_angle_instruction>]%branch_angle_instruction%\\n\\n— — —\\n\\n[<endif>]%topic_action_instructions%"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step`) AS s
                    WHERE s.`workflow_id` = @sub_id AND s.`title` = 'Инструкции: накопить');

UPDATE `agent_workflow_step`
   SET `position` = 3
 WHERE `workflow_id` = @sub_id AND `title` = 'Ответ';

-- ── 7. Переходы: номера известны только теперь ──────────────────────────────
--
-- ⚠⚠ Ради этого шаги и вставлялись без переходов. `step_id` в переходе — номер
-- строки, а он на каждой установке свой: перенеси его из локальной базы, и
-- движок прыгнул бы в чужой шаг или упал на отсутствующем.

SET @s_ask = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @sub_id AND `title` = 'Вопросы темы' LIMIT 1);
SET @s_raised = (SELECT `id` FROM `agent_workflow_step`
                  WHERE `workflow_id` = @sub_id AND `title` = 'Тема поднята?' LIMIT 1);
SET @s_keep = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @sub_id AND `title` = 'Инструкции: накопить' LIMIT 1);
SET @s_return = (SELECT `id` FROM `agent_workflow_step`
                  WHERE `workflow_id` = @sub_id AND `title` = 'Ответ' LIMIT 1);

-- Нет вопросов — тема поднимается одними метками: модель не зовём.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_before',
           JSON_ARRAY(JSON_OBJECT('variable', 'topic_action_questions',
                                  'operator', 'empty', 'value', '',
                                  'step_id', CAST(@s_keep AS CHAR))))
 WHERE `id` = @s_ask;

-- «Yes» не набралось — отдаём накопленное нетронутым.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after',
           JSON_ARRAY(JSON_OBJECT('variable', 'topic_raised',
                                  'operator', 'empty', 'value', '',
                                  'step_id', CAST(@s_return AS CHAR))))
 WHERE `id` = @s_raised;

-- ── 8. Родитель: текст, в котором ищут метки ────────────────────────────────
--
-- ⚠⚠ Пришедшая реплика лежит ОТДЕЛЬНО от истории, в `prompt_user`. Подай шагу
-- `talk_history_chat` — и «Can you send me your photos?» в текст не попадёт:
-- обе метки искать будет негде, тема не поднимется ни разу. Ровно это и
-- случилось при переводе шага.

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @talk_id, 'talk_history_topic', 'workflow', '',
       'Чат, письма и пришедшая реплика — в этом тексте ищут метки тем'
  FROM (SELECT 1) AS x
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable`) AS v
                    WHERE v.`workflow_id` = @talk_id AND v.`name` = 'talk_history_topic');

SET @hist_step = (SELECT `id` FROM `agent_workflow_step`
                   WHERE `workflow_id` = @talk_id AND `title` = 'Переменные: история' LIMIT 1);

-- ⚠ Третья строка дописывается в СУЩЕСТВУЮЩИЙ шаг, рядом с двумя соседними, —
-- новым шагом такое не заводят. Повтор прогона второй строки не добавит.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_ARRAY_APPEND(`metadata`, '$.variable_conversion',
           JSON_OBJECT('variable', 'talk_history_topic', 'text', '[<if talk_history_chat>]%talk_history_chat%
[<endif>][<if talk_history_mail>]%talk_history_mail%
[<endif>][<if prompt_user>]он: %prompt_user%[<endif>]'))
 WHERE `id` = @hist_step
   AND JSON_SEARCH(`metadata`, 'one', 'talk_history_topic') IS NULL;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.topic_action.history', 'talk_history_topic')
 WHERE `id` = @topic_step;

-- ── 9. Что стало ────────────────────────────────────────────────────────────

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_topic_question`
         WHERE `topic_id` = @topic_id) AS вопросов,
       (SELECT `tags_qty_accept` FROM `agent_workflow_topic`
         WHERE `id` = @topic_id) AS порог_меток,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @sub_id) AS шагов_подпотока,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.topic_action.history'))
          FROM `agent_workflow_step` WHERE `id` = @topic_step) AS история;
