-- intention_context: судья бракует письмо к обещанному фото, если оно описывает снимок (2026-11-21)
--
-- ЗАЧЕМ. Письмо пишется раньше, чем выбран снимок: снимок подбирает DatingAi
-- по приметам (тегам), а цвета и детали одежды в тегах нет. Промпт просит не
-- описывать снимок, но модель описывает: Olena → Donnie, 21.11.2026, письмо
-- обещало «sleek black dress», а ушёл снимок в тёмно-зелёном вечернем платье.
--
-- ЧТО. Сразу за «Письмо и приметы снимка» два шага:
--   * «Судья: письмо описывает снимок?» — yes / no. Описание — одежда и её
--     цвет, причёска, место и фон, поза, свет. Само «вот фото», её чувства,
--     стеснение, надежда, что понравится, — не описание.
--   * «Письмо: убрать описание снимка» — **всегда**: модель пишет письмо
--     заново, 2–5 фраз, не видя снимка. Судья обхода не даёт и остаётся в
--     трассе отметкой «было ли описание»: на замере он пропустил 2 описания из
--     4 («light hit the river», «dressed up, studio light»), а переписчик
--     чистил 2 из 2 — решение владельца 21.11.2026 «всегда переписывай».
-- ⚠ Без цикла переписываний: правка одна и окончательная, ей не на чем
-- зациклиться (грабля «Давай» — 300 шагов на письмах — здесь не повторится).
-- ⚠ Повторный прогон безопасен: шаги и переменная заводятся под условием.

SET @ic = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'intention_context');
SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @ic AND `title` = 'Судья: письмо описывает снимок?');
SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `workflow_id` = @ic AND `title` = 'Письмо и приметы снимка');
SET @rewrite = '{"prompt_user": "[<if talk_history_chat>]=== Chat with %companion_title% ===\\n    %talk_history_chat%\\n[<endif>]\\n=== Her first draft of the letter ===\\n%intention_letter%\\n\\nThe draft describes what is in the photo, and that is forbidden: the photo is chosen AFTER the letter, so any detail may be wrong — he would see a green dress where the letter promised a black one.\\n\\nWrite the letter ANEW, in her own voice, 2 to 5 sentences:\\n- she kept her promise and here is the photo,\\n- how she feels sending it (shy, excited, playful),\\n- one warm line or question about him, from the chat above.\\n\\n⚠⚠ FORBIDDEN: any word about what the photo shows — no clothes, no shoes, no colours, no hair, no place (no kitchen, river, window, room, street, studio), no light, no time of day, no pose, nothing she holds or does in the picture. Write as if you have NOT seen the photo.\\n⚠ Keep the paragraph marker [P] where paragraphs end. Never put a real line break inside the letter. Never use a double quote inside the letter — use single quotes.\\n\\nReturn only a JSON object: {\\"intention_letter\\": \\"the new letter, in English\\"}", "llm_to_json_variable": [{"variable": "intention_letter", "text": "the new letter, with no word about what the photo shows"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}';

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @ic, 'letter_describes', 'workflow', '', 'Судья письма к фото: yes — письмо описывает снимок словами, no — нет'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @ic AND `name` = 'letter_describes');

UPDATE `agent_workflow_step` SET `position` = `position` + 2
 WHERE `workflow_id` = @ic AND `position` >= @pos AND @has = 0 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @ic, 2, 'Судья: письмо описывает снимок?', @pos,
       CAST(CONCAT('{"prompt_user": "=== Her letter that goes with a photo of her ===\\n%intention_letter%\\n\\nThe photo is chosen AFTER the letter is written, so the letter must not say what is in the photo. Does the letter describe what is IN the photo?\\n\\nyes — it names or describes any of: her clothes or their colour, her hair, the place or background (kitchen, river, walk, window, room, studio, street), her pose, the light or time of day in the picture (studio light, morning light, evening), what she is holding or doing in it (tea, coffee, a mug, cooking). Even one such word means yes.\\nno — it only says that a photo is attached, how she feels about sending it (shy, excited), that she hopes he likes it, or talks about other things.\\n\\nReturn only a JSON object: {\\"letter_describes\\": \\"yes or no\\"}", "llm_to_json_variable": [{"variable": "letter_describes", "text": "yes or no, lowercase"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}') AS JSON)
 WHERE @has = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @ic, 2, 'Письмо: убрать описание снимка', @pos + 1,
       CAST(@rewrite AS JSON)
 WHERE @has = 0;

-- Промпт переписчика — и тем, у кого шаг уже заведён первой редакцией.
UPDATE `agent_workflow_step` SET `metadata` = CAST(@rewrite AS JSON)
 WHERE `workflow_id` = @ic AND `title` = 'Письмо: убрать описание снимка'
   AND `metadata` NOT LIKE '%Write as if you have NOT seen the photo%';

-- Судья обхода не даёт: письмо всегда идёт в переписчик.
UPDATE `agent_workflow_step` SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY())
 WHERE `workflow_id` = @ic AND `title` = 'Судья: письмо описывает снимок?'
   AND JSON_LENGTH(JSON_EXTRACT(`metadata`, '$.transitions_after')) > 0;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @ic AND `position` BETWEEN @pos - 1 AND @pos + 2) AS порядок;
