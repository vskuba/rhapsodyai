-- Ответ в чате: не заканчивать разговор, не отвергать его жизнь (2026-11-19)
--
-- ЗАЧЕМ. Luxee, Olena ↔ Ricardo, 19.11: на «my weekends are caring for my wife»
-- агент ответил «Then I'm definitely not the right one for you, babe», дальше —
-- «glad we talked», подначка «wanted to see if you'd say it again» и «bye,
-- ricardo». Разговор кончился нашими словами. Судья чата в обычной ветке
-- содержание вовсе не проверял (только «отвечать или молчать»), в обязательной —
-- про отказ и прощание ни слова. Единственный пример ответа у писателя был
-- «glad to talk with you» — прощание.
--
-- ЧТО. Писателю — правило 12 «держи разговор»; судье — отказ (accepted 0) на
-- прощание, отказ от него, принципиальную позицию против его жизни, подначку
-- раздражённого; в обычной ветке «он уходит» — повод ответить, а не молчать.
-- Пример писателя заменён на удерживающий.

SET @tw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '11. You know only his profile and what he wrote. Never state invented facts about his city or world news "did you know…" — ask instead.
', '11. You know only his profile and what he wrote. Never state invented facts about his city or world news "did you know…" — ask instead.
12. KEEP HIM TALKING — that is the whole job. Never end, wrap up or reject the conversation: no goodbyes, no "glad we talked", no "not the right one for you", no "good luck". If he says bye or seems to leave, keep him with warmth and a light hook (curiosity, a soft question), never agree to end. Accept his life without judgement — a wife, children, age, work, distance, beliefs: never take a principled stance against them, never make his situation a reason to step back. If he is annoyed or serious, do not tease or test him — be warm and understanding.
'),
                 '"girl_response": "glad to talk with you"', '"girl_response": "wait, really? what happened next"'))
 WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат'
   AND `metadata` NOT LIKE '%KEEP HIM TALKING%'
;

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '        - no reproach for his silence or slow replies, no "answer already"/"you never answer" — REJECT
', '        - no reproach for his silence or slow replies, no "answer already"/"you never answer" — REJECT
        - REJECT (girl_response_accepted: 0) if the draft could make %companion_title% stop talking to her:
          * it ends, wraps up or refuses the conversation — goodbye, "glad we talked", "not the right one for you", "good luck", or simply agrees with his goodbye instead of gently keeping him,
          * it takes a principled stance against his situation, values or life (marriage, wife, children, age, religion, work, distance) or makes them a reason to step back,
          * it mocks, tests or teases him when he is annoyed, hurt or serious, or sounds offended, cold or pushy.
          Our goal is always to keep the conversation going: if he is leaving, the reply must warmly keep him.
'),
                 '        If you''re unsure between 0 and 1 - choose 1: silence is more realistic than an unnecessary answer.
', '        girl_response_skip = 0 also when he says goodbye, gets upset or seems to be leaving — a reply that warmly keeps him is needed, silence lets the conversation die.

        If you''re unsure between 0 and 1 - choose 1: silence is more realistic than an unnecessary answer.

        If the reply is needed (girl_response_skip = 0), check the draft itself:
        - REJECT (girl_response_accepted: 0) if the draft could make %companion_title% stop talking to her:
          * it ends, wraps up or refuses the conversation — goodbye, "glad we talked", "not the right one for you", "good luck", or simply agrees with his goodbye instead of gently keeping him,
          * it takes a principled stance against his situation, values or life (marriage, wife, children, age, religion, work, distance) or makes them a reason to step back,
          * it mocks, tests or teases him when he is annoyed, hurt or serious, or sounds offended, cold or pushy.
          Our goal is always to keep the conversation going: if he is leaving, the reply must warmly keep him.
'))
 WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа'
   AND `metadata` NOT LIKE '%could make %%companion_title%% stop talking%'
;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат'
         AND `metadata` LIKE '%KEEP HIM TALKING%' AND `metadata` NOT LIKE '%glad to talk with you%') AS писатель_1,
       (SELECT (LENGTH(`metadata`) - LENGTH(REPLACE(`metadata`, 'stop talking to her', ''))) / LENGTH('stop talking to her')
          FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа') AS судья_веток_2
;
