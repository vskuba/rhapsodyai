-- Снятая провайдером модель уходит из списка узла Dating
--
-- Зачем вручную: список моделей узла — данные (`node_llm`), а не схема. Деплой их
-- не трогает, и правка, сделанная локально, на прод не доедет.
--
-- ЧТО ПРОИЗОШЛО. `groq/llama-3.3-70b-versatile` (llm id 5) провайдер снял: запрос к
-- ней отвечает `404`. На проде она стояла **первой** в списке узла Dating, и на ней
-- падало заведение агента анкеты:
--
--     status_code: 404, model_name: llama-3.3-70b-versatile
--
-- Падало целиком, а не переходило к следующей модели, потому что `404` не значился
-- среди кодов, по которым цепочка переключается. Это исправлено в коде
-- (`src/ai/framework/agent/ai_framework.py`) — теперь снятая модель переживается
-- фоллбэком. Но держать мёртвую первой всё равно незачем: каждый шаг workflow
-- начинался бы с обращения в пустоту.
--
-- ЧТО ДЕЛАЕТ ФАЙЛ: убирает модель 5 из списка узла Dating и пересчитывает позиции
-- остальных, сохраняя их порядок. Саму запись в `llm` не трогает — она может быть
-- привязана к другим узлам, и решение о ней принимается отдельно.
--
-- ⚠️ `UPDATE` с `ORDER BY` MySQL не принимает, если в запросе есть `JOIN`
--   («Incorrect usage of UPDATE and ORDER BY»). Поэтому новые позиции считаются
--   подзапросом и присваиваются по совпадению строки.
--
-- Идемпотентность: второй прогон не найдёт модель 5 в списке и лишь пересчитает
-- позиции, которые уже верны.

USE `project`;

SELECT 'ДО' AS этап, nl.position, l.id, l.name
  FROM node_llm nl
  JOIN llm l ON l.id = nl.llm_id
  JOIN node n ON n.id = nl.node_id
 WHERE n.name = 'Dating' ORDER BY nl.position;

DELETE nl FROM node_llm nl
  JOIN node n ON n.id = nl.node_id
 WHERE n.name = 'Dating' AND nl.llm_id = 5;

SET @pos := -1;
UPDATE node_llm nl
  JOIN (
    SELECT nl2.llm_id, (@pos := @pos + 1) AS new_pos
      FROM node_llm nl2
      JOIN node n2 ON n2.id = nl2.node_id
     WHERE n2.name = 'Dating'
     ORDER BY nl2.position
  ) AS calc ON calc.llm_id = nl.llm_id
  JOIN node n ON n.id = nl.node_id
   SET nl.position = calc.new_pos
 WHERE n.name = 'Dating';

SELECT 'ПОСЛЕ' AS этап, nl.position, l.id, l.name
  FROM node_llm nl
  JOIN llm l ON l.id = nl.llm_id
  JOIN node n ON n.id = nl.node_id
 WHERE n.name = 'Dating' ORDER BY nl.position;
