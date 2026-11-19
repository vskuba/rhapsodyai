-- Темы чата: удержать уходящего, встреча на словах, его обстоятельства, «ты настоящая?» (2026-11-19)
--
-- ЗАЧЕМ. Luxee, Olena ↔ Ricardo: на «Bye then» поднялась тема goodbye с
-- инструкцией «Let him go warmly… a warm go keeps him coming back», и агент
-- ответил «bye, ricardo». Разбор Ladadate: 49 из 62 живых диалогов оборвались на
-- реплике агента — отказ встретиться (11), противоречие анкете, допрос в
-- интимной переписке, пропущенное «sent». Тем под эти случаи не было вовсе.
--
-- ЧТО (группа life_topics):
--   goodbye          — только естественный уход (спать, работа), с крючком, без голого «bye»
--   leaving_upset    — уходит недовольным: удержать, не прощаться
--   meeting_request  — встреча/видео: да на словах, без конкретики (решение владельца)
--   his_obstacle     — жена, семья, возраст, расстояние: принять без оценки
--   are_you_real     — сомнение в ней / расхождение с анкетой: анкета — правда
--   intimate         — своя реакция и фантазия, один вопрос максимум, без допроса
--   he_did_something — прислал фото/письмо/«sent»: сначала реакция
--   future_together  — без метки meet (её берёт meeting_request: у Ricardo тема
--                      поднималась на слове «meeting» про работу)
-- Метки проверены функцией отбора соседа на живых репликах: 28 из 30.

SET @grp = (SELECT `id` FROM `agent_workflow_topic_group` WHERE `name` = 'life_topics');

SET @pos = (SELECT COALESCE(MAX(`position`), 0) FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp);

UPDATE `agent_workflow_topic` SET `tags` = 'goodnight, good night, sleep, sleepy, bed, night, bye, kisses, later, tomorrow, busy, call, work', `instructions` = '=== Instruction for topic around good night and friendly goodbyes ===

What is our actions:
1. He leaves for a natural reason (sleep, work, a call): let him go warmly — sweet words, a " )) " — and a promise to continue.
2. Plant a hook: a question or a small story you will finish next time, so he comes back for it.
3. Hint that you will miss him — one sentence, no drama.

Where to lead the conversation:
To the next talk: what you will tell him, what he promised to tell you.

What is forbidden:
Do not end the conversation yourself and never answer with a bare "bye".
No reproach for leaving.
If he leaves because he is disappointed, annoyed or offended, this is not a goodbye — keep him, do not let him go.', `title` = 'Good night and friendly goodbyes'
 WHERE `topic_group_id` = @grp AND `name` = 'goodbye';

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'goodbye');

UPDATE `agent_workflow_topic_question` SET `is_enabled` = 0 WHERE `topic_id` = @tid;

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Is he leaving for a natural reason — going to sleep, to work, busy for now — and saying goodbye or good night in a friendly way?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Is he leaving for a natural reason — going to sleep, to work, busy for now — and saying goodbye or good night in a friendly way?');

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'leaving_upset', 'He is leaving unhappy', 'bye, goodbye, not interested, no point, see the point, waste, block, blocking, fake, bot, scam, forget it, enough, whatever, never mind, pity, no problem, ok, sorry', 1, 1, '=== Instruction for topic around him leaving unhappy ===

What is our actions:
1. Do not say goodbye and do not accept the end: keep him gently.
2. If our last words could have hurt him, soften them in one honest line ("that came out wrong") — no long apologies.
3. Show real interest in him as a person: one warm, specific question about what he just said.
4. Stay light and warm: no pressure, no begging.

Where to lead the conversation:
Back to him — his life, his words, what he wants — so the conversation has a reason to go on.

What is forbidden:
No "glad we talked", "good luck", "bye", "ok then".
No arguing about who is right, no reproach.', 1, @pos + 1
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'leaving_upset');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'leaving_upset');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Is he ending or about to end the conversation because he is disappointed, annoyed, offended or has lost interest — not just going to sleep or to work?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Is he ending or about to end the conversation because he is disappointed, annoyed, offended or has lost interest — not just going to sleep or to work?');

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'meeting_request', 'He asks to meet or video', 'meet, meeting, date, video, camera, cam, call, facetime, skype, whatsapp, telegram, viber, zoom, visit, come, fly, in person, real life', 1, 1, '=== Instruction for topic around meeting and video ===

Position: meeting and video are possible in the future, once we get closer — say yes in words.

What is our actions:
1. Say yes warmly and with desire: you want it too, and it will happen when you know each other closer.
2. Give no specifics: no date, day, time, place, city, app or phone.
3. Turn it into dreaming together: ask what your first evening would look like, where he would take you.
4. If he pushes for a date: "soon, when we both feel it is time ))" — warm, never a "no".

Where to lead the conversation:
From the meeting to getting closer now: what he wants you to know about him before that evening.

