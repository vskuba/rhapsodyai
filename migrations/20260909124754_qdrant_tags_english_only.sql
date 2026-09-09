-- Теги фактов — только на английском.
--
-- Проблема: язык тега шёл за языком ноды, и одно понятие попадало в Qdrant
-- дважды. На момент правки в коллекциях лежало 749 тегов: 419 английских и
-- 330 русских, среди них пары «hobbies»/«хобби» (26 и 11 фактов) и
-- «work»/«работа» (8 и 11). Поиск по «hobbies» не находил факты с «хобби»,
-- хотя это одно и то же.
--
-- Правится в трёх местах, потому что теги рождаются в трёх:
--   1. комментарий колонки `fact`.`tags` — из него инструмент
--      `fact_collection_output_format` собирает пример формата, который
--      подставляется во все workflow создания фактов;
--   2. промпт шага «Анализ сообщения» workflow `dating_talk` — он же даёт
--      значение фильтра поиска по тегам;
--   3. системные промпты агентов `fact_extractor` и `fact_compress`.
--
-- Уже накопленные русские теги эта миграция НЕ трогает: перезапись живых
-- данных — отдельное решение, а не побочный эффект правки промптов.

-- 1. Комментарий колонки: источник формата для всех workflow создания фактов
ALTER TABLE `fact`
    MODIFY `tags` CHAR(250) NOT NULL
    COMMENT 'tag:extract|type:array_string|desc:A comma-separated list of tags. ALWAYS in English and lowercase, regardless of the document language: tags are a shared index, and a translated tag creates a duplicate (example: gym,fitness,routine)';

-- 2. Шаг «Анализ сообщения» (workflow dating_talk): два вхождения примера —
--    в описании переменной и в тексте промпта, REPLACE берёт оба
UPDATE `agent_workflow_step`
   SET `metadata` = REPLACE(
        `metadata`,
        'Например: машина,права,пунктуальность',
        'ВСЕГДА на английском и в нижнем регистре, независимо от языка переписки: теги — общий индекс, переведённый тег создаёт дубликат. Например: car,license,punctuality'
   )
 WHERE `metadata` LIKE '%Например: машина,права,пунктуальность%';

-- 3. Агенты извлечения и сжатия фактов
UPDATE `agent`
   SET `prompt_system` = REPLACE(
        `prompt_system`,
        '- tags: A comma-separated list inside brackets [tag1, tag2].',
        '- tags: A comma-separated list inside brackets [tag1, tag2]. ALWAYS in English and lowercase, regardless of the source language: tags are a shared index, and a translated tag creates a duplicate.'
   )
 WHERE `prompt_system` LIKE '%- tags: A comma-separated list inside brackets [tag1, tag2].%';
