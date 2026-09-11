-- Workflow «ответ на письмо» — `dating_mail_reply` (2026-09-09)
--
-- ЗАЧЕМ. Девушкам пишут, и на письма надо отвечать. Пул ответов в DatingAi уже есть,
-- наполнять его нечем: агента, который пишет ответ, не существует.
--
-- ⚠ ЧЕТВЁРТЫЙ WORKFLOW ПИСЕМ, И У КАЖДОГО СВОЁ ДЕЛО. У агента один workflow, и
-- заниматься двумя занятиями он не может:
--
--   `dating_mail_vars`     — заполняет переменные анкеты;
--   `dating_mail_write`    — пишет ШАБЛОН рассылки: без адресата, без имён;
--   `dating_mail_question` — сочиняет один вопрос про интересы получателя;
--   `dating_mail_reply`    — отвечает на конкретное письмо конкретного человека.
--
-- Последние два похожи только на первый взгляд. Вопрос сочиняется **до** знакомства,
-- по профилю, и встаёт внутрь шаблона; ответ пишется **после** — на живой текст, с
-- историей переписки перед глазами.
--
-- ⚠ ЗДЕСЬ, В ОТЛИЧИЕ ОТ ШАБЛОНА, КОНКРЕТИКА НУЖНА. `dating_mail_write` нарочно не
-- получает ни анкеты, ни собеседника: шаблон пишут для всех, и «Diana из Kyiv» в нём
-- делает его годным одной анкете из сорока. Ответ же адресован одному человеку —
-- имена, город и то, о чём он спросил, здесь не лишнее, а суть.
--
-- ⚠ ИСТОРИЯ — НЕ БОЛЬШЕ ПОСЛЕДНИХ N ПИСЕМ, и режет её вызывающий (настройка сайта
-- «Письма: ответ на базе последних N писем»). Причина не в стоимости: переписка на
-- сорок писем не помещается в осмысленный промпт, а модель, получив её целиком,
-- отвечает на первое попавшееся, а не на последнее.

SET @node = (SELECT `id` FROM `node` WHERE `name` = 'Dating' LIMIT 1);

SELECT 'ДО' AS этап, @node AS узел,
       (SELECT COUNT(*) FROM `agent_workflow` WHERE `name` = 'dating_mail_reply') AS есть_уже;

INSERT INTO `agent_workflow` (`node_id`, `name`, `title`, `description`, `position`, `subflow`)
SELECT @node, 'dating_mail_reply', 'Ответ на письмо',
       'Пишет ответ на письмо мужчины по истории переписки (последние N писем), анкете девушки и карточке собеседника',
       0, 0
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `id` FROM `agent_workflow`
                                   WHERE `name` = 'dating_mail_reply') AS x);

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_mail_reply');

-- ── Шаг 1: сам ответ ─────────────────────────────────────────────────────────
--
-- ⚠ `CHAR(10 USING utf8mb4)`, а не `CHAR(10)`: без набора MySQL отдаёт VARBINARY, и
-- склейка превращает строку в двоичную — наружу она уезжает как `base64:type251:`.
-- Грабли известные, поймано на `dating_mail_write`.
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 2, 'Ответ', 0, CAST(CONCAT('{"prompt_user": ', JSON_QUOTE(CONCAT(
    '%if reply_hint%НЕ ГОДИТСЯ: %reply_hint%', CHAR(10 USING utf8mb4),
    'Перепиши, устранив это.', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '%endif%Ты пишешь ОТВЕТ на письмо мужчины с сайта знакомств. Отвечает девушка, от её имени.',
    CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '=== Переписка (старые сверху, последнее письмо — внизу) ===', CHAR(10 USING utf8mb4),
    '%mail_history%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '=== Кто отвечает ===', CHAR(10 USING utf8mb4),
    '%girl_card%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    '=== Кому отвечает ===', CHAR(10 USING utf8mb4),
    '%companion_card%', CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    'Правила:', CHAR(10 USING utf8mb4),
    '1. Отвечай на ПОСЛЕДНЕЕ письмо. Прежние — только затем, чтобы не повторять уже сказанное и не спрашивать о том, что он уже рассказал.',
    CHAR(10 USING utf8mb4),
    '2. Язык ответа: %user_language%.', CHAR(10 USING utf8mb4),
    '3. Два-три коротких абзаца. Это переписка, а не письмо-знакомство: длинный ответ на короткое письмо выглядит заготовкой.',
    CHAR(10 USING utf8mb4),
    '4. Ответь на то, о чём он спросил или рассказал, — прямо, а не общими словами. Если он написал «Moto is my life», ответ про погоду означает, что письмо не прочли.',
    CHAR(10 USING utf8mb4),
    '5. Один вопрос в конце — чтобы разговор продолжился. Не три: анкета вместо письма.',
    CHAR(10 USING utf8mb4),
    '6. Никаких переменных в квадратных скобках: это готовый текст, а не шаблон. Имена бери из карточек выше.',
    CHAR(10 USING utf8mb4),
    '7. Не обещай встреч, не проси денег, не давай контактов вне сайта.',
    CHAR(10 USING utf8mb4), CHAR(10 USING utf8mb4),
    'Верни JSON: {"reply": "текст ответа"}')),
    ', "transitions_after": [], "transitions_before": [],',
    ' "llm_to_json_variable": [{"text": "текст ответа целиком", "variable": "reply"}]}')
    AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `id` FROM `agent_workflow_step`
                                   WHERE `workflow_id` = @wf AND `title` = 'Ответ') AS x);

-- ── Шаг 2: отдать текст ──────────────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`, `position`, `metadata`)
SELECT @wf, 4, 'Готово', 1,
       CAST('{"prompt_user": "%reply%", "continue_workflow": false,
              "transitions_after": [], "transitions_before": []}' AS JSON)
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT `id` FROM `agent_workflow_step`
                                   WHERE `workflow_id` = @wf AND `title` = 'Готово') AS x);

SELECT 'ПОСЛЕ' AS этап, @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_step` WHERE `workflow_id` = @wf) AS шагов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Готово') AS что_отдаём;
