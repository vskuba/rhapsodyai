-- История правок workflow: кто, когда и что на что поменял (2026-10-03)
--
-- ЗАЧЕМ. 03.10.2026 цикл инвайтов перестал давать одиннадцать шаблонов и стал
-- давать один: у шага `workflow_invoke` поле `repeat.count` потеряло метку
-- `%invite_count%` и стало единицей. Потерял её редактор — поле было
-- `type="number"`, а сборка писала `parseInt(...) || 1`.
--
-- ⚠⚠ Ошибки при этом не было НИ ОДНОЙ: прогон шёл, пул набирался, панель
-- докладывала «готово 93». А следа правки — кто, когда, с чего на что — не было
-- нигде, и время поломки определяли косвенно: по числу разных текстов в чужой
-- базе, заход за заходом. Точность вышла три минуты.
--
-- Отсюда таблица: любая правка workflow оставляет запись.
--
-- ⚠ Это НЕ журнал прогонов. Прогоны лежат в `agent_workflow_trace_*` и
-- отвечают «как workflow работал»; здесь — «как его меняли». Разные предметы и
-- разные сроки жизни: трейс чистится, история переживает чистку.
--
-- Спека целиком — `.claude/docs/workflow_history.md`.

CREATE TABLE IF NOT EXISTS `agent_workflow_history` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    -- ⚠ Без внешнего ключа на `agent_workflow`: история обязана пережить
    -- удаление workflow, иначе запись «кто его удалил» исчезала бы вместе с ним.
    `workflow_id` INT NOT NULL,

    `object`      ENUM('workflow', 'step', 'variable') NOT NULL,

    -- Номер шага или переменной. Ноль — правка самого workflow.
    `object_id`   INT NOT NULL DEFAULT 0,

    -- ⚠⚠ Имя предмета КОПИЕЙ на момент правки, а не `JOIN`-ом. Это не
    -- денормализация ради скорости, а правда на момент события: запись
    -- «удалён шаг „Жребий“» после удаления шага иначе читалась бы как
    -- «удалён шаг #803».
    `object_name` VARCHAR(190) NOT NULL DEFAULT '',

    `action`      ENUM('create', 'update', 'delete', 'reorder', 'import') NOT NULL,

    -- Что именно изменилось: [{field, was, now}, …]. Полных снимков не держим.
    --
    -- ⚠ Длинные строки (промпты по 9 КБ) лежат здесь ПОСТРОЧНЫМ диффом — только
    -- изменившиеся строки с номерами. Решение человека: полный промпт в истории
    -- не нужен ни «до», ни «после».
    `changes`     JSON NULL,

    -- Кто правил. ⚠ `user_id = 0` при `author = 'agent'` — правка инструментом
    -- агента, человека за ней нет вовсе.
    `user_id`     INT NOT NULL DEFAULT 0,
    `username`    VARCHAR(190) NOT NULL DEFAULT '',
    `author`      ENUM('human', 'agent', 'import') NOT NULL DEFAULT 'human',

    -- ⚠⚠ Миллисекунды обязательны, и это не запас на будущее. Правка шага
    -- уходит в базу САМА через 400 мс после касания поля (автосохранение,
    -- `steps.js`), и две записи в одну секунду — обычное дело. На секундной
    -- точности лента перетасовалась бы.
    `created_at`  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (`id`),

    -- Лента вкладки: правки этого workflow, свежие сверху.
    INDEX `idx_workflow_history_workflow` (`workflow_id`, `created_at`),

    -- Отбор «что было с этим шагом».
    INDEX `idx_workflow_history_object` (`object`, `object_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = 'agent_workflow_history') AS таблица_есть,
       (SELECT COUNT(*) FROM information_schema.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = 'agent_workflow_history') AS столбцов_в_индексах;
