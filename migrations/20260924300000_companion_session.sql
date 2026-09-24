-- Разговор пары живёт своей таблицей `companion_session` (2026-09-24)
--
-- ## ⚠⚠ ЗАЧЕМ
--
-- До сих пор переписка человека с анкетой не хранилась **нигде разборно**. Её
-- собирали на каждый вызов заново (`DatingAi/src/dating/talk_history.py`) и
-- отдавали агенту готовым текстом, а у нас она оседала только слепками:
--
--     agent_workflow_trace.variables_start   927 прогонов из 3252 несут ленту целиком
--     agent_session.content                  та же лента внутри собранного промпта
--
-- То есть разговор у нас был, но выбрать его по паре нельзя, отфильтровать по
-- времени нельзя, а каждый вызов дописывал ещё одну копию.
--
-- Теперь дом один, и он здесь. Читать историю положено отсюда — и промпту, и
-- страницам, и кому угодно ещё.
--
-- ## Строка — это обмен, а не реплика
--
-- Одна строка = «он спросил, мы ответили». Так разговор и устроен, и так его
-- видит агент.
--
-- ⚠ Обе половины могут пустовать, и обе — законно:
--
--     question пусто   заговорили мы: инвайт, рассылка, письмо избранному
--     answer пусто     не ответили: он написал дважды подряд, или ответа не было
--
-- ⚠⚠ Пустой `answer` — это **большинство**. На проде 42 145 входящих реплик
-- против 144 исходящих: панель забирает журнал сайта целиком, а отвечаем мы
-- единицам. Строка без ответа честно говорит «пришло, не ответили» — и её
-- отсутствие означало бы, что разговора не было вовсе.
--
-- ## ⚠ Обе стороны — записи `companion`
--
-- Девушка тоже лежит в справочнике (`…_companion_girls_from_panel`), поэтому
-- связей две и обе ведут туда же:
--
--     owner_id      наша сторона     643694_diana
--     companion_id  та сторона       10_dating_343_604366
--
-- Тот же ключ, которым ключуются факты пары (`%girl_unique_id%_%companion_unique_id%`),
-- так что память о человеке и разговор с ним сходятся сами, без третьего реестра.
--
-- ⚠ `owner_id`, а не `girl_id`: справочник общий на всю установку — в нём живут
-- и детектив, и телеграм. Имя поля не должно обещать, что там непременно девушка.
--
-- ## ⚠⚠ `kind` разделяет чат и почту, и сливать их нельзя
--
-- С человеком говорят двумя каналами, и это разные разговоры: чат идёт десятками
-- коротких реплик, письма — единицами длинных, часто других дней. Слитые в одну
-- ленту, письма вытолкнул бы чат на первом же пределе выборки, а отвечать на
-- письмо агент стал бы в регистре мессенджера.
--
-- ## Чего здесь нет намеренно
--
--     llm_id, token, role, kind_type   это работа `agent_session` — ради
--                                      разделения всё и затевается
--     site_id                          сайт уже сидит в ключе собеседника
--                                      (`dating_343_…`); копия разошлась бы

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `information_schema`.`TABLES`
         WHERE `TABLE_SCHEMA` = DATABASE()
           AND `TABLE_NAME` = 'companion_session') AS таблица_есть;

CREATE TABLE IF NOT EXISTS `companion_session` (
  `id`           int NOT NULL AUTO_INCREMENT,
  `owner_id`     int NOT NULL
                 COMMENT 'Наша сторона: запись в companion',
  `companion_id` int NOT NULL
                 COMMENT 'Та сторона: запись в companion',
  `kind`         enum('chat','mail') COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'chat'
                 COMMENT 'Каким каналом шёл разговор: реплики или письма',
  `question`     text COLLATE utf8mb4_general_ci NOT NULL
                 COMMENT 'Что написал он. Пусто — заговорили мы',
  `question_at`  datetime DEFAULT NULL
                 COMMENT 'Когда написал он',
  `answer`       text COLLATE utf8mb4_general_ci NOT NULL
                 COMMENT 'Что ответили мы. Пусто — не ответили',
  `answer_at`    datetime DEFAULT NULL
                 COMMENT 'Когда ответили мы',
  `source_uid`   varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL
                 COMMENT 'Ключ реплики у источника: ловит повтор переноса',
  `request_uuid` char(36) COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''
                 COMMENT 'Какой вызов LLM сочинил ответ: мост в agent_session',
  `created_at`   datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  -- ⚠⚠ `source_uid` умеет `NULL` **нарочно**: в MySQL `NULL` в уникальном ключе
  -- не сталкивается сам с собой. Реплики без номера у источника (наш инвайт,
  -- сочинённое письмо) лягут все, а повторный перенос того, у кого номер есть,
  -- не задвоится. Стой там пустая строка — вторая такая строка упёрлась бы в
  -- ключ, и перенос встал бы на первом же инвайте.
  UNIQUE KEY `uq_companion_session_source` (`owner_id`, `kind`, `source_uid`),
  -- ⚠ Порядок столбцов — под главный вопрос: «последние N обменов этой пары».
  -- Время впереди `id`, потому что перенесённые реплики приходят в базу позже,
  -- чем стоят в разговоре.
  KEY `idx_companion_session_pair` (`owner_id`, `companion_id`, `kind`,
                                    `question_at`, `id`),
  CONSTRAINT `fk_companion_session_owner` FOREIGN KEY (`owner_id`)
      REFERENCES `companion` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_companion_session_companion` FOREIGN KEY (`companion_id`)
      REFERENCES `companion` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='Разговор пары: обмен «он спросил — мы ответили», чатом или письмами';

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `information_schema`.`COLUMNS`
         WHERE `TABLE_SCHEMA` = DATABASE()
           AND `TABLE_NAME` = 'companion_session') AS столбцов,
       -- ⚠ Обе связи обязаны стоять: без них строка переживёт удаление того, о
       -- ком она, и разговор повиснет на номере, которого нет.
       (SELECT COUNT(*) FROM `information_schema`.`REFERENTIAL_CONSTRAINTS`
         WHERE `CONSTRAINT_SCHEMA` = DATABASE()
           AND `TABLE_NAME` = 'companion_session') AS связей,
       (SELECT COUNT(*) FROM `companion_session`) AS строк;