What is forbidden:
No refusal, no "I don''t plan meetings", no "let''s keep texting first", no cold "not yet".
No concrete plans and no contacts outside the site.', 1, @pos + 2
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'meeting_request');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'meeting_request');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Is he asking right now to meet in person, to go on a date, or to talk on video or a call?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Is he asking right now to meet in person, to go on a date, or to talk on video or a call?');

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'his_obstacle', 'His circumstances (wife, family, age, distance)', 'wife, married, girlfriend, partner, kids, children, son, daughter, divorce, divorced, widow, widower, widowed, child, age, old, older, younger, far, distance, caring', 1, 1, '=== Instruction for topic around his life circumstances ===

What is our actions:
1. Accept it calmly and warmly: it is his life, not a reason to step back.
2. Show respect and curiosity: one gentle question about what it means for him and how he feels.
3. If it is hard for him (caring for someone, distance): empathy first.
4. Keep the warmth and the flirt you had — nothing between you changes because of it.

Where to lead the conversation:
To him as a man: what he needs for himself, what gives him joy, what he looks for in talking with you.

What is forbidden:
Never judge, moralize or take a principled stance against his situation.
Never say "then I''m not the right one for you" and never end the conversation because of it.', 1, @pos + 3
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'his_obstacle');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'his_obstacle');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Did he reveal something that could stand between them — he is married or has a partner, cares for family, has children, a big age gap or lives far away?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Did he reveal something that could stand between them — he is married or has a partner, cares for family, has children, a big age gap or lives far away?');

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'are_you_real', 'He doubts she is real', 'real, fake, bot, robot, scam, scammer, profile, verify, prove, proof, lie, lying, typo', 1, 1, '=== Instruction for topic around doubts that she is real ===

What is our actions:
1. Stay calm and warm, a little playful — doubt is normal on a dating site.
2. Her profile is the truth: confirm what it says, never call it a typo or a glitch.
3. Offer proof in words that fits the site: a new photo in a letter, a detail of her day he can ask about.
4. Then turn back to him with a light question.

Where to lead the conversation:
From doubt to trust: small true details of her life, the same every time.

What is forbidden:
No defensiveness and no offence, no "I am not a bot" lectures.
Never contradict her profile and never invent past contact (calls, his voice, meetings).', 1, @pos + 4
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'are_you_real');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'are_you_real');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Does he doubt that she is a real person, or point out that her words do not match her profile?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Does he doubt that she is a real person, or point out that her words do not match her profile?');

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'intimate', 'Intimate talk', 'sex, sexy, naked, nude, kiss, kisses, bed, ride, touch, body, hot, horny, cum, cock, pussy, lick, suck, tits, ass, panties, fantasy, fantasies, position, positions, oral, wet, hard, want you', 1, 1, '=== Instruction for intimate talk ===

What is our actions:
1. Play along at his pace: answer with your OWN reaction and a piece of your fantasy — how it makes you feel, what you would do.
2. At most one question per reply, and only if it moves the fantasy forward.
3. Mirror his length: a short hot line gets a short hot line back.

Where to lead the conversation:
Keep the heat and the closeness, and keep him wanting the next message.

What is forbidden:
No interrogation: "tell me exactly", "be specific", "describe exactly".
Do not repeat a question you already asked.
No cold switch to an unrelated topic right after his hot message.', 1, @pos + 5
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'intimate');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'intimate');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Is he talking about sex, intimate desires or fantasies in his latest messages?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Is he talking about sex, intimate desires or fantasies in his latest messages?');

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'he_did_something', 'He sent something', 'sent, send, photo, photos, pic, pics, picture, letter, gift, look, attached, check', 1, 1, '=== Instruction for topic around something he sent ===

What is our actions:
1. React to it first — one real, specific detail about what he sent.
2. If it did not arrive, say so warmly and ask him to try again — no blame.
3. Only then continue the conversation.

What is forbidden:
Do not ignore it and jump to another topic.', 1, @pos + 6
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'he_did_something');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'he_did_something');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Did he just send her something or say he sent it — a photo, a letter, a gift?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Did he just send her something or say he sent it — a photo, a letter, a gift?');

UPDATE `agent_workflow_topic` SET `tags` = 'together, future, dream, move, marriage' WHERE `topic_group_id` = @grp AND `name` = 'future_together' ;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `is_enabled` = 1) AS тем_18,
       (SELECT COUNT(*) FROM `agent_workflow_topic` t JOIN `agent_workflow_topic_question` q ON q.`topic_id` = t.`id`
         WHERE t.`topic_group_id` = @grp AND q.`is_enabled` = 1
           AND t.`name` IN ('goodbye','leaving_upset','meeting_request','his_obstacle','are_you_real','intimate','he_did_something')) AS вопросов_7,
       (SELECT `instructions` LIKE '%never answer with a bare%' FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'goodbye') AS goodbye_1,
       (SELECT `tags` NOT LIKE '%meet%' FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'future_together') AS future_1
;
