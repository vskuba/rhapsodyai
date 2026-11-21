-- dating_talk: фото-подарок — девушке просто захотелось прислать снимок (2026-11-21)
--
-- ЗАЧЕМ. Обещанное фото (she_promised_send_photo) появляется, когда тема
-- зашла о снимках. Живая девушка шлёт фото и просто так, подарком. Решение
-- владельца: намерение she_just_send_photo — после 2–3 его сообщений, 30%.
--
-- ЧТО. Решают двое:
--   * DatingAi — **можно ли** (медиа открыто, пределы, его сообщения, есть
--     невиданный снимок): входная переменная photo_gift_due = 1 / 0;
--   * здесь — **хочется ли**: доля dice_photo_gift (30%) в шаге «Жребий».
--     ⚠ Доля одна и только здесь: в двух местах доли уже складывались.
-- Выпало — писатель добавляет короткую строку о снимке, судья её не бракует,
-- а после «Ветки намерений» кладётся метка she_just_send_photo. Подпоток
-- intention_context подбирает к ней приметы снимка (теги), снимок уходит
-- **вместе с этим ответом** одним сообщением — это делает DatingAi.
--
-- ⚠ Порядок выкладки: сперва эта миграция, потом DatingAi — присланная
-- необъявленная переменная отвечает 400 на весь прогон.
-- ⚠ Повторный прогон безопасен: каждая правка стоит под своим условием.

SET @tw = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @ic = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'intention_context');

-- ── Переменные ────────────────────────────────────────────────────────────────
INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'photo_gift_due', 'input', '0', 'Фото-подарок можно: 1 — DatingAi проверил медиа, пределы и галерею, 0 — нельзя'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'photo_gift_due');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'dice_photo_gift', 'workflow', '', 'Жребий подарка: yes — девушке захотелось прислать снимок'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'dice_photo_gift');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'photo_gift', 'workflow', '', 'Подарок в этом ответе: 1 — снимок уходит вместе с ответом'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'photo_gift');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @tw, 'photo_gift_intention', 'workflow', '', 'Метка подарка для chat_intention_add, пусто — подарка нет'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @tw AND `name` = 'photo_gift_intention');

