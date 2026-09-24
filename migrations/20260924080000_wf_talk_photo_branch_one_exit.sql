-- Ветка фото отвечает общим шагом «Ответ», без своего (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- У ветки «письма и фото» был свой шаг возврата — «Ответ ветки», — делавший ровно
-- то же, что общий «Ответ»: отдавал текст собеседнику. Разница лишь в том, какую
-- переменную он читал.
--
--     «Ответ ветки»  %workflow_invoke_1525_result_str%
--     «Ответ»        %if girl_response_fixed%%girl_response_fixed%%else%%girl_response%%endif%
--
-- А `workflow_invoke_…_result_str` — это возврат самого сабворкфлоу, и форма у
-- него **та же самая**:
--
--     %if photo_fixed%%photo_fixed%%else%%photo_response%%endif%
--
-- То есть два шага отвечали на один вопрос, отличаясь именами переменных.
--
-- ## Как теперь
--
-- `outputs_map` кладёт выходы сабворкфлоу прямо в переменные общего ответа, и
-- ветка уходит на «Ответ» — тот же, которым отвечает чат.
--
-- ⚠⚠ **`photo_fixed` обязателен, и его в карте не было.** Это правка судьи (шаг
-- «Проверка ответа про фото»: «исправленный ответ; пусто — черновик годится»).
-- Смапь мы один `photo_response` — к человеку поехал бы черновик, а исправление
-- судьи пропало бы молча. Перенос имён сохраняет поведение в точности: у общего
-- шага та же развилка «правил ли судья».
--
-- ## ⚠ Переход становится безусловным, и это чинит дыру
--
-- У шага стоял переход `photo_deal != ""`, а рядом — снятая галочка «to next
-- step» (миграция `…_wf_talk_to_next_step`). Вместе это давало тупик: пустой
-- `photo_deal` не проходил условие и упирался в `no more step available`. До
-- снятия галочки поток в этом случае проваливался в «Ответ ветки» по номеру и
-- всё-таки отвечал.
--
-- Теперь переход безусловный (`prompt_user exists` — переменную кладёт сам
-- движок), и оба случая ведут к ответу.
--
-- ⚠ `photo_deal` в карте **остаётся**: он больше не нужен для развилки, но это
-- предмет разговора («о чём договорились: his, mine, both, mail»), и сбор фактов
-- о нём ещё спросит.
--
-- ## ⚠ Проверено кодом, а не журналом
--
-- За неделю в эту ветку не заходили ни разу: 0 прогонов. Поэтому разбор шёл по
-- устройству — какие переменные объявлены, что возвращает сабворкфлоу, как
-- движок раскладывает `outputs_map` (`переменная ребенка -> переменная родителя`).

SET @wf = (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk');
SET @branch = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf
                  AND `title` = 'Ветка: письма и фото' LIMIT 1);
SET @answer = (SELECT `id` FROM `agent_workflow_step`
                WHERE `workflow_id` = @wf AND `title` = 'Ответ' LIMIT 1);
SET @extra = (SELECT `id` FROM `agent_workflow_step`
               WHERE `workflow_id` = @wf AND `title` = 'Ответ ветки' LIMIT 1);

SELECT 'ДО' AS этап, @branch AS ветка, @answer AS общий_ответ,
       COALESCE(@extra, 0) AS свой_ответ_ветки,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.outputs_map')
          FROM `agent_workflow_step` WHERE `id` = @branch) AS карта_выходов;

-- ── 1. Выходы сабворкфлоу — в переменные общего ответа ──────────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.workflow_invoke.outputs_map',
         JSON_OBJECT('photo_deal', 'photo_deal',
                     'photo_response', 'girl_response',
                     'photo_fixed', 'girl_response_fixed'))
 WHERE `id` = @branch
   AND `metadata` IS NOT NULL AND `metadata` <> '' AND JSON_VALID(`metadata`);

-- ── 2. Ветка уходит на общий «Ответ», безусловно ────────────────────────────
--
-- ⚠ `prompt_user exists` — ближайшее к безусловному, что даёт язык переходов:
-- переменную кладёт сам движок (`ai_workflow_variables_base`), удалить её из
-- редактора нельзя. Условие по `photo_deal` убрано намеренно: пустое значение
-- оставляло ветку без ответа.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.transitions_after', JSON_ARRAY(
         JSON_OBJECT('variable', 'prompt_user', 'operator', 'exists',
                     'value', '', 'step_id', CAST(@answer AS CHAR))))
 WHERE `id` = @branch;

-- ── 3. Свой шаг возврата больше не нужен ────────────────────────────────────
--
-- ⚠ Удаляем **последним**: пока на него ведёт переход, снос оставил бы ссылку в
-- никуда. Порядок здесь — не вкусовщина.
-- ⚠⚠ Ссылки ищем **числом**, а не `LIKE CONCAT(…, @переменная, …)`. У баз разные
-- сличения (`utf8mb4_general_ci` против `utf8mb4_0900_ai_ci`), и сравнение
-- столбца с пользовательской переменной роняет запрос: `Illegal mix of
-- collations`. Поймано этой же миграцией — на проде прошла, локально упала.
-- У чисел сличения нет.
DELETE FROM `agent_workflow_step`
 WHERE `id` = @extra AND @extra IS NOT NULL
   AND NOT EXISTS (
         SELECT 1 FROM (
           SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(j.v, '$.step_id')) AS UNSIGNED) AS ref
             FROM `agent_workflow_step` s
             JOIN JSON_TABLE(
                    JSON_MERGE_PRESERVE(
                      COALESCE(JSON_EXTRACT(s.`metadata`, '$.transitions_after'), JSON_ARRAY()),
                      COALESCE(JSON_EXTRACT(s.`metadata`, '$.transitions_before'), JSON_ARRAY())),
                    '$[*]' COLUMNS (v JSON PATH '$')) j
            WHERE s.`workflow_id` = @wf
              AND s.`metadata` IS NOT NULL AND s.`metadata` <> ''
              AND JSON_VALID(s.`metadata`)) r
          WHERE r.ref = @extra);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT JSON_EXTRACT(`metadata`, '$.workflow_invoke.outputs_map')
          FROM `agent_workflow_step` WHERE `id` = @branch) AS карта_выходов,
       (SELECT JSON_UNQUOTE(JSON_EXTRACT(`metadata`,
                 '$.transitions_after[0].step_id')) = CAST(@answer AS CHAR)
          FROM `agent_workflow_step` WHERE `id` = @branch) AS ведёт_на_общий_ответ,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Ответ ветки') AS лишний_остался,
       (SELECT COUNT(*) FROM (
          SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(j.v, '$.step_id')) AS UNSIGNED) AS ref
            FROM `agent_workflow_step` s
            JOIN JSON_TABLE(
                   JSON_MERGE_PRESERVE(
                     COALESCE(JSON_EXTRACT(s.`metadata`, '$.transitions_after'), JSON_ARRAY()),
                     COALESCE(JSON_EXTRACT(s.`metadata`, '$.transitions_before'), JSON_ARRAY())),
                   '$[*]' COLUMNS (v JSON PATH '$')) j
           WHERE s.`workflow_id` = @wf
             AND s.`metadata` IS NOT NULL AND s.`metadata` <> ''
             AND JSON_VALID(s.`metadata`)) r
         WHERE r.ref = COALESCE(@extra, 0)) AS ссылок_в_никуда;
