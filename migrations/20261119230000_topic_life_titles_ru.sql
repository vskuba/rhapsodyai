-- Темы чата: русские заголовки у тем, заведённых 20261119220000 (2026-11-19)
--
-- ЗАЧЕМ. У остальных тем группы заголовки русские, у семи новых были английские.

SET @grp = (SELECT `id` FROM `agent_workflow_topic_group` WHERE `name` = 'life_topics');

UPDATE `agent_workflow_topic` SET `title` = 'Спокойной ночи и тёплое прощание' WHERE `topic_group_id` = @grp AND `name` = 'goodbye';

UPDATE `agent_workflow_topic` SET `title` = 'Уходит недовольным' WHERE `topic_group_id` = @grp AND `name` = 'leaving_upset';

UPDATE `agent_workflow_topic` SET `title` = 'Просит встречу или видео' WHERE `topic_group_id` = @grp AND `name` = 'meeting_request';

UPDATE `agent_workflow_topic` SET `title` = 'Его обстоятельства (жена, семья, возраст, расстояние)' WHERE `topic_group_id` = @grp AND `name` = 'his_obstacle';

UPDATE `agent_workflow_topic` SET `title` = 'Сомневается, что она настоящая' WHERE `topic_group_id` = @grp AND `name` = 'are_you_real';

UPDATE `agent_workflow_topic` SET `title` = 'Интимная переписка' WHERE `topic_group_id` = @grp AND `name` = 'intimate';

UPDATE `agent_workflow_topic` SET `title` = 'Он что-то прислал' WHERE `topic_group_id` = @grp AND `name` = 'he_did_something';

SELECT 'ПОСЛЕ' AS этап, (SELECT COUNT(*) FROM `agent_workflow_topic` WHERE `topic_group_id` = @grp AND `title` REGEXP '^[A-Za-z]') AS английских_0;