INSERT INTO `agent_workflow_variable` (`workflow_id`, `name`, `type`, `default`, `description`)
SELECT @ic, 'girl_response', 'input', '', 'Её ответ, к которому прикладывается подарок'
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable` WHERE `workflow_id` = @ic AND `name` = 'girl_response');

-- ── Доля в «Жребии» ───────────────────────────────────────────────────────────
UPDATE `agent_workflow_variable`
   SET `default` = CAST(JSON_SET(CAST(`default` AS JSON), '$.dice_photo_gift', CAST('{"yes": 30, "no": 70}' AS JSON)) AS CHAR)
 WHERE `workflow_id` = @tw AND `name` = 'dice_talk_spec' AND `default` NOT LIKE '%dice_photo_gift%';

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.tool_invoke.outputs_map.dice_photo_gift', 'dice_photo_gift')
 WHERE `workflow_id` = @tw AND `title` = 'Жребий' AND `metadata` NOT LIKE '%dice_photo_gift%';

-- ── Шаг «Подарок фото?» — сразу после «Жребия» ────────────────────────────────
SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Подарок фото?');
SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Жребий');

UPDATE `agent_workflow_step` SET `position` = `position` + 1
 WHERE `workflow_id` = @tw AND `position` >= @pos AND @has = 0 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 5, 'Подарок фото?', @pos,
       CAST('{"variable_conversion": [{"variable": "photo_gift", "text": "[<if photo_gift_due == 1 and dice_photo_gift == ''yes'' and !make_initiative and !mail_mode>]1[<endif>]"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE @has = 0;

-- ── Писатель ответа: строка о снимке ──────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '=== What you need ===',
                 CONCAT('[<if photo_gift>]=== A photo goes with this message ===
She is attaching a photo of herself to this very message — a small gift, just because she felt like it. He did not ask for it.
- still answer his message first,
- weave in one short, natural line about the photo in her own voice (for example: a little something from my day), not a separate announcement;
- do not describe what is in the photo — he will see it himself.

[<endif>]', '=== What you need ===')))
 WHERE `workflow_id` = @tw AND `title` = 'Ответ в чат' AND `metadata` NOT LIKE '%=== A photo goes with this message ===%';

-- ── Судья: строку о снимке не бракует ─────────────────────────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')), '        girl_response_skip = 0 also when he says goodbye, gets upset or seems to be leaving — a reply that warmly keeps him is needed, silence lets the conversation die.
',
                 CONCAT('        girl_response_skip = 0 also when he says goodbye, gets upset or seems to be leaving — a reply that warmly keeps him is needed, silence lets the conversation die.
', '[<if photo_gift>]        girl_response_skip = 0 ALWAYS here: a photo of her goes with this reply as a gift — a short line about the photo is expected, never reject a draft for mentioning it.
[<endif>]')))
 WHERE `workflow_id` = @tw AND `title` = 'Валидация ответа' AND `metadata` NOT LIKE '%a photo of her goes with this reply as a gift%';

-- ── После «Ветки намерений»: метка подарка ────────────────────────────────────
SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Подарок: метка');
SET @pos = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Ветка намерений');

UPDATE `agent_workflow_step` SET `position` = `position` + 2
 WHERE `workflow_id` = @tw AND `position` >= @pos AND @has = 0 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 5, 'Подарок: метка', @pos,
       CAST('{"variable_conversion": [{"variable": "photo_gift_intention", "text": "[<if photo_gift>]she_just_send_photo[<endif>]"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE @has = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @tw, 3, 'Подарок: намерение', @pos + 1,
       CAST('{"tool_invoke": {"tool_name": "chat_intention_add", "inputs_map": {"intention": "photo_gift_intention", "owner_unique_id": "girl_unique_id", "companion_unique_id": "companion_unique_id"}, "outputs_map": {}}, "transitions_before": [{"variable": "photo_gift_intention", "operator": "empty", "value": "", "step_id": "{{NEXT}}"}], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE @has = 0;

-- Пустая метка — шаг пропускается: переход на следующий за ним.
SET @gift = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw AND `title` = 'Подарок: намерение');
SET @after = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @tw
               AND `position` = (SELECT `position` + 1 FROM `agent_workflow_step` WHERE `id` = @gift));
UPDATE `agent_workflow_step`
   SET `metadata` = CAST(REPLACE(CAST(`metadata` AS CHAR), '"{{NEXT}}"', CONCAT('"', @after, '"')) AS JSON)
 WHERE `id` = @gift AND `metadata` LIKE '%{{NEXT}}%';

-- Подпоток контекста получает её ответ: приметы подарка подбираются к нему.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.workflow_invoke.inputs_map.girl_response', 'girl_response')
 WHERE `workflow_id` = @tw AND `title` = 'Намерение контекст'
   AND JSON_EXTRACT(`metadata`, '$.workflow_invoke.inputs_map.girl_response') IS NULL;

-- ── intention_context: ветка подарка ──────────────────────────────────────────
SET @has = (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @ic AND `title` = 'Подарок: приметы снимка');
SET @name = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @ic AND `title` = 'Имя намерения');
SET @pos = (SELECT `position` FROM `agent_workflow_step` WHERE `id` = @name);

-- ⚠ История прежде проваливалась в «Имя намерения» следующим шагом, теперь
-- между ними ветка подарка, и переход ставится явно, как у ветки фото.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(JSON_SET(`metadata`, '$.to_next_step', CAST('false' AS JSON)),
                             '$.transitions_after',
                             CAST(CONCAT('[{"variable": "intention_context", "operator": "not_empty", "value": "", "step_id": "', @name, '"}]') AS JSON))
 WHERE `workflow_id` = @ic AND `title` = 'Контекст: собрать историю' AND @has = 0;

UPDATE `agent_workflow_step` SET `position` = `position` + 2
 WHERE `workflow_id` = @ic AND `position` >= @pos AND @has = 0 ORDER BY `position` DESC;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @ic, 2, 'Подарок: приметы снимка', @pos,
       CAST('{"prompt_user": "[<if talk_history_chat>]=== Chat with %companion_title% ===\\n    %talk_history_chat%\\n[<endif>]\\n=== Her message that goes with the photo ===\\n%girl_response%\\n\\nShe is attaching a photo of herself to this message as a small gift — he did not ask for it. Pick the tags to choose that photo by: something that fits her message and the mood of the conversation, and that a woman would send as a friendly gift.\\n\\n⚠ Never lingerie, nude, bedroom or sensual — this is a gift from her open album, not an intimate photo.\\n\\n⚠ Return **only a JSON object**:\\n{\\n  \\"intention_tags\\": \\"2 to 4 comma-separated tags, only from the list below\\"\\n}\\n\\nTags allowed, word for word: dress, swimsuit, casual, sportswear, evening-wear, coat, portrait, half-body, full-body, close-up, selfie, indoor, outdoor, studio, kitchen, beach, nature, city, car, gym, cafe, smiling, serious, playful, confident, shy, dreamy, daylight, evening, night, studio-light, group, with-pet, mirror, sitting, standing", "llm_to_json_variable": [{"variable": "intention_tags", "text": "2 to 4 tags to pick the gift photo by, comma-separated, only from the allowed list"}], "transitions_before": [], "transitions_after": [], "to_next_step": true}' AS JSON)
 WHERE @has = 0;

INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @ic, 5, 'Контекст: собрать подарок', @pos + 1,
       CAST(CONCAT('{"variable_conversion": [{"variable": "intention_context", "text": "{\\"tags\\": \\"%intention_tags%\\"}"}], "transitions_before": [], "transitions_after": [{"variable": "intention_context", "operator": "not_empty", "value": "", "step_id": "', @name, '"}], "to_next_step": false}') AS JSON)
 WHERE @has = 0;

SET @tags = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @ic AND `title` = 'Подарок: приметы снимка');
SET @get = (SELECT `id` FROM `agent_workflow_step` WHERE `workflow_id` = @ic AND `title` = 'Намерение: какое сейчас');

-- Развилка подпотока: подарок — в свою ветку, раньше общего «прочее».
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_ARRAY_INSERT(`metadata`, '$.transitions_after[3]',
         CAST(CONCAT('{"variable": "chat_intention_get_', @get, '_result_intention", "operator": "==", "value": "she_just_send_photo", "step_id": "', @tags, '"}') AS JSON))
 WHERE `workflow_id` = @ic AND `title` = 'Ветка намерения' AND `metadata` NOT LIKE '%she_just_send_photo%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @tw AND `title` IN ('Жребий', 'Подарок фото?', 'Ветка намерений', 'Подарок: метка', 'Подарок: намерение', 'Намерение контекст')) AS talk,
       (SELECT GROUP_CONCAT(`title` ORDER BY `position` SEPARATOR ' > ') FROM `agent_workflow_step`
         WHERE `workflow_id` = @ic) AS ctx;
