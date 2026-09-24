-- Карточки зовутся так же, как везде: `*_bio`, а не `*_card` (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- Одно и то же — «что известно о человеке» — звалось в проекте двумя именами:
--
--     dating_talk           companion_bio, girl_bio
--     dating_mail_question  companion_card, girl_card
--     dating_mail_vars      girl_card
--
-- Разница только в имени: содержимое собирают соседние функции DatingAi из тех
-- же полей анкеты. А цена разных имён — настоящая: правя промпт почты, легко
-- написать по привычке `%companion_bio%`, и метка молча останется в тексте.
-- Модель прочитает её словами и ответит наугад; ошибка видна только в
-- отрисованном промпте.
--
-- ## Что меняется
--
-- Связь workflow с переменной и сама метка в промпте. Значения продолжает
-- слать панель — правка DatingAi едет вместе с этой миграцией, и порядок
-- значим: пока панель шлёт старое имя, ручка ответит `400` «не объявлена».
--
-- ⚠ Форма значения не меняется: `girl_bio` у `dating_talk` — связный рассказ,
-- у почты — строки с подписями («Имя: …», «Возраст: …»). Разные формы под одним
-- именем законны: имя отвечает на вопрос «о ком», а не «как отформатировано».
--
-- ## ⚠ Старые переменные не удаляем
--
-- `girl_card` остаётся у `dating_mail_write` — там она **объявлена, но не
-- читается ни одним промптом**, и это отдельная недоделка. Снеси мы её заодно,
-- панель получила бы `400` на письмах, а разбираться пришлось бы в двух правках
-- сразу.

SET @q = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_question');
SET @v = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_vars');
SET @girl_card = (SELECT `id` FROM `agent_workflow_variable` WHERE `name` = 'girl_card');
SET @girl_bio = (SELECT `id` FROM `agent_workflow_variable` WHERE `name` = 'girl_bio');
SET @comp_card = (SELECT `id` FROM `agent_workflow_variable` WHERE `name` = 'companion_card');
SET @comp_bio = (SELECT `id` FROM `agent_workflow_variable` WHERE `name` = 'companion_bio');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
         WHERE s.`workflow_id` IN (@q, @v)
           AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`, '$.prompt_user'))
               LIKE '%\_card\%%') AS меток_card;

-- ── Связи: вместо карточек — анкеты ─────────────────────────────────────────
--
-- ⚠⚠ Связь **заводим до того, как убрать старую**. Порядок наоборот оставил бы
-- окно, в котором промпт уже просит `girl_bio`, а объявления ещё нет: вызов в
-- эту секунду получил бы `400`. Миграции применяют на живой базе.
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT one.`vid`, one.`wid` FROM (
        SELECT @girl_bio AS vid, @q AS wid
  UNION SELECT @girl_bio, @v
  UNION SELECT @comp_bio, @q) AS one
 WHERE one.`vid` IS NOT NULL AND one.`wid` IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_variable_workflow`) x
                    WHERE x.`variable_id` = one.`vid` AND x.`workflow_id` = one.`wid`);

DELETE FROM `agent_workflow_variable_workflow`
 WHERE (`variable_id` = @girl_card AND `workflow_id` IN (@q, @v))
    OR (`variable_id` = @comp_card AND `workflow_id` = @q);

-- ── Метки в промптах ────────────────────────────────────────────────────────
--
-- ⚠ Заменяем **вместе с процентами**: `%girl_card%` — метка целиком, а голое
-- `girl_card` встречается и в пояснениях к ней. Замена без процентов испортила
-- бы текст, который читает человек.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 '%girl_card%', '%girl_bio%'),
                 '%companion_card%', '%companion_bio%'))
 WHERE `workflow_id` IN (@q, @v)
   AND `metadata` IS NOT NULL AND `metadata` <> '' AND JSON_VALID(`metadata`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
         WHERE s.`workflow_id` IN (@q, @v)
           AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`, '$.prompt_user'))
               LIKE '%\_card\%%') AS меток_card_осталось,
       (SELECT COUNT(*) FROM `agent_workflow_step` s
         WHERE s.`workflow_id` IN (@q, @v)
           AND JSON_UNQUOTE(JSON_EXTRACT(s.`metadata`, '$.prompt_user'))
               LIKE '%\%girl\_bio\%%') AS шагов_с_girl_bio,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` IN (@girl_bio, @comp_bio)
           AND `workflow_id` IN (@q, @v)) AS связей_заведено,
       (SELECT COUNT(*) FROM `agent_workflow_variable_workflow`
         WHERE `variable_id` IN (@girl_card, @comp_card)
           AND `workflow_id` IN (@q, @v)) AS связей_со_старым;
