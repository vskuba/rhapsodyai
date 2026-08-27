-- Замеры работы ролей — таблица `project_task_metric`.
--
-- Замеры работы ролей: объём контекста против времени, токенов и правок.
--
-- Зачем отдельная таблица, а не трасса. Трассу чистят: она про «что происходило
-- в этом прогоне», и её обрезают по возрасту (см. observability_rules). Здесь же
-- копится то, ради чего замер и делается, — средние по ролям и шагам, и ценность
-- у них растёт со временем.
--
-- **Задачу переживает.** FK на `project_task` нет намеренно: план сбрасывают,
-- подзадачи удаляют пачками, а замер с ними уходить не должен — иначе средние
-- обнуляются ровно тогда, когда по ним впервые захотели что-то посчитать.
-- Поэтому `task_id` — просто число, а название задачи лежит копией: по мёртвому
-- номеру уже ничего не восстановить, а строка в отчёте должна читаться.
-- Чистят таблицу руками (`/admin/task`, вкладка «Статистика»), и средние тогда
-- пересчитываются сами — они считаются запросом, а не хранятся.
--
-- `context_lines` — оценка менеджера при разбиении, а не фактический размер
-- правки. Сверять надо именно с ней: она делается заранее, и весь смысл в том,
-- предсказывает ли она время.
--
-- `lines_changed` — сколько кода круг реально изменил. Пишется один раз на круг,
-- на строке его последнего шага, а у остальных ноль: иначе сумма по задаче
-- считала бы одну и ту же правку столько раз, сколько в круге было шагов.
--
-- Токены — дельта накопительных счётчиков llama.cpp вокруг хода агента
-- (`llamacpp:tokens_predicted_total`). Модель одна и обслуживает один ход за раз,
-- поэтому дельта достаётся тому, кто её потратил. Ноль во всех трёх полях сразу
-- означает «счётчики недоступны», а не «модель молчала».
CREATE TABLE `project_task_metric` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `task_id` INT NOT NULL COMMENT 'Подзадача, чей шаг замерен; без FK — замер переживает её удаление',
    `parent_id` INT NULL DEFAULT NULL COMMENT 'Её задача — для разрезов по дереву',
    `task_title` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Копия названия: строку читают и после удаления задачи',
    `role` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'manager / developer / qa / bugfixer',
    `step_title` VARCHAR(190) NOT NULL DEFAULT '' COMMENT 'Название шага workflow',
    `attempt_no` INT NOT NULL DEFAULT '0' COMMENT 'Номер круга по строке',
    `context_lines` INT NOT NULL DEFAULT '0' COMMENT 'Оценка объёма менеджером при разбиении',
    `lines_changed` INT NOT NULL DEFAULT '0' COMMENT 'Строк кода изменено за круг; ненулевой один раз на круг',
    `duration_ms` INT NOT NULL DEFAULT '0',
    `tokens_output` INT NOT NULL DEFAULT '0' COMMENT 'Сгенерировано за шаг; 0 — счётчик недоступен',
    `tokens_prompt` INT NOT NULL DEFAULT '0' COMMENT 'Прочитано за шаг; 0 — счётчик недоступен',
    `tokens_per_sec` DECIMAL(8,2) NOT NULL DEFAULT '0.00' COMMENT 'Скорость модели в окне шага',
    `status` VARCHAR(16) NOT NULL DEFAULT '' COMMENT 'Исход шага: success / error',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_ptm_task` (`task_id`, `id`),
    INDEX `idx_ptm_parent` (`parent_id`, `id`),
    INDEX `idx_ptm_role_step` (`role`, `step_title`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
