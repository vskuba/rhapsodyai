-- Темы чата: просит почту, мессенджер или соцсети (2026-11-24)
--
-- ЗАЧЕМ. Собеседник просит личную почту, перейти в Telegram / WhatsApp / Viber
-- или дать Instagram и другие соцсети. Темы под это не было: просьба мессенджера
-- поднимала только meeting_request (метки whatsapp, telegram, viber), а та про
-- встречу и видео, не про контакты.
--
-- ЧТО (группа life_topics):
--   contacts_outside — мягко не соглашаться: на сайте ей спокойнее и безопаснее,
--                      сперва узнать друг друга лучше; без холодного «нет».

SET @grp = (SELECT `id` FROM `agent_workflow_topic_group` WHERE `name` = 'life_topics');

SET @pos = (SELECT COALESCE(MAX(`position`), 0) FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp);

INSERT INTO `agent_workflow_topic` (`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, `questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`)
SELECT @grp, 'contacts_outside', 'Просит почту, мессенджер или соцсети', 'email, e-mail, gmail, mail address, your mail, telegram, whatsapp, viber, signal, wechat, skype, messenger, instagram, insta, facebook, snapchat, tiktok, social, number, phone, contact, contacts, outside', 1, 1, '=== Instruction for topic around him asking for her email, messengers or social networks ===

Position: she does not move to email, messengers (Telegram, WhatsApp, Viber and others) or social networks (Instagram, Facebook and others) at the first acquaintance. On this dating site she feels safe and comfortable; to move elsewhere they first need to know each other better and talk more.

What is our actions:
1. Answer softly and warmly, with a smile " )) " — it is a pleasant sign that he wants to be closer, say so.
2. Explain in your own words: here on the site you feel calmer and safer, and you are not the kind of woman who gives contacts right after meeting someone.
3. Leave hope: when you know each other better, it will feel natural — "let''s talk more here first".
4. Turn back to him with one warm, specific question so the conversation goes on.

Where to lead the conversation:
To getting to know each other here and now: his life, his words, what he wants you to know about him.

What is forbidden:
Never give an email, phone number, messenger, nickname or social network account, and never promise a date or condition for it.
No cold "no", no lecture about rules or scammers, no reproach for asking.
Do not end the conversation because of his request.', 1, @pos + 1
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'contacts_outside');

SET @tid = (SELECT `id` FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'contacts_outside');

INSERT INTO `agent_workflow_topic_question` (`topic_id`, `question`, `is_enabled`, `position`)
SELECT @tid, 'Is he asking for her email, phone number, messenger (Telegram, WhatsApp, Viber or other) or social network (Instagram, Facebook or other), or asking to move the conversation off this site?', 1, 10
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `question` = 'Is he asking for her email, phone number, messenger (Telegram, WhatsApp, Viber or other) or social network (Instagram, Facebook or other), or asking to move the conversation off this site?');

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `name` = 'contacts_outside' AND `is_enabled` = 1) AS тема_1,
       (SELECT COUNT(*) FROM `agent_workflow_topic_question` WHERE `topic_id` = @tid AND `is_enabled` = 1) AS вопросов_1
;
