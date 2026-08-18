-- Агенты перенесённых workflow → на прод
--
-- Зачем вручную: агенты — данные, деплой их не трогает. 20 workflow приехали на
-- прод миграцией `2026-08-18_workflow_sync_prod.sql`, но вызывать их было некому:
-- агент — это точка входа, через него workflow и запускается.
--
-- ЧТО ПЕРЕНОСИТСЯ (10 агентов узла Dashboard, снято 2026-08-18):
--
--     44  planning_scorer                      → workflow 30
--     71  planning_idea_generator              → 31
--     72  planning_designer                    → 32
--     73  planning_html_prototyper             → 33
--     77  planning_prototype_refiner           → 37
--     78  planning_prototype_sitemap_checker   → 38
--     82  planning_wireframe_composer          → 49
--     83  planning_block_regenerator           → 50
--     84  task_ai_generator                    → 53
--     97  design_tokens_manager                → 54
--
-- ЧЕГО ЗДЕСЬ НЕТ. Остальных агентов локальной установки: среди них тестовые —
-- анкеты сайтов знакомств (`renata_1430354`), служебные `*_runner`, остатки
-- экспериментов. Им на проде не место, поэтому список явный, а не «все».
--
-- ПРОВЕРЕНО НА ПРОДЕ ПЕРЕД ВЫПУСКОМ:
--   * все десять номеров свободны (ни один не занят чужим агентом);
--   * узел 6 на проде — тот же `Dashboard`, что локально (сверены имена всех узлов);
--   * workflow 30, 31, 32, 33, 37, 38, 49, 50, 53, 54 на проде уже есть;
--   * ролевых связей (`agent_role`) у этих агентов нет — переносить нечего.
--
-- ⚠️ ID сохраняются: агент адресуется по номеру из панели и из ссылок вида
--   `/admin/agent?agent_id=44`. Переназначить их значит поломать закладки и сбить
--   соответствие с локальной установкой, по которой этот файл и собран.
--
-- ПЕРЕД ПРОГОНОМ: свежий бэкап через `/admin/backup`.

USE `project`;

SET NAMES utf8mb4;

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM agent) AS всего_агентов,
       (SELECT COUNT(*) FROM agent WHERE id IN (44,71,72,73,77,78,82,83,84,97)) AS из_этих_есть;

-- Агенты. Порядок не важен: связей между ними нет, все смотрят на узел и workflow.

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (44,6,'planning_scorer','Blueprint Scorer','Оценивает Blueprint по ключевым критериям и выставляет итоговый рейтинг',30,'{\"planning_phase_name\":\"score\"}','Ты опытный венчурный аналитик. Оцениваешь продуктовые идеи объективно и критично. Оценки реалистичные — большинство идей 5-7, хорошие 8-9, исключительные 10. go = реальный шанс; maybe = нужны изменения; no = фундаментальные проблемы.','',9,'Проекты/Planning',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (71,6,'planning_idea_generator','Генератор идей','Генерирует идеи продуктов по заданной нише',31,'{\"planning_phase_name\":\"idea_gen\"}','Ты опытный продуктовый стратег. Генерируешь конкретные реалистичные идеи продуктов с чётким value proposition.','',10,'Проекты/Planning',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (72,6,'planning_designer','Design Creator','Создаёт полный дизайн-документ: дизайн-система, карта страниц, спецификации, Landing Page, Dashboard',32,'{\"planning_doc_title\":\"Дизайн\",\"planning_doc_type\":\"design\"}','Ты эксперт по UI/UX дизайну SaaS продуктов. Создавай детальные дизайн-документы, основанные на реальных данных: скриншоты конкурентов, паттерны с высокой конверсией, обоснованный выбор UI-библиотек. Каждое дизайн-решение должно быть подкреплено источником.','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (73,6,'planning_html_prototyper','Design Prototype Builder','Генерирует интерактивный HTML-прототип со всеми ключевыми экранами продукта',33,'{\"planning_doc_title\":\"Прототип\",\"planning_doc_type\":\"prototype\"}','Ты UI/UX-дизайнер и senior frontend-разработчик. Создаёшь HIGH-FIDELITY интерактивные HTML-прототипы SaaS продуктов которые выглядят как реальные продукты — насыщенные цвета, правильная типографика, тени, иконки, реалистичный контент. ВСЕГДА используешь Tailwind CSS CDN (cdn.tailwindcss.com) через <script> тег. Устанавливаешь цветовую схему через tailwind.config. JS-код чистый, навигация между страницами работает плавно. Возвращаешь ПОЛНЫЙ HTML-файл, готовый к открытию в браузере.','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (77,6,'planning_prototype_refiner','Design Prototype Refiner','Доработка HTML-прототипа',37,'{}','Ты frontend-разработчик. Работаешь с HTML-страницами прототипов. Точно следуй инструкциям каждого шага: для JSON-шагов — возвращай только JSON, для HTML-шагов — возвращай только полный HTML без пояснений и markdown.','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (78,6,'planning_prototype_sitemap_checker','Design Sitemap Checker','QA-проверка прототипа: браузерный обход всех пунктов меню, сравнение с картой страниц',38,'{}','Ты QA-инженер. Анализируй результаты браузерного сканирования прототипа. Пиши чёткие, конкретные отчёты с таблицами. Для каждой проблемы давай конкретную рекомендацию.','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (82,6,'planning_wireframe_composer','Design UI/UX Creator','Генерирует вайрфреймы страниц и базовые виджеты блоков',49,'{}','','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (83,6,'planning_block_regenerator','UI Block Manager','AI перегенерирует описание блока и создаёт виджеты с CSS',50,'{}','','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (84,6,'task_ai_generator','AI помощник','Генерирует структуру задачи из описания',53,'{}','Ты опытный менеджер проектов. Помогаешь структурировать задачи: придумываешь чёткое название, развёрнутое описание и конкретные измеримые цели. Всегда отвечаешь строго в JSON формате.','',0,'Проекты/Task',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);
INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `group_name`, `dynamic`) VALUES (97,6,'design_tokens_manager','Design Tokens Manager','',54,'{}','','',0,'Проекты/Design',0)
  ON DUPLICATE KEY UPDATE `node_id` = VALUES(`node_id`), `name` = VALUES(`name`), `title` = VALUES(`title`), `description` = VALUES(`description`), `workflow_id` = VALUES(`workflow_id`), `workflow_variable` = VALUES(`workflow_variable`), `prompt_system` = VALUES(`prompt_system`), `greeting` = VALUES(`greeting`), `position` = VALUES(`position`), `group_name` = VALUES(`group_name`), `dynamic` = VALUES(`dynamic`);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM agent) AS всего_агентов,
       (SELECT COUNT(*) FROM agent WHERE id IN (44,71,72,73,77,78,82,83,84,97)) AS перенесено;

-- Каждый агент смотрит на существующий workflow и узел.
SELECT a.id, a.name,
       IF(w.id IS NULL, 'WORKFLOW НЕТ', w.name) AS workflow,
       IF(n.id IS NULL, 'УЗЛА НЕТ', n.name)     AS узел
  FROM agent a
  LEFT JOIN agent_workflow w ON w.id = a.workflow_id
  LEFT JOIN node n ON n.id = a.node_id
 WHERE a.id IN (44,71,72,73,77,78,82,83,84,97) ORDER BY a.id;

-- Workflow, которым по-прежнему некого вызвать: список должен стать короче.
SELECT w.id, w.name
  FROM agent_workflow w LEFT JOIN agent a ON a.workflow_id = w.id
 WHERE w.subflow = 0 AND a.id IS NULL ORDER BY w.id;