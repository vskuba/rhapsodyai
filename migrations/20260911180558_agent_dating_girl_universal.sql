-- Универсальная «Девушка» для DatingAi: один агент вместо записи на анкету.
--
-- ЧТО БЫЛО. У каждой анкеты свой агент. Разница между ними — одно слово:
-- «You are a girl Diana» против «You are a girl Renata», остальные полторы
-- тысячи знаков промпта совпадают до буквы. Всё прочее уже приходило
-- переменными: `girl_id` (тип `input` у `dating_talk`) адресует факты анкеты в
-- Qdrant и передаётся запросом, workflow — общий. Записи плодились ради имени.
--
-- Цена этого: заведение анкеты требовало прогона `dating_girl_create` с LLM,
-- правка формулировки в промпте — обхода всех анкет, а список агентов в админке
-- рос на каждую анкету соседнего сайта.
--
-- ЧТО ДЕЛАЕМ. Заводим агента `dating_girl_universal` с промптом-шаблоном: на
-- месте имени — `%girl_name%`, значение приходит переменной агента
-- (`agent.agent_variable`) или переменной запроса. Запись одна; анкету от анкеты
-- отличает пара значений, а не пара записей.
--
-- КАК ЕГО ЗОВУТ ИЗ DatingAi:
--
--     POST /chat/ask
--     {"agent_id": <id этого агента>, "companion_id": <…>, "question": "…",
--      "variables": {"girl_id": "natalia_1430119", "girl_name": "Natalia"}}
--
-- `girl_name` уходит в промпт, `girl_id` — в фильтры фактов (шаг «Переменные»
-- workflow `dating_talk`). Оба обязательны: без `girl_id` факты чужие, без
-- `girl_name` собеседница представится умолчанием записи.
--
-- ⚠ ТЕКСТ ПРОМПТА НЕ НАБРАН РУКАМИ, А ВЗЯТ ИЗ ПЕРЕМЕННОЙ УЗЛА
-- `girl_prompt_system` — того самого шаблона, по которому `dating_girl_create`
-- лепит промпт каждой анкете. Набрать его копией значило бы завести второй
-- источник правды: правка в узле не доехала бы сюда, и универсальный агент
-- начал бы вести себя иначе, чем заведённые раньше. `%girl_title%` в шаблоне
-- меняем на `%girl_name%`: `girl_title` — это переменная узла типа `proxy` со
-- значением `%prompt_user%`, и переменные узла применяются **после** переменных
-- запроса (`update`, а не `setdefault`) — имя собеседницы в промпте подменилось
-- бы текстом входящего сообщения.
--
-- ⚠ `girl_id` В `workflow_variable` — УМОЛЧАНИЕ, А НЕ НАСТРОЙКА. Переменная
-- обязательная (`type='input'`), и без неё `/chat/ask` отвечает `400` ещё до
-- первого шага. Умолчание даёт агенту открываться в админском чате; работа
-- идёт со значением из запроса, оно перекрывает это.
--
-- Старые агенты анкет не трогаем: они работают, их факты на месте, и снос сотни
-- записей — отдельное решение с бэкапом, а не побочный эффект этой миграции.
--
-- Идемпотентность: вставка под `NOT EXISTS` по имени. Повторный прогон не
-- добавляет второго агента и **не переписывает** промпт — его могли поправить
-- руками в админке, и миграция не вправе это отменять.

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent` WHERE `name` = 'dating_girl_universal') AS агент_есть,
       (SELECT COUNT(*) FROM `agent` WHERE `workflow_id` =
            (SELECT `id` FROM `agent_workflow` WHERE `name` = 'dating_talk')) AS анкет_сейчас;

INSERT INTO `agent` (`node_id`, `name`, `title`, `description`, `workflow_id`,
                     `workflow_variable`, `agent_variable`, `prompt_system`,
                     `greeting`, `position`, `group_name`, `dynamic`)
SELECT n.`id`,
       'dating_girl_universal',
       'Девушка',
       'Универсальная анкета: имя приходит переменной girl_name, факты — girl_id',
       w.`id`,
       '{"girl_id": "dating_girl_universal"}',
       '{"girl_name": "Natalia"}',
       REPLACE(nv.`default`, '%girl_title%', '%girl_name%'),
       'Hi, I am %girl_name%',
       0,
       NULL,
       0
  FROM `node` n
  JOIN `agent_workflow` w ON w.`name` = 'dating_talk'
  JOIN `node_variable` nv ON nv.`node_id` = n.`id` AND nv.`name` = 'girl_prompt_system'
 WHERE n.`name` = 'Dating'
   AND NOT EXISTS (SELECT 1 FROM (SELECT `name` FROM `agent`) a
                    WHERE a.`name` = 'dating_girl_universal');

-- Роли: `dating_service` — под ней ходит DatingAi (без строки в `agent_role`
-- служебная учётка агента просто не увидит, `/agent/list` отдаст пустой массив);
-- `manager_dating` — чтобы агент был виден менеджерам в админке.
INSERT IGNORE INTO `agent_role` (`agent_id`, `role_id`)
SELECT a.`id`, r.`id`
  FROM `agent` a
  JOIN `role` r ON r.`name` IN ('dating_service', 'manager_dating')
 WHERE a.`name` = 'dating_girl_universal';

SELECT 'ПОСЛЕ' AS этап,
       a.`id` AS номер,
       a.`agent_variable` AS переменные,
       LEFT(a.`prompt_system`, 40) AS начало_промпта,
       (SELECT COUNT(*) FROM `agent_role` ar WHERE ar.`agent_id` = a.`id`) AS ролей
  FROM `agent` a
 WHERE a.`name` = 'dating_girl_universal';
