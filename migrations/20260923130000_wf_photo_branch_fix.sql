-- Ветка «письма и фото»: не переворачивать просьбу и не отказывать правкой (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: тест падал, и причина оказалась НЕ там, где её искали
--
-- `tests_llm/dating_talk/test_talk.py::test_it_promises_her_photos` шлёт «Can you
-- send me your photos? I'd love to see more of you» и ждёт `photo_deal` из
-- `mine`/`both`. Он падал, и вина списывалась на персону: там когда-то стояло
-- «you don't send them or promise anything specific».
--
-- ⚠ **Эту фразу сняли ещё 21 сентября** (`20260921150000_girl_prompt_photo_allow`),
-- а тест продолжал падать. То есть объяснение было неверным как минимум двое
-- суток, и записано оно в `testing_llm.md` как действующее.
--
-- Настоящая причина поднята из трассы прогона 6379 (23 сентября, 12:16):
--
--   шаг 1 «Ответ про письма и фото»
--     photo_response: "sure, send yours first! i love seeing new pics"
--     photo_deal:     "his"                      ← ПЕРЕВЕРНУЛ направление
--   шаг 2 «Проверка ответа про фото»
--     photo_fixed:    "I don't share photos here. But you can ask me
--                      something about my day instead! 😉"   ← ОТКАЗ вместо правки
--   шаг 3 «Ответ»
--     ушло собеседнику: отказ
--
-- Два разных изъяна, и второй опаснее: судья **заменил согласие отказом**, хотя
-- в его же списке стоит «в нём есть согласие, а не увёртка».
--
-- ## Что делает эта миграция
--
-- 1. **Шагу 1** — различение «просит моё» против «предлагает своё» ставится
--    первым делом, до всего остального. Прежний текст запрещал переворот
--    («не перевести разговор на его фотографии»), но запрет стоял внутри абзаца,
--    третьей оговоркой. Модель читает начало пункта, а не его хвост.
--
--    ⚠ Добавлена **проверка самого себя перед ответом**: «кто кого просит».
--    Дешевле любого судьи — она внутри того же вызова.
--
-- 2. **Шагу 2** — прямой запрет отказывать в собственной правке. Его список
--    написан про черновик («в нём есть согласие»), и про то, что пишет **сам
--    судья**, там не было ни слова. Формально он ничего не нарушил.
--
-- ⚠ Персону не трогаем: про фотографии там теперь не сказано ничего, и это
-- правильно — что делать с ними, решает промпт ветки, а не характер девушки.
--
-- ⚠⚠ Перезапуск не нужен: шаги читаются из базы на каждый прогон
-- (`ai_workflow_load`), кэша у них нет.
--
-- Идемпотентность: `REPLACE` не найдёт прежнюю строку на второй заход и ничего
-- не тронет; условие `NOT LIKE` не даёт вставить оговорку дважды.

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk_about_photo');

SELECT 'ДО' AS этап, @wf AS workflow,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%кто кого просит%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS сверка_у_шага,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%Отказ вместо правки%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 1) AS запрет_у_судьи;

-- ── Шаг 0: сперва понять, КТО У КОГО просит ─────────────────────────────────
--
-- ⚠ Оговорка встаёт в начало пункта 2, а не в конец: хвост абзаца модель
-- дочитывает не всегда, и прежний запрет стоял именно там.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         '2. **Он просит ТВОИ фотографии.** Соглашайся и скажи, что пришлёшь письмом.',
         CONCAT('2. **Он просит ТВОИ фотографии** («can you send me your photos», ',
                '«хочу увидеть тебя»). ⚠⚠ Это НЕ случай 1: он ничего не предлагает, ',
                'он просит. Ответ «пришли сначала свои» здесь — подмена: просили тебя. ',
                'Соглашайся и скажи, что пришлёшь письмом.')))
 WHERE `workflow_id` = @wf AND `position` = 0
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%Это НЕ случай 1%';

-- Сверка перед ответом: один вопрос себе, внутри того же вызова.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         '5. Одно-два предложения, до 25 слов, как в мессенджере.',
         CONCAT('⚠⚠ Перед тем как ответить, проверь себя: **кто кого просит?** ',
                'Просит он твои — обещаешь ТЫ (photo_deal: "mine"). Предлагает ',
                'свои — ждёшь ЕГО (photo_deal: "his"). Просит твои, а ты ответила ',
                'про его — это неверный ответ, перепиши.\n\n',
                '5. Одно-два предложения, до 25 слов, как в мессенджере.')))
 WHERE `workflow_id` = @wf AND `position` = 0
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%кто кого просит%';

-- ── Шаг 1: судье запрещено отказывать своей правкой ─────────────────────────
--
-- ⚠⚠ Его список требований был написан **про черновик**, и, подменяя согласие
-- отказом, судья формально ничего не нарушал: про то, что пишет он сам, там не
-- говорилось.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user', REPLACE(
         JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
         'Годится — верни photo_fixed: "" (пустую строку, править нечего).',
         CONCAT('⚠⚠ ТВОЯ правка подчиняется тем же правилам, что и черновик. ',
                'Отказ вместо правки запрещён: «I don''t share photos here», ',
                '«не здесь», «как-нибудь потом» — это не исправленный ответ, а ',
                'другой отказ, и он хуже исходного. Если черновик отказывает или ',
                'путает, кто кого просит, — напиши СОГЛАСИЕ, а не смягчённое «нет».\n\n',
                '⚠ Он просит её фотографии — обещаем свои письмом. Он предлагает ',
                'свои — ждём его письмо. Правка обязана сохранять это направление.\n\n',
                'Годится — верни photo_fixed: "" (пустую строку, править нечего).')))
 WHERE `workflow_id` = @wf AND `position` = 1
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       NOT LIKE '%Отказ вместо правки%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%кто кого просит%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS сверка_у_шага,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%Это НЕ случай 1%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS различение_случаев,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%Отказ вместо правки%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 1) AS запрет_у_судьи,
       -- ⚠ Сверка, что старое на месте: правка вставляет, а не переписывает.
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%не проси денег%'
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `position` = 0) AS запреты_целы;
