-- Журнал ошибок установки: одна таблица, куда стекается всё сломавшееся (2026-09-26)
--
-- ## Зачем
--
-- Ошибки установки видны только тому, кто в этот момент смотрит в `docker logs`
-- или открыл `data/log/app.log` внутри контейнера. Воркер упал ночью, кронджоб
-- сорвался, роутер отдал 500 — узнаём об этом от человека, который «что-то не
-- работает», и дальше ищем по логам четырёх контейнеров. Страница трасс
-- (`/admin/workflow_trace`) показывает только падения workflow: всё, что
-- случилось вне движка, там не видно вовсе.
--
-- Теперь сюда пишет обработчик журнала (`src/error/error_log_handler.py`),
-- подвешенный к корневому логгеру: любой `logger_exception` / `logging.error` в
-- любом процессе установки оставляет здесь строку.
--
-- ## ⚠ Строка одна на отпечаток, а не на каждое падение
--
-- Сломавшийся цикл даёт одну и ту же ошибку каждую секунду: строка на каждую —
-- это десятки тысяч одинаковых записей за ночь и таблица, в которой ничего не
-- найти. Поэтому строка одна на `fingerprint` (источник + логгер + текст без
-- меняющихся чисел и uuid), а повторы считаются:
--
--   * `hits`     — сколько раз всего;
--   * `first_at` — когда сломалось впервые: видно, идёт это час или неделю;
--   * `last_at`  — когда в последний раз; по нему и сортируется журнал.
--
-- Так же устроен журнал отказов в соседнем проекте DatingAi (`dating_error`) —
-- приём проверен там на живом трафике.
--
-- ## Почему не в `browser_error`
--
-- `browser_error` — про живое окно браузера: у неё свои колонки (сессия, адрес
-- страницы, селектор) и свой потребитель (вкладка на `/admin/browser`). Общий
-- журнал установки сложил бы два разных предмета в одну ленту.

CREATE TABLE IF NOT EXISTS `error_log` (
    `id` INT NOT NULL AUTO_INCREMENT,
    -- Кто поймал: uvicorn, worker, telegram, cronjob. Строкой, а не перечислением:
    -- процессы заводятся по ходу дела, и миграция на каждый новый — цена,
    -- которой это не стоит.
    `source` VARCHAR(32) NOT NULL COMMENT 'Процесс, поймавший ошибку: uvicorn, worker, telegram, cronjob',
    `level` VARCHAR(16) NOT NULL DEFAULT 'ERROR' COMMENT 'ERROR или CRITICAL — ниже сюда не попадает',
    `logger` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Имя логгера — по нему видно подсистему',
    `message` TEXT NOT NULL COMMENT 'Текст ошибки — его и читает человек',
    `traceback` MEDIUMTEXT NULL COMMENT 'Трассировка целиком; NULL — записали без неё',
    `context` JSON NOT NULL COMMENT 'Где случилось: модуль, функция, строка, trace_id',
    -- Отпечаток «той же самой ошибки». Считает `error_log_fingerprint`; значение
    -- здесь, а не в коде страницы, потому что по нему стоит UNIQUE.
    `fingerprint` CHAR(32) NOT NULL COMMENT 'md5 источника, логгера и текста без меняющихся чисел',
    `hits` INT NOT NULL DEFAULT 1 COMMENT 'Сколько раз повторилась',
    `first_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        COMMENT 'Когда сломалось впервые — по нему видно, идёт это час или неделю',
    `last_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        COMMENT 'Последний раз; по нему журнал и сортируется',
    PRIMARY KEY (`id`),
    -- Одна строка на отпечаток: повтор бьётся в счётчик, а не в новую строку.
    UNIQUE KEY `uniq_error_log_fingerprint` (`fingerprint`),
    INDEX `idx_error_log_last` (`last_at`),
    INDEX `idx_error_log_source` (`source`, `last_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- Проверка
SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'error_log') AS есть_таблица,
       (SELECT COUNT(*) FROM `error_log`) AS записей;
