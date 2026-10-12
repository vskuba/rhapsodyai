-- Факты девушки: сочинённое не должно спорить с анкетой и само с собой (2026-10-12)
--
-- ## ⚠⚠ ЧТО СЛОМАЛОСЬ
--
-- У анкеты Ekaterina (`622715_ekaterina`) в коллекции `dating_girl` лежали два
-- факта, записанные **одним вызовом**, одной секундой `2026-10-01 17:08:16`:
--
--     #166  I am 27 years old, and I live in Kyiv.     I work as a video editor…
--     #167  I am 25 years old, and I live in Kharkiv.  I work as a photographer…
--
-- В карточке анкеты при этом 33 года и Kyiv (`birthday 1993-07-01`). То есть
-- промахнулись оба факта, а между собой разошлись ещё и в городе. Дальше их
-- обоих читает каждый промпт разговора — девушка одновременно двадцатипяти- и
-- двадцатисемилетняя, из двух городов сразу.
--
-- ## Отчего
--
-- Шаг «Новый факты» просит у модели **пару** фактов одним ответом, а единственная
-- оговорка про согласие звучала так:
--
--     Новые факты не должны противоречить уже существующим.
--
-- Два факта, рождённые одним ответом, друг для друга «уже существующими» **не
-- являются** — их обоих ещё нет в базе. И анкета (`girl_bio`) в правилах не
-- названа вовсе: она показана заголовком «Информация в анкете о …», но ни одним
-- требованием не закрыта. Даже топонимическая оговорка привязана к фактам, а не
-- к анкете: «не называй город… которых нет **в уже существующих фактах**». У
-- Ekaterina это был **первый** заход, фактов о ней не было, блок «Уже
-- существующие факты» под `[<if …>]` в промпт не попал — и опор не осталось ни
-- одной.
--
-- ## ⚠⚠⚠ Правило уже написано — через один workflow
--
-- У `dating_bot`, шаг «LLM -> JSON», то же занятие описано верно:
--
--     2. Факты не должны противоречить биографии и друг другу.
--
-- Обе недостающие половины там на месте. Эта миграция переносит их сюда — то
-- есть не выдумывает правило, а чинит расхождение двух промптов об одном деле.
--
-- ## ⚠ Чего эта миграция не делает
--
-- **Два факта Ekaterina она не удаляет.** Удаление факта обязано снимать его и из
-- Qdrant (`qdrant_remove_by` по `{"id": …}`, см. `fact_delete_fact`), а поиск
-- читает именно Qdrant: голый `DELETE FROM fact` оставил бы векторы жить, и
-- противоречие продолжило бы приезжать в промпты при чистой таблице. Чистка идёт
-- отдельно и дверью приложения.
--
-- Идемпотентность: каждая правка условна по тексту, который заменяет. Второй
-- прогон не находит старой формулировки и ничего не делает.

SET @wf = (SELECT `id` FROM `agent_workflow`
            WHERE `name` = 'girl_fact_invent' ORDER BY `id` LIMIT 1);

SELECT 'ДО' AS этап,
       @wf AS workflow,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Новый факты'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%не должны противоречить уже существующим.%') AS старое_правило,
       (SELECT CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')))
          FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Новый факты') AS длина_промпта;

-- ── 1. Главное правило: анкета и соседний факт того же ответа ────────────────
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 'Новые факты не должны противоречить уже существующим.',
                 'Новые факты не должны противоречить уже существующим фактам, '
                 'анкете девушки и друг другу. Возраст и город бери строго из '
                 'анкеты: названы там — повторяй их буква в букву, не названы — '
                 'не называй вовсе.'))
 WHERE `workflow_id` = @wf
   AND `title` = 'Новый факты'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       LIKE '%Новые факты не должны противоречить уже существующим.%';

-- ── 2. Топонимы: анкета — такой же источник, как накопленные факты ───────────
--
-- ⚠ Отдельным запросом со своим условием, а не вложенным `REPLACE` в первый:
-- правка промпта руками между выкладками оставила бы половину правил старыми,
-- и понять по базе, какая половина применилась, было бы нечем.
UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 'которых нет в уже существующих фактах:',
                 'которых нет в анкете и в уже существующих фактах:'))
 WHERE `workflow_id` = @wf
   AND `title` = 'Новый факты'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       LIKE '%которых нет в уже существующих фактах:%';

UPDATE `agent_workflow_step`
   SET `metadata` = JSON_SET(`metadata`, '$.prompt_user',
         REPLACE(JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')),
                 'Если город в фактах назван — все места только в нём.',
                 'Если город назван в анкете или в фактах — все места только в нём.'))
 WHERE `workflow_id` = @wf
   AND `title` = 'Новый факты'
   AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
       LIKE '%Если город в фактах назван — все места только в нём.%';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Новый факты'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%анкете девушки и друг другу%') AS новое_правило,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Новый факты'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%которых нет в анкете и в уже существующих фактах:%') AS топонимы,
       (SELECT COUNT(*) FROM `agent_workflow_step`
         WHERE `workflow_id` = @wf AND `title` = 'Новый факты'
           AND JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user'))
               LIKE '%Если город назван в анкете или в фактах%') AS город;

-- ⚠⚠ Сторож: метки шага обязаны уцелеть. `%girl_title%` и `%girl_id%` несут имя
-- девушки и ключ документа — затри их `REPLACE`, и факты поедут в чужой документ.
SELECT 'метки на месте' AS проверка,
       JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%\%girl_title\%%' AS есть_имя,
       JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%\%girl_id\%%' AS есть_ключ,
       JSON_UNQUOTE(JSON_EXTRACT(`metadata`, '$.prompt_user')) LIKE '%\%girl_bio\%%' AS есть_анкета
  FROM `agent_workflow_step`
 WHERE `workflow_id` = @wf AND `title` = 'Новый факты';
