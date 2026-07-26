-- Planning: нода для AI-ассистированного планирования продуктов.
-- Принимает сырую идею и за 8 фаз (анализ → рынок → продукт → техника →
-- GTM → финансы → Blueprint → Supplements) строит полный пакет документов.
-- Каждая фаза — отдельный агент с workflow; запускаются Cronicle-кронджобами.

-- === NODE ===

INSERT IGNORE INTO `node` (`id`, `name`, `position`, `migration_file`, `is_catchall`) VALUES
(9, 'Planning', 5, 'migrations/0007.sql', 0);

INSERT IGNORE INTO `node_llm` (`node_id`, `llm_id`, `rate_limit_at`, `code_error`, `position`) VALUES
(9, 5,  NULL, NULL, 2),
(9, 6,  NULL, NULL, 5),
(9, 10, NULL, NULL, 6),
(9, 11, NULL, NULL, 1),
(9, 12, NULL, NULL, 4),
(9, 15, NULL, NULL, 3),
(9, 16, NULL, NULL, 7);

-- === TABLES ===

CREATE TABLE IF NOT EXISTS `planning_project` (
    `id`            INT            NOT NULL AUTO_INCREMENT,
    `node_id`       INT            NOT NULL DEFAULT 9,
    `user_id`       INT            NOT NULL DEFAULT 0,
    `title`         VARCHAR(255)   NOT NULL DEFAULT '',
    `idea`          LONGTEXT       NOT NULL,
    `status`        ENUM('pending','processing','complete','error') NOT NULL DEFAULT 'pending',
    `phase_current` VARCHAR(100)   NOT NULL DEFAULT '',
    `created_at`    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `planning_phase` (
    `id`           INT          NOT NULL AUTO_INCREMENT,
    `project_id`   INT          NOT NULL,
    `phase`        VARCHAR(100) NOT NULL DEFAULT '',
    `status`       ENUM('pending','running','complete','failed') NOT NULL DEFAULT 'pending',
    `result`       LONGTEXT     NOT NULL DEFAULT '',
    `error`        TEXT         NOT NULL DEFAULT '',
    `tokens_used`  INT          NOT NULL DEFAULT 0,
    `started_at`   DATETIME     NULL,
    `completed_at` DATETIME     NULL,
    `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `project_phase` (`project_id`, `phase`),
    KEY `idx_project` (`project_id`),
    KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `planning_document` (
    `id`         INT          NOT NULL AUTO_INCREMENT,
    `project_id` INT          NOT NULL,
    `doc_type`   VARCHAR(100) NOT NULL DEFAULT '',
    `title`      VARCHAR(255) NOT NULL DEFAULT '',
    `content`    LONGTEXT     NOT NULL DEFAULT '',
    `version`    INT          NOT NULL DEFAULT 1,
    `status`     ENUM('draft','final') NOT NULL DEFAULT 'draft',
    `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_project` (`project_id`),
    KEY `idx_doc_type` (`doc_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- === WORKFLOW VARIABLES ===

-- Входная переменная: ID проекта (передаётся во все planning-воркфлоу)
INSERT INTO `agent_workflow_variable` (`id`, `name`, `type`, `default`, `description`) VALUES
(194, 'planning_project_id', 'input', '0',  'ID проекта из таблицы planning_project'),
(195, 'planning_supplement_type', 'input', 'market', 'Тип дополнения: market | product | tech | gtm | financial | launch');

-- === WORKFLOWS (8 фаз + 1 supplement + 1 planning_bot chat) ===

INSERT INTO `agent_workflow` (`id`, `node_id`, `name`, `title`, `description`, `position`, `subflow`) VALUES
(19, 9, 'planning_analyze',    'Анализ идеи',          'Структурирует сырую идею: аудитория, проблема, гипотеза, допущения', 0, 0),
(20, 9, 'planning_market',     'Исследование рынка',   'Рынок, конкуренты, тренды, белые пятна', 1, 0),
(21, 9, 'planning_product',    'Продуктовый план',     'Видение, фичи, MVP scope, дорожная карта', 2, 0),
(22, 9, 'planning_tech',       'Тех. архитектура',     'Стек, компоненты, инфра, риски', 3, 0),
(23, 9, 'planning_gtm',        'GTM-стратегия',        'ICP, позиционирование, каналы, воронка', 4, 0),
(24, 9, 'planning_financial',  'Финансовая модель',    'Unit-экономика, P&L, инвестиции, таблица работ по ролям', 5, 0),
(25, 9, 'planning_blueprint',  'Blueprint документ',   'Главный сводный документ с иллюстрациями и таблицами', 6, 0),
(26, 9, 'planning_supplement', 'Дополнение',           'Детализированное дополнение по конкретному направлению', 7, 0),
(27, 9, 'planning_bot_chat',   'Planning Bot Chat',    'Конверсационный workflow для Planning Bot', 8, 0);

-- Привязка общей входной переменной ко всем planning-воркфлоу
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) VALUES
(194, 19), (194, 20), (194, 21), (194, 22),
(194, 23), (194, 24), (194, 25), (194, 26),
(195, 26);

-- === WORKFLOW STEPS ===

-- ─── Workflow 19: planning_analyze ───────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
-- Шаг 1: загрузить данные проекта
(162, 19, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
-- Шаг 2: LLM анализ идеи
(163, 19, 2, 'Анализ идеи', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"структурированный анализ идеи продукта (800-1200 слов Markdown) с разделами: ## Суть идеи, ## Целевая аудитория, ## Ключевая проблема, ## Гипотеза решения, ## Уникальный угол, ## Ключевые допущения, ## Риски. Используй маркированные списки и выделение жирным."}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\nПроанализируй идею продукта по ключевым измерениям. Верни JSON с одним ключом phase_result содержащим полный Markdown-анализ. Правильно экранируй кавычки.","transitions_before":[],"transitions_after":[]}'),
-- Шаг 3: сохранить результат
(164, 19, 3, 'Сохранить фазу', 2,
 '{"tool_invoke":{"tool_name":"planning_phase_save","inputs_map":{"project_id":"planning_project_id","phase":"planning_phase_name","result":"phase_result"},"outputs_map":{"saved":"phase_saved"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 20: planning_market ────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(165, 20, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(166, 20, 2, 'Исследование рынка', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"полное исследование рынка (1000-1500 слов Markdown) с разделами: ## Обзор рынка, ## Размер рынка (TAM/SAM/SOM с оценками), ## Конкуренты (таблица с колонками: Название | Сегмент | Ключевая фича | Цена | Сильные стороны | Слабые стороны), ## Тренды (макро и продуктовые), ## Белые пятна и возможности, ## Ключевые инсайты"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПРЕДЫДУЩИЙ АНАЛИЗ ===\\n%phases_context%\\n\\nПроведи детальное исследование рынка для данной идеи продукта. Оцени рынок реалистично. Верни JSON с ключом phase_result содержащим Markdown-отчёт.","transitions_before":[],"transitions_after":[]}'),
(167, 20, 3, 'Сохранить фазу', 2,
 '{"tool_invoke":{"tool_name":"planning_phase_save","inputs_map":{"project_id":"planning_project_id","phase":"planning_phase_name","result":"phase_result"},"outputs_map":{"saved":"phase_saved"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 21: planning_product ───────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(168, 21, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(169, 21, 2, 'Продуктовый план', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"продуктовый план (1000-1500 слов Markdown) с разделами: ## Видение продукта, ## Стратегические цели (SMART с KPI), ## Функции (таблица: Функция | Приоритет MoSCoW | Описание | Ценность), ## MVP scope (что входит / что нет), ## Дорожная карта (таблица: Фаза | Срок | Ключевые deliverables | Цель), ## Метрики успеха"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПРЕДЫДУЩИЙ АНАЛИЗ ===\\n%phases_context%\\n\\nСоздай детальный продуктовый план. Опирайся на данные рынка из предыдущего анализа. Верни JSON с ключом phase_result содержащим Markdown.","transitions_before":[],"transitions_after":[]}'),
(170, 21, 3, 'Сохранить фазу', 2,
 '{"tool_invoke":{"tool_name":"planning_phase_save","inputs_map":{"project_id":"planning_project_id","phase":"planning_phase_name","result":"phase_result"},"outputs_map":{"saved":"phase_saved"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 22: planning_tech ──────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(171, 22, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(172, 22, 2, 'Тех. архитектура', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"техническая архитектура (1000-1500 слов Markdown) с разделами: ## Технологический стек (таблица: Слой | Технология | Версия | Обоснование), ## Архитектурная схема (текстовое ASCII-описание компонентов), ## Ключевые компоненты и их взаимодействие, ## Инфраструктура (cloud, CI/CD, мониторинг), ## API Design (ключевые endpoints), ## Технические риски и митигация, ## Оценка сложности (S/M/L/XL по компонентам)"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПРЕДЫДУЩИЙ АНАЛИЗ ===\\n%phases_context%\\n\\nСпроектируй техническую архитектуру продукта. Учти MVP scope из продуктового плана. Верни JSON с ключом phase_result.","transitions_before":[],"transitions_after":[]}'),
(173, 22, 3, 'Сохранить фазу', 2,
 '{"tool_invoke":{"tool_name":"planning_phase_save","inputs_map":{"project_id":"planning_project_id","phase":"planning_phase_name","result":"phase_result"},"outputs_map":{"saved":"phase_saved"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 23: planning_gtm ───────────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(174, 23, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(175, 23, 2, 'GTM-стратегия', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"GTM-стратегия (1000-1500 слов Markdown) с разделами: ## Идеальный клиент ICP (firmographics, психографика, trigger events), ## Позиционирование (positioning statement + value proposition), ## Топ-3 канала привлечения (таблица: Канал | CAC-оценка | Time-to-revenue | Scalability), ## Воронка продаж (этапы с метриками конверсии), ## Sales motion (self-serve/inside-sales/enterprise), ## Retention (онбординг, health score, churn prevention), ## Milestones (первые 10 клиентов → первые 100 → $10K MRR)"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПРЕДЫДУЩИЙ АНАЛИЗ ===\\n%phases_context%\\n\\nРазработай GTM-стратегию. Основывайся на рыночном исследовании и продуктовом плане. Верни JSON с ключом phase_result.","transitions_before":[],"transitions_after":[]}'),
(176, 23, 3, 'Сохранить фазу', 2,
 '{"tool_invoke":{"tool_name":"planning_phase_save","inputs_map":{"project_id":"planning_project_id","phase":"planning_phase_name","result":"phase_result"},"outputs_map":{"saved":"phase_saved"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 24: planning_financial ─────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(177, 24, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(178, 24, 2, 'Финансовая модель', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"финансовая модель (1200-1800 слов Markdown) с разделами: ## Допущения (ключевые финансовые предположения), ## Unit-экономика (таблица: ARPU | CAC | LTV | Payback Period | LTV/CAC), ## MRR Waterfall (таблица: Месяц 1-12 | New MRR | Churn MRR | Expansion MRR | Total MRR), ## Структура затрат (таблица: Категория | $/ мес | % от расходов | Растёт с клиентами?), ## P&L прогноз (3 сценария: base/optimistic/pessimistic), ## Runway и break-even анализ, ## Инвестиционные потребности (сколько нужно и на что), ## ТАБЛИЦА РАБОТ ПО РОЛЯМ (обязательно!): таблица с колонками Роль | Задачи | Часов на MVP | Часов/месяц после | Ставка $/ ч | Стоимость MVP $"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПРЕДЫДУЩИЙ АНАЛИЗ ===\\n%phases_context%\\n\\nСоздай детальную финансовую модель. Обязательно включи таблицу работ по ролям (PM, Designer, Frontend Dev, Backend Dev, ML Engineer, QA, DevOps, Marketing). Все цифры должны быть реалистичными. Верни JSON с ключом phase_result.","transitions_before":[],"transitions_after":[]}'),
(179, 24, 3, 'Сохранить фазу', 2,
 '{"tool_invoke":{"tool_name":"planning_phase_save","inputs_map":{"project_id":"planning_project_id","phase":"planning_phase_name","result":"phase_result"},"outputs_map":{"saved":"phase_saved"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 25: planning_blueprint ─────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(180, 25, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(181, 25, 2, 'Compose Blueprint', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"главный Blueprint-документ продукта (2500-4000 слов Markdown). Структура документа:\\n# [Название продукта] — Blueprint\\n\\n## Executive Summary (200-300 слов — самое важное)\\n\\n## 1. Рынок и возможность (с таблицей конкурентов и TAM/SAM/SOM)\\n\\n## 2. Продукт (видение, MVP features таблица с MoSCoW приоритетами)\\n\\n## 3. Техническая архитектура (схема компонентов и стек)\\n\\n## 4. Go-to-Market (ICP, каналы, воронка)\\n\\n## 5. Финансовая сводка (unit-экономика, P&L таблица, инвестиции)\\n\\n## 6. Таблица работ по ролям (обязательно: Роль | Задачи | Часов на MVP | $/ч | Стоимость)\\n\\n## 7. Дорожная карта (таблица: Фаза | Срок | Ключевые deliverables)\\n\\n## 8. Риски и митигация (таблица: Риск | Вероятность | Влияние | Митигация)\\n\\n## 9. Ключевые метрики успеха\\n\\n## 10. Следующие шаги (топ-5 действий на ближайшие 2 недели)\\n\\n---\\n*Дополнения: [Market Deep Dive](supplement_market) | [Financial Model](supplement_financial) | [Tech Architecture](supplement_tech) | [GTM Strategy](supplement_gtm) | [Launch Plan](supplement_launch)*"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПОЛНЫЙ АНАЛИЗ ВО ВСЕХ ФАЗАХ ===\\n%phases_context%\\n\\nСоздай главный Blueprint-документ продукта. Это сжатый но максимально насыщенный сводный документ. Используй данные из всех фаз анализа. Обязательно включи все таблицы. Верни JSON с ключом phase_result.","transitions_before":[],"transitions_after":[]}'),
(182, 25, 3, 'Сохранить Blueprint', 2,
 '{"tool_invoke":{"tool_name":"planning_document_save","inputs_map":{"project_id":"planning_project_id","doc_type":"planning_doc_type","title":"planning_doc_title","content":"phase_result"},"outputs_map":{"saved":"doc_saved","doc_id":"doc_id"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 26: planning_supplement ────────────────────────────────────────
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES
(183, 26, 3, 'Загрузить проект', 0,
 '{"tool_invoke":{"tool_name":"planning_project_load","inputs_map":{"project_id":"planning_project_id"},"outputs_map":{"idea":"project_idea","phases_context":"phases_context"}},"transitions_before":[],"transitions_after":[]}'),
(184, 26, 2, 'Compose Supplement', 1,
 '{"llm_to_json_variable":[{"variable":"phase_result","text":"детализированное дополнение к Blueprint для направления: %planning_supplement_type% (2000-3000 слов Markdown). Раскрой это направление максимально глубоко с конкретными данными, таблицами, примерами и actionable рекомендациями. Начни с # [Название направления] — Детальный анализ"}],"prompt_user":"=== ИДЕЯ ПРОДУКТА ===\\n%project_idea%\\n\\n=== ПОЛНЫЙ АНАЛИЗ ===\\n%phases_context%\\n\\nНаправление для детализации: %planning_supplement_type%\\n\\nСоздай детализированное дополнение к Blueprint для этого направления. Максимальная глубина, конкретные данные, таблицы. Верни JSON с ключом phase_result.","transitions_before":[],"transitions_after":[]}'),
(185, 26, 3, 'Сохранить Supplement', 2,
 '{"tool_invoke":{"tool_name":"planning_document_save","inputs_map":{"project_id":"planning_project_id","doc_type":"planning_supplement_type","title":"planning_doc_title","content":"phase_result"},"outputs_map":{"saved":"doc_saved","doc_id":"doc_id"}},"transitions_before":[],"transitions_after":[]}');

-- ─── Workflow 27: planning_bot_chat ──────────────────────────────────────────
-- Без LLM: маршрутизация через чипсы [[]], continue_workflow для сбора ввода
-- Greeting агента показывает чипсы; первое сообщение = chip-текст или свободная идея
INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) VALUES

-- ── Маршрутизация ────────────────────────────────────────────────────────────
(186, 27, 5, 'Маршрутизация', 0,
 '{"variable_conversion":[{"variable":"bot_action","text":"%prompt_user%"}],"transitions_before":[],"transitions_after":[{"variable":"bot_action","operator":"==","value":"Статус проекта","step_id":"192"},{"variable":"bot_action","operator":"==","value":"Удалить проект","step_id":"200"},{"variable":"bot_action","operator":"==","value":"Создать проект","step_id":"187"},{"variable":"bot_action","operator":"!=","value":"Создать проект","step_id":"188"}]}'),

-- ── Create flow: спросить идею (только если кликнул чип "Создать проект") ───
(187, 27, 4, 'Спросить идею', 1,
 '{"prompt_user":"Опишите идею продукта:","continue_workflow":true,"transitions_before":[],"transitions_after":[]}'),

-- ── Create flow: сохранить идею ──────────────────────────────────────────────
(188, 27, 5, 'Сохранить идею', 2,
 '{"variable_conversion":[{"variable":"project_idea","text":"%prompt_user%"},{"variable":"bot_invoke_action","text":"create"},{"variable":"bot_invoke_project_id","text":"0"}],"transitions_before":[],"transitions_after":[]}'),

-- ── Create flow: создать проект ──────────────────────────────────────────────
(189, 27, 3, 'Создать проект', 3,
 '{"tool_invoke":{"tool_name":"planning_bot_action","inputs_map":{"action":"bot_invoke_action","title":"project_idea","idea":"project_idea","project_id":"bot_invoke_project_id"},"outputs_map":{"project_id":"created_project_id","title":"created_project_title"}},"transitions_before":[],"transitions_after":[]}'),

-- ── Create flow: результат (без ID) ─────────────────────────────────────────
(190, 27, 4, 'Проект создан', 4,
 '{"prompt_user":"✅ Проект сохранён! Cronicle запустит анализ в ближайшие минуты. Полный цикл (8 фаз + Blueprint) занимает 1–2 часа.\\n\\n[[Статус проекта]] [[Создать проект]]","continue_workflow":false,"transitions_before":[],"transitions_after":[]}'),

-- ── Status flow: получить список проектов ────────────────────────────────────
(192, 27, 3, 'Список проектов', 6,
 '{"tool_invoke":{"tool_name":"planning_projects_list","inputs_map":{},"outputs_map":{"display_str":"projects_display","id_chips":"projects_chips","count":"projects_count"}},"transitions_before":[],"transitions_after":[]}'),

-- ── Status flow: показать список с чипсами ───────────────────────────────────
(193, 27, 4, 'Выбрать проект', 7,
 '{"prompt_user":"%if projects_count%Выберите проект:\\n\\n%projects_display%%else%Проектов пока нет.\\n\\n[[Создать проект]]%endif%","continue_workflow":true,"transitions_before":[],"transitions_after":[]}'),

-- ── Status flow: сохранить выбранный ID и параметры ──────────────────────────
(194, 27, 5, 'Подготовить статус', 8,
 '{"variable_conversion":[{"variable":"query_project_id","text":"%prompt_user%"},{"variable":"bot_invoke_action","text":"status"},{"variable":"bot_invoke_title","text":""},{"variable":"bot_invoke_idea","text":""}],"transitions_before":[],"transitions_after":[]}'),

-- ── Status flow: запрос статуса ──────────────────────────────────────────────
(195, 27, 3, 'Получить статус', 9,
 '{"tool_invoke":{"tool_name":"planning_bot_action","inputs_map":{"action":"bot_invoke_action","title":"bot_invoke_title","idea":"bot_invoke_idea","project_id":"query_project_id"},"outputs_map":{"project_id":"status_project_id","title":"status_project_title","status":"status_project_status","phase_current":"status_phase_current","phases_summary":"status_phases_summary","documents_summary":"status_documents_summary"}},"transitions_before":[],"transitions_after":[]}'),

-- ── Status flow: показать статус ─────────────────────────────────────────────
(196, 27, 4, 'Показать статус', 10,
 '{"prompt_user":"**Проект #%status_project_id%**: %status_project_title%\\nСтатус: %status_project_status%\\nТекущая фаза: %status_phase_current%\\n\\n**Фазы:**\\n%status_phases_summary%\\n\\n%if status_documents_summary%**Документы:**\\n%status_documents_summary%\\n\\n%endif%[[Статус проекта]] [[Создать проект]]","continue_workflow":false,"transitions_before":[],"transitions_after":[]}'),

-- ── Delete flow ───────────────────────────────────────────────────────────────
(200, 27, 3, 'Список для удаления', 20,
 '{"tool_invoke":{"tool_name":"planning_projects_list","inputs_map":{},"outputs_map":{"display_str":"del_projects_display","id_chips":"del_projects_chips","count":"del_projects_count"}},"transitions_before":[],"transitions_after":[]}'),
(201, 27, 4, 'Выбрать для удаления', 21,
 '{"prompt_user":"%if del_projects_count%Выберите проект для удаления:\\n\\n%del_projects_display%%else%Проектов пока нет.\\n\\n[[Создать проект]]%endif%","continue_workflow":true,"transitions_before":[],"transitions_after":[]}'),
(202, 27, 5, 'Сохранить ID удаления', 22,
 '{"variable_conversion":[{"variable":"del_project_id","text":"%prompt_user%"}],"transitions_before":[],"transitions_after":[]}'),
(203, 27, 4, 'Подтвердить удаление', 23,
 '{"prompt_user":"Вы уверены, что хотите удалить «%del_project_id%»?\\n\\n[[!Да, удалить]] [[Отмена]]","continue_workflow":true,"transitions_before":[],"transitions_after":[]}'),
(204, 27, 5, 'Проверить подтверждение', 24,
 '{"variable_conversion":[{"variable":"del_confirm","text":"%prompt_user%"}],"transitions_before":[],"transitions_after":[{"variable":"del_confirm","operator":"!=","value":"Да, удалить","step_id":"206"}]}'),
(205, 27, 3, 'Удалить проект', 25,
 '{"tool_invoke":{"tool_name":"planning_project_delete","inputs_map":{"project_id":"del_project_id"},"outputs_map":{"deleted":"del_result","title":"del_project_title"}},"transitions_before":[],"transitions_after":[]}'),
(206, 27, 4, 'Результат удаления', 26,
 '{"prompt_user":"%if del_result%✅ Проект «%del_project_title%» удалён.%else%Отменено.%endif%\\n\\n[[Создать проект]] [[Статус проекта]] [[Удалить проект]]","continue_workflow":false,"transitions_before":[],"transitions_after":[]}');

-- === AGENTS ===

INSERT INTO `agent` (`id`, `node_id`, `name`, `title`, `description`, `workflow_id`, `workflow_variable`, `prompt_system`, `greeting`, `position`, `dynamic`) VALUES
(35, 9, 'planning_analyzer', 'Аналитик идей', 'Структурирует сырую идею продукта: аудитория, проблема, гипотеза, допущения',
 19, '{"planning_phase_name":"analyze"}',
 'Ты старший продуктовый стратег. Твоя задача — структурировать и углубить сырую идею продукта. Анализируй объективно, указывай как сильные стороны, так и слабые. Всегда отвечай на языке идеи (если идея на русском — анализ на русском).',
 '', 0, 0),

(36, 9, 'planning_market_researcher', 'Исследователь рынка', 'Проводит анализ рынка: конкуренты, тренды, размер, возможности',
 20, '{"planning_phase_name":"market"}',
 'Ты эксперт по рыночному анализу с опытом в стартапах и SaaS. Используй методологию TAM/SAM/SOM, анализ конкурентов (feature matrix), SWOT. Давай реалистичные оценки рынка — не завышай и не занижай. Указывай источники данных когда возможно.',
 '', 1, 0),

(37, 9, 'planning_product_planner', 'Продуктовый планировщик', 'Создаёт продуктовый план: видение, фичи (MoSCoW), MVP scope, дорожная карта',
 21, '{"planning_phase_name":"product"}',
 'Ты опытный product manager с опытом запуска B2B SaaS. Создавай чёткие, реалистичные продуктовые планы. Приоритизируй функции по методологии MoSCoW. MVP должен быть минимальным — только то, что абсолютно необходимо для проверки value proposition.',
 '', 2, 0),

(38, 9, 'planning_tech_architect', 'Технический архитектор', 'Проектирует техническую архитектуру: стек, компоненты, инфра, оценка сложности',
 22, '{"planning_phase_name":"tech"}',
 'Ты senior software architect с опытом в cloud-native приложениях, AI/ML системах и SaaS. Предлагай прагматичный стек под конкретную задачу. Оценивай сложность реалистично. Указывай технические риски честно.',
 '', 3, 0),

(39, 9, 'planning_gtm_strategist', 'GTM-стратег', 'Разрабатывает Go-to-Market стратегию: ICP, позиционирование, каналы, воронка',
 23, '{"planning_phase_name":"gtm"}',
 'Ты B2B GTM эксперт с опытом в product-led и sales-led компаниях. Создавай реалистичные GTM-стратегии. Каналы привлечения выбирай исходя из типа продукта и сегмента — не копируй шаблоны. CAC-оценки должны быть обоснованными.',
 '', 4, 0),

(40, 9, 'planning_financial_modeler', 'Финансовый моделист', 'Строит финансовую модель: unit-экономика, P&L, таблица работ по ролям',
 24, '{"planning_phase_name":"financial"}',
 'Ты финансовый аналитик специализирующийся на tech-стартапах. Строй реалистичные финансовые модели с тремя сценариями. Unit-экономика должна сходиться (LTV/CAC > 3). Таблица работ по ролям — обязательна с реальными часами и ставками.',
 '', 5, 0),

(41, 9, 'planning_blueprint_composer', 'Blueprint Composer', 'Создаёт главный Blueprint-документ — сжатый насыщенный сводный документ с таблицами',
 25, '{"planning_phase_name":"blueprint","planning_doc_type":"blueprint","planning_doc_title":"Blueprint"}',
 'Ты опытный технический писатель и product strategist. Создавай сводные документы, которые одновременно сжатые и максимально насыщенные. Каждый раздел Blueprint должен давать actionable информацию. Таблицы обязательны. Документ должен быть понятен инвестору, разработчику и маркетологу.',
 '', 6, 0),

(42, 9, 'planning_supplement_writer', 'Supplement Writer', 'Создаёт детализированные дополнения к Blueprint по конкретным направлениям',
 26, '{"planning_phase_name":"supplement","planning_doc_title":"Supplement"}',
 'Ты эксперт-аналитик. Создавай детализированные дополнения к основному Blueprint. Каждое дополнение должно раскрывать своё направление максимально глубоко: конкретные данные, примеры из индустрии, actionable рекомендации, детальные таблицы.',
 '', 7, 0),

(43, 9, 'planning_bot', 'Planning Bot', 'Принимает идеи продуктов и запускает AI-анализ; отвечает на вопросы о статусе и результатах',
 27, NULL,
 'Ты Planning Bot. Управляешь планированием продуктов через workflow без LLM.',
 'Привет! Я Planning Bot.\n\n[[Создать проект]] [[Статус проекта]] [[Удалить проект]]',
 8, 0);
