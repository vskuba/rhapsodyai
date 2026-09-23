-- Входящие переменные объявлены у своих workflow (2026-09-23)
--
-- ## ⚠⚠ ЗАЧЕМ: дыра, а не порядок ради порядка
--
-- `POST /chat/ask` подмешивает `variables` запроса **последними**, поверх всего:
--
--     workflow_variables_all = {**базовые, **агентские, **json_request.variables}
--
-- То есть вызывающий может переопределить **любую** внутреннюю переменную
-- workflow — не только ту, что ему предназначена.
--
-- Проверено живьём: в запрос положено `fact_collection_girl_name:
-- 'ЧУЖАЯ_КОЛЛЕКЦИЯ'`, и в трассе прогона стоит именно оно. То есть поиск и
-- запись фактов уводятся в чужое хранилище одним полем запроса. Так же уводится
-- `prompt_user`, `girl_id`, имя агента — что угодно.
--
-- ## Что делает эта миграция
--
-- Объявляет **входящими** (`type = 'input'`) те переменные, которые вызывающие
-- вправду присылают, и привязывает их к своим workflow. После этого код сможет
-- отвергать всё, чего в списке нет, — до сих пор такого списка просто не
-- существовало.
--
-- ⚠ Миграция сама ничего не запрещает: она готовит список. Запрет — в
-- `chat.py`, и без этого списка он отверг бы работающие вызовы.
--
-- ## ⚠⚠ `global` не трогаем
--
-- У `global` в движке своё значение: «переменные запроса, приносятся каждым
-- сообщением заново» — они намеренно не попадают в снимок сессии
-- (`ai_framework_manager`). `user_language` такая, и сменить ей тип значило бы
-- изменить поведение мастеров.
--
-- ## ⚠ Смена `workflow` → `input` безопасна
--
-- Тип читается ровно в двух местах: `ai_workflow_variables_input_get` (проверка
-- «есть ли в раскладке») и страница workflow. Проверка идёт **после**
-- `ai_workflow_variables_defaults_apply`, который кладёт умолчание каждой
-- переменной workflow, — то есть заход без неё по-прежнему проходит.
--
-- Идемпотентность: тип меняется `UPDATE`-ом, связи заводятся проверкой.

-- ── Что чему принадлежит ────────────────────────────────────────────────────
--
-- Списки сняты **с кода вызывающего** (`answer.py`, `mail_agent.py`), а не
-- придуманы: разбором `variables={...}` у каждого вызова. Разойдись они —
-- работающий вызов станет отвергаться.

-- ⚠⚠ **Кодировка задана явно, и без неё миграция падает на проде.**
--
-- Временная таблица без оговорки берёт кодировку **базы**, а не таблиц. У
-- `project` на проде база `utf8mb4_unicode_ci`, а таблицы `utf8mb4_0900_ai_ci` —
-- одна кодировка, разные сортировки, и сравнение `w.name = m.wf_name` отвечает
-- `ERROR 1267: Illegal mix of collations`.
--
-- ⚠ Локально это не воспроизводилось: там база `latin1_swedish_ci`, а разные
-- **кодировки** MySQL приводит молча — ошибка бывает только при одной кодировке с
-- разными сортировками. То есть локальный успех был случайностью чужой
-- настройки, а не признаком исправности.
--
-- Отсюда два правила ниже: явная кодировка у таблицы и явный `COLLATE` в каждом
-- сравнении — он весомее неявной кодировки столбца, и работает при любой
-- настройке установки.
CREATE TEMPORARY TABLE `wf_input_map` (
    `wf_name` CHAR(64) NOT NULL,
    `var_name` CHAR(64) NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

INSERT INTO `wf_input_map` (`wf_name`, `var_name`) VALUES
    -- Чат с девушкой: кладёт `answer.py`.
    ('dating_talk', 'talk_history'),
    ('dating_talk', 'companion_uid'),
    ('dating_talk', 'make_initiative'),
    ('dating_talk', 'initiative_kind'),
    ('dating_talk', 'chat_timeout'),
    ('dating_talk', 'girl_name'),
    ('dating_talk', 'companion_name'),
    ('dating_talk', 'companion_title'),

    -- Почта: кладёт `mail_agent.py`, по вызову на занятие.
    ('dating_mail_vars', 'girl_card'),
    ('dating_mail_vars', 'mail_var_names'),
    ('dating_mail_vars', 'mail_vars'),
    ('dating_mail_vars', 'mail_vars_json'),

    ('dating_mail_write', 'mail_angle'),
    ('dating_mail_write', 'mail_avoid'),
    ('dating_mail_write', 'mail_greeting'),
    ('dating_mail_write', 'mail_hint'),
    ('dating_mail_write', 'mail_length'),
    ('dating_mail_write', 'mail_story'),
    ('dating_mail_write', 'mail_var_live'),
    ('dating_mail_write', 'mail_var_must'),
    ('dating_mail_write', 'mail_var_names'),
    ('dating_mail_write', 'mail_vars'),

    ('dating_mail_question', 'companion_card'),
    ('dating_mail_question', 'girl_card'),

    ('dating_mail_reply', 'companion_card'),
    ('dating_mail_reply', 'girl_card'),
    ('dating_mail_reply', 'mail_history'),

    ('dating_invite_write', 'datetime_current_get_zone'),
    ('dating_invite_write', 'invite_angle'),
    ('dating_invite_write', 'invite_avoid'),
    ('dating_invite_write', 'invite_count'),
    ('dating_invite_write', 'invite_country'),
    ('dating_invite_write', 'invite_length'),
    ('dating_invite_write', 'invite_slots'),
    ('dating_invite_write', 'invite_time'),

    ('dating_favorite_mail_write', 'datetime_current_get_zone'),
    ('dating_favorite_mail_write', 'fav_angle'),
    ('dating_favorite_mail_write', 'fav_avoid'),
    ('dating_favorite_mail_write', 'fav_country'),
    ('dating_favorite_mail_write', 'fav_length'),
    ('dating_favorite_mail_write', 'fav_question'),
    ('dating_favorite_mail_write', 'fav_slots'),
    ('dating_favorite_mail_write', 'fav_story'),
    ('dating_favorite_mail_write', 'fav_time');

SELECT 'ДО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `type` = 'input')
         AS входящих_всего;

-- ── Тип: workflow → input ───────────────────────────────────────────────────
--
-- ⚠ `global` пропускаем явно: у него своё значение в движке.
UPDATE `agent_workflow_variable` v
   SET v.`type` = 'input'
 WHERE v.`type` = 'workflow'
   AND v.`name` IN (SELECT `var_name` COLLATE utf8mb4_0900_ai_ci
                      FROM `wf_input_map`);

-- ── Связь с workflow ────────────────────────────────────────────────────────

-- ⚠⚠ **Имя в реестре не уникально, и это ловушка.**
--
-- `companion_title` есть в трёх экземплярах: `global` (id 72), входящая чата
-- (id 80) и входящая **детектива** (id 158, «Отображаемое имя детектива-игрока»).
-- Привязка «по имени» цепляет все три, и на странице workflow появляются две
-- одинаковые строки с разными описаниями — видно на снимке страницы.
--
-- Поэтому условие двойное: не привязываем, если переменная **с таким именем**
-- у этого workflow уже есть. Первая подходящая закрывает вопрос, остальные
-- одноимённые остаются при своих workflow.
INSERT INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`)
SELECT v.`id`, w.`id`
  FROM `wf_input_map` m
  JOIN `agent_workflow` w
    ON w.`name` = m.`wf_name` COLLATE utf8mb4_0900_ai_ci
  JOIN `agent_workflow_variable` v
    ON v.`name` = m.`var_name` COLLATE utf8mb4_0900_ai_ci
 WHERE NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw
                    WHERE vw.`variable_id` = v.`id` AND vw.`workflow_id` = w.`id`)
   AND NOT EXISTS (SELECT 1 FROM `agent_workflow_variable_workflow` vw2
                     JOIN `agent_workflow_variable` v2 ON v2.`id` = vw2.`variable_id`
                    WHERE vw2.`workflow_id` = w.`id`
                      AND v2.`name` = m.`var_name` COLLATE utf8mb4_0900_ai_ci);

SELECT 'ПОСЛЕ' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_variable` WHERE `type` = 'input')
         AS входящих_всего;

-- Чего не хватило: имя из списка, которого нет в реестре. Пусто — всё нашлось.
SELECT 'НЕ НАЙДЕНО' AS этап, m.`wf_name`, m.`var_name`
  FROM `wf_input_map` m
  LEFT JOIN `agent_workflow_variable` v
    ON v.`name` = m.`var_name` COLLATE utf8mb4_0900_ai_ci
  LEFT JOIN `agent_workflow` w
    ON w.`name` = m.`wf_name` COLLATE utf8mb4_0900_ai_ci
 WHERE v.`id` IS NULL OR w.`id` IS NULL;

DROP TEMPORARY TABLE `wf_input_map`;
