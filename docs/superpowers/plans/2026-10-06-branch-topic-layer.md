# Ветки и темы: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завести открытый слой управления разговором: ветка — род разговора со своим контрактом и необязательным subflow, тема — запись с метками и тремя текстами (разрешено / желательно / запрещено); тему выбирает арифметика по меткам, а не зашитый в промпт перечень.

**Architecture:** Две таблицы (`agent_workflow_branch`, `agent_workflow_branch_topic`) + новый тип шага `branch`, который по строке меток находит победившую тему **по всему реестру ноды** и, если она принадлежит его ветке, кладёт семь `topic_*` переменных и (при наличии `workflow_id` у ветки) вызывает subflow той же подпрограммой, что `workflow_invoke`. Словарь меток для шага-развилки приезжает служебной переменной `%topic_catalog%`, заполняемой на старте прогона.

**Tech Stack:** Python 3.12, FastAPI, MySQL (aiomysql), pytest (httpx против стенда), ванильный JS в `data/uvicorn/public/js/`.

**Спека:** `docs/superpowers/specs/2026-10-06-branch-topic-layer-design.md` — читать перед началом.

## Global Constraints

- ⚠⚠ **Архитектуру workflow и его движка модель не придумывает** (`.claude/docs/workflow.md`, шапка). Этот план — запись решений владельца от 06.10.2026. Встретив место, где план расходится с кодом, — **спросить**, а не починить по-своему.
- Начальная схема `migrations/20260101000000_initial_schema.sql` заморожена; изменения — новым файлом.
- Миграции идемпотентны: `CREATE TABLE IF NOT EXISTS`, `INSERT … SELECT … WHERE NOT EXISTS`, колонки через `information_schema.COLUMNS` + `PREPARE`.
- Имена: таблицы `agent_workflow_branch`, `agent_workflow_branch_topic`; роутер `src/uvicorn/routers/workflow/workflow_branch.py`; пути ручек `/workflow_branch/…` (без `/api` — его вешает монтирование); страница `data/uvicorn/template/admin/workflow_branch.html`.
- Семь переменных темы: `topic_name`, `topic_title`, `topic_tags`, `topic_accept`, `topic_direction`, `topic_restrict`, `topic_score`.
- Тесты ходят по HTTP на `BASE_URL` (умолчание `http://localhost:8011`), логин — `TEST_AUTH` из `tests/constants.py`, модуль метится `pytestmark = pytest.mark.ai`. Чистые функции проверяются вызовом, без HTTP.
- ⚠ Прогон — **своим интерпретатором**: `.venv/bin/python -m pytest …`. Голый `python` в этой оболочке подхватывает venv соседнего проекта (DatingAi, 3.14) — тесты при этом зелёные, но проверено не то окружение, в котором работает стенд (3.12).
- ⚠ Миграции накатывает приложение при старте: применить — `docker restart uvicorn` (проект compose `rhapsodyai`). Проверять применённое по `_yoyo_migration`, а **не** по `mysql_migration_pending`: без `--source` он с базой не сверяется вовсе и печатает всё, что лежит в корне каталога.
- Коммит после каждой задачи. Сообщение — одной строкой по-русски, как в истории репозитория.

---

### Task 1: Миграция — две таблицы, `output` в ENUM, тип шага `branch`

**Files:**
- Create: `migrations/20261006150000_agent_workflow_branch.sql`

**Interfaces:**
- Produces: таблицы `agent_workflow_branch`, `agent_workflow_branch_topic`; значение `output` в `agent_workflow_variable.type`; строка `branch` в `agent_workflow_step_type`.

- [ ] **Step 1: Написать миграцию**

```sql
-- Ветки и темы: открытый слой управления разговором (2026-10-06)
--
-- ЗАЧЕМ. Особая тема разговора сегодня заведена одна — `photo_mail`, — и стоит
-- она в трёх местах текстом: перечень тем в промпте шага «Тема разговора»,
-- инструкции в промпте subflow `dating_talk_about_photo`, развилка переходом.
-- Вторая тема стоит subflow из трёх шагов, двух шагов у родителя и выкладки.
--
-- ⚠ Миграция, которой заведена первая тема, сама это предсказала: «ТЕМА —
-- СТРОКА, А НЕ ФЛАГ. Их будет больше одной: встречи, деньги, контакты».
--
-- Спека целиком — docs/superpowers/specs/2026-10-06-branch-topic-layer-design.md.

CREATE TABLE IF NOT EXISTS `agent_workflow_branch` (
    `id`          INT NOT NULL AUTO_INCREMENT,
    `node_id`     INT NOT NULL,
    `name`        VARCHAR(64)  NOT NULL,
    `title`       VARCHAR(255) NOT NULL,
    `description` TEXT NULL,

    -- Subflow ветки. ⚠ NULL — законное значение и основной случай: ветка
    -- «сужает» общий ответ, своей дороги у неё нет.
    `workflow_id` INT NULL DEFAULT NULL,

    -- Порог: сколько меток темы должно совпасть, чтобы тема вообще
    -- участвовала в выборе. ⚠ Живёт здесь, а не на шаге: на шаге строгая
    -- ветка глушила бы и чужие темы (спека §4.2).
    `match_min`   TINYINT NOT NULL DEFAULT 1,

    `is_enabled`  TINYINT NOT NULL DEFAULT 1,
    `position`    INT NOT NULL DEFAULT 0,
    `created_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_agent_workflow_branch_node_name` (`node_id`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agent_workflow_branch_topic` (
    `id`          INT NOT NULL AUTO_INCREMENT,
    `branch_id`   INT NOT NULL,
    `name`        VARCHAR(64)  NOT NULL,
    `title`       VARCHAR(255) NOT NULL,

    -- Метки через запятую, слова внутри метки через пробел: «обмен письмами».
    -- ⚠ Односложные метки не различают близкие темы: «письмо» стоит и в
    -- рассказе про письмо от деда, и в просьбе прислать фотографии.
    `tags`        TEXT NOT NULL,

    `acceptance`  TEXT NULL,
    `direction`   TEXT NULL,
    `restriction` TEXT NULL,
    `is_enabled`  TINYINT NOT NULL DEFAULT 1,
    `position`    INT NOT NULL DEFAULT 0,
    `created_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_agent_workflow_branch_topic_name` (`branch_id`, `name`),
    CONSTRAINT `fk_agent_workflow_branch_topic_branch` FOREIGN KEY (`branch_id`)
        REFERENCES `agent_workflow_branch` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── Объявленные выходы workflow ─────────────────────────────────────────────
--
-- ⚠ Без них «контракты ветки и subflow совпадают» непроверяемо. Побочная
-- выгода крупнее повода: сейчас `outputs_map` у tool-шагов движок игнорирует
-- молча, и в базе лежат тринадцать мёртвых карт в шести workflow.
SET @has_output = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_workflow_variable'
       AND COLUMN_NAME = 'type'
       AND COLUMN_TYPE LIKE '%output%'
);
SET @sql = IF(@has_output = 0,
    "ALTER TABLE `agent_workflow_variable`
        MODIFY `type` ENUM('global','input','workflow','output') NOT NULL DEFAULT 'workflow'",
    "SELECT 'ENUM уже содержит output'");
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ── Тип шага ────────────────────────────────────────────────────────────────
--
-- ⚠ Колонки сверены с живой схемой 06.10.2026: `title` у таблицы нет, а `icon`,
-- `description` и `metadata` объявлены NOT NULL. У соседей `metadata` пустая
-- строка (проверено на `workflow_invoke`), описание — короткая подпись в две-три
-- слова, иконка — один символ.
INSERT INTO `agent_workflow_step_type` (`name`, `icon`, `description`, `description_full`, `metadata`)
SELECT 'branch', '🌿', 'Ветка разговора',
       'Находит тему по меткам во всём реестре ноды и, если она принадлежит выбранной ветке, кладёт topic_* и вызывает subflow ветки',
       ''
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM `agent_workflow_step_type`) x
                    WHERE x.`name` = 'branch');

SELECT 'ГОТОВО' AS этап,
       (SELECT COUNT(*) FROM `agent_workflow_branch`) AS веток,
       (SELECT `id` FROM `agent_workflow_step_type` WHERE `name` = 'branch') AS тип_шага;
```

⚠ Колонки сверены 06.10.2026 — `PYTHONPATH=py_modules python -m mysql_.mysql_query columns agent_workflow_step_type`. Схема менялась и может поменяться: расходится — **поправить INSERT, а не схему**.

⚠ У `mysql_query` команда идёт **подкомандой**: `python -m mysql_.mysql_query sql "SELECT …"`. Без неё разбор доводов отвечает «invalid choice».

- [ ] **Step 2: Проверить, что миграция применяется и применяется дважды**

Run:
```bash
cd ~/PycharmProjects/RhapsodyAi
PYTHONPATH=py_modules python -m mysql_.migration.mysql_migration_pending
```
Expected: файл `20261006150000_agent_workflow_branch.sql` в списке к применению.

Применить и повторить прогон — второй раз файл обязан пройти без ошибки.

- [ ] **Step 3: Убедиться в схеме**

Run:
```bash
PYTHONPATH=py_modules python -m mysql_.mysql_query sql \
  "SHOW COLUMNS FROM agent_workflow_variable LIKE 'type'"
```
Expected: в `Type` присутствует `output`.

- [ ] **Step 4: Коммит**

```bash
git add migrations/20261006150000_agent_workflow_branch.sql
git commit -m "Ветки и темы: таблицы реестра, объявленные выходы workflow, тип шага"
```

---

### Task 2: Домен — разбор меток и выбор темы

**Files:**
- Create: `src/ai/ai_workflow_branch.py`
- Test: `tests/test_workflow_branch_pick.py`

**Interfaces:**
- Produces:
  - `ai_workflow_branch_tags_split(tags_raw: str) -> list[str]` — метки строкой → список приведённых, без повторов.
  - `ai_workflow_branch_pick(topics: list[dict], tags_raw: str) -> dict | None` — победившая тема или `None`.
  - Каждая запись `topics` обязана нести ключи `branch_id`, `match_min`, `tags`.

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_workflow_branch_pick.py`:

```python
"""
Выбор темы по меткам: счёт, порог ветки, ничья.

⚠ Без HTTP и без базы: правило выбора — чистая функция, и проверяется вызовом.
Живого LLM здесь нет тем более — метки подаются готовой строкой, как если бы
шаг-развилка уже отработал.
"""

from src.ai.ai_workflow_branch import ai_workflow_branch_pick, ai_workflow_branch_tags_split


def _topic(name, tags, branch_id=1, match_min=1):
    return {'name': name, 'tags': tags, 'branch_id': branch_id, 'match_min': match_min}


class TestTagsSplit:
    def test_splits_on_comma_and_normalises(self):
        assert ai_workflow_branch_tags_split(" Обмен  Письмами , пришли письмо ") == \
               ['обмен письмами', 'пришли письмо']

    def test_drops_repeats_and_empties(self):
        assert ai_workflow_branch_tags_split("письмо,, письмо ,") == ['письмо']

    def test_empty_gives_empty_list(self):
        assert ai_workflow_branch_tags_split('') == []


class TestPick:
    def test_more_matches_wins(self):
        """Ровно тот случай, ради которого счёт глобальный: тема соседней ветки
        с большим счётом обязана победить тему, стоящую в цепочке выше."""
        topics = [
            _topic('post_service', 'почта служба, письмо от родных', branch_id=2),
            _topic('photo_mail', 'обмен письмами, пришли письмо, интимное письмо', branch_id=1),
        ]
        picked = ai_workflow_branch_pick(topics, 'обмен письмами, пришли письмо, письмо от родных')
        assert picked['name'] == 'photo_mail'

    def test_below_own_branch_threshold_drops_out(self):
        topics = [_topic('photo_mail', 'обмен письмами, пришли письмо', match_min=2)]
        assert ai_workflow_branch_pick(topics, 'обмен письмами') is None

    def test_strict_branch_does_not_block_a_lenient_one(self):
        """Порог живёт в ветке, поэтому строгая ветка выбывает сама, а не уносит
        с собой годную тему соседней."""
        topics = [
            _topic('money', 'перевод денег, оплата письма', branch_id=2, match_min=3),
            _topic('photo_mail', 'обмен письмами, пришли письмо', branch_id=1, match_min=1),
        ]
        picked = ai_workflow_branch_pick(topics, 'перевод денег, обмен письмами')
        assert picked['name'] == 'photo_mail'

    def test_equal_score_decided_by_share(self):
        topics = [
            _topic('wide', 'а б, в г, д е, ж з'),
            _topic('narrow', 'а б, в г'),
        ]
        picked = ai_workflow_branch_pick(topics, 'а б, в г')
        assert picked['name'] == 'narrow'

    def test_equal_score_and_share_gives_nothing(self):
        topics = [_topic('one', 'а б, в г'), _topic('two', 'а б, в г')]
        assert ai_workflow_branch_pick(topics, 'а б, в г') is None

    def test_unknown_tag_matches_nothing(self):
        topics = [_topic('photo_mail', 'обмен письмами')]
        assert ai_workflow_branch_pick(topics, 'погода завтра') is None

    def test_no_tags_gives_nothing(self):
        topics = [_topic('photo_mail', 'обмен письмами')]
        assert ai_workflow_branch_pick(topics, '') is None
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `pytest tests/test_workflow_branch_pick.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ai.ai_workflow_branch'`

- [ ] **Step 3: Написать минимальную реализацию**

Create `src/ai/ai_workflow_branch.py`:

```python
"""
Реестр веток и тем: чтение и выбор темы по меткам.

Ветка — род разговора со своим контрактом и необязательным subflow. Тема — запись
внутри ветки: метки и три текста (разрешено / желательно / запрещено).

⚠⚠ Выбор идёт ПО ВСЕМУ реестру ноды, а не по темам одной ветки. Иначе цепочка
шагов берёт первую прошедшую порог, а не лучшую, и промахивается ровно там, ради
чего заведены двухсловные метки: «почта как служба» со счётом 2 у ветки, стоящей
выше, увела бы поток мимо «обмена письмами» со счётом 4.
"""

from mysql_.mysql_ import mysql_get_db_async


def ai_workflow_branch_tags_split(tags_raw: str) -> list[str]:
    """
    Метки строкой через запятую → список приведённых меток без повторов.

    Приведение: нижний регистр и схлопывание пробелов. Больше ничего не нужно —
    словарь закрытый, и модель возвращает нашу же строку.
    """
    if not tags_raw:
        return []

    tags = []
    for tag in str(tags_raw).split(','):
        tag = ' '.join(tag.split()).lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def ai_workflow_branch_pick(topics: list[dict], tags_raw: str) -> dict | None:
    """
    Выбрать тему: наибольший счёт совпавших меток, при равенстве — большая доля.

    Args:
        topics: записи тем с ключами `tags`, `branch_id`, `match_min`.
        tags_raw: метки, названные моделью, строкой через запятую.

    Returns:
        Запись победившей темы либо `None` — меток нет, никто не прошёл порог
        своей ветки, либо ничья по счёту и доле.
    """
    found = ai_workflow_branch_tags_split(tags_raw)
    if not found:
        return None

    best_mark = None
    best_topic = None
    best_tied = False

    for topic in topics:
        own = ai_workflow_branch_tags_split(topic.get('tags'))
        if not own:
            continue

        score = sum(1 for tag in own if tag in found)
        if score < int(topic.get('match_min') or 1):
            continue

        # ⚠ Доля — лекарство от перекоса: тема с двадцатью метками набирает
        # совпадений чаще темы с тремя просто потому, что меток больше.
        mark = (score, score / len(own))
        if best_mark is None or mark > best_mark:
            best_mark, best_topic, best_tied = mark, topic, False
        elif mark == best_mark:
            best_tied = True

    # ⚠ Ничья — это «темы нет». Неверная тема хуже отсутствия темы: она
    # подставит в промпт чужие инструкции, и отказ будет молчаливым.
    if best_topic is None or best_tied:
        return None
    return best_topic


async def ai_workflow_branch_topics(node_id: int) -> list[dict]:
    """Все включённые темы включённых веток ноды — материал для выбора."""
    sql = """
        SELECT t.`id`, t.`branch_id`, t.`name`, t.`title`, t.`tags`,
               t.`acceptance`, t.`direction`, t.`restriction`,
               b.`name` AS `branch_name`, b.`title` AS `branch_title`,
               b.`match_min`, b.`workflow_id`
          FROM `agent_workflow_branch_topic` t
          JOIN `agent_workflow_branch` b ON b.`id` = t.`branch_id`
         WHERE b.`node_id` = %s AND b.`is_enabled` = 1 AND t.`is_enabled` = 1
         ORDER BY b.`position` ASC, t.`position` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        return list(await db.fetchall())


async def ai_workflow_branch_catalog(node_id: int) -> str:
    """
    Плоский список меток всех включённых тем ноды, без повторов, через запятую.

    ⚠ Плоский и без группировки по темам намеренно: увидев группировку, модель
    выберет тему сама, и выбор перестанет быть детерминированным. Модель
    размечает — выбирает арифметика.
    """
    tags = []
    for topic in await ai_workflow_branch_topics(node_id):
        for tag in ai_workflow_branch_tags_split(topic.get('tags')):
            if tag not in tags:
                tags.append(tag)
    return ', '.join(tags)
```

- [ ] **Step 4: Прогнать тест и убедиться, что он проходит**

Run: `pytest tests/test_workflow_branch_pick.py -v`
Expected: PASS, 10 тестов.

- [ ] **Step 5: Коммит**

```bash
git add src/ai/ai_workflow_branch.py tests/test_workflow_branch_pick.py
git commit -m "Ветки и темы: разбор меток и правило выбора темы"
```

---

### Task 3: Служебная переменная `%topic_catalog%`

**Files:**
- Modify: `src/ai/framework/agent/ai_framework_manager.py` — в `_workflow_steps_run`, сразу после снапшота `variables_run_start` (около строки 318)
- Test: `tests/test_workflow_branch_catalog.py`

**Interfaces:**
- Consumes: `ai_workflow_branch_catalog` из Task 2.
- Produces: переменная `topic_catalog` в scope прогона при `depth == 0`.

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_workflow_branch_catalog.py`:

```python
"""
Словарь меток: что видит шаг-развилка «Тема разговора».

⚠ Без него перечень тем пришлось бы держать текстом в промпте — то, от чего
слой и уходит. Развилка стоит ДО шагов веток, и положить словарь ей некому.
"""

import pytest

from src.ai.ai_workflow_branch import ai_workflow_branch_catalog

pytestmark = pytest.mark.ai

TEST_NODE_ID = 2  # нода, на которой живёт dating_talk


class TestCatalog:
    async def test_catalog_is_flat_and_comma_separated(self):
        catalog = await ai_workflow_branch_catalog(TEST_NODE_ID)
        assert isinstance(catalog, str)
        # Группировки по темам в словаре быть не должно — только метки
        assert ':' not in catalog
        assert '\n' not in catalog

    async def test_catalog_has_no_repeats(self):
        catalog = await ai_workflow_branch_catalog(TEST_NODE_ID)
        tags = [tag.strip() for tag in catalog.split(',') if tag.strip()]
        assert len(tags) == len(set(tags))

    async def test_unknown_node_gives_empty_catalog(self):
        assert await ai_workflow_branch_catalog(999_343) == ''
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `pytest tests/test_workflow_branch_catalog.py -v`
Expected: FAIL на первых двух (словаря ещё нет — вернётся `''`, и `assert isinstance` пройдёт, а вот после Task 10 с сидами тесты станут содержательными). Третий обязан проходить сразу.

⚠ Если все три зелёные до сидов — это нормально: содержательными они станут после Task 10. Падать обязан **Step 4** ниже.

- [ ] **Step 3: Вставить заполнение переменной в движок**

В `src/ai/framework/agent/ai_framework_manager.py`, в `_workflow_steps_run`, сразу после строки `variables_run_start = dict(variables) if depth == 0 else {}`:

```python
        # Словарь меток тем ноды — для шага-развилки, который выбирает метки.
        #
        # ⚠ Служебная переменная, по образцу `user_language` и `node_languages`
        # у workflow_invoke: источник у неё реестр, а не родитель, и объявлять
        # её в каждом workflow не нужно.
        #
        # ⚠ Только на верхнем уровне: в sub-workflow она приедет сквозным
        # scope, второй запрос к базе на каждую ветку не нужен.
        if depth == 0:
            variables.setdefault(
                'topic_catalog',
                await ai_workflow_branch_catalog(model.entity_agent.get('node_id') or 0)
            )
```

Импорт в шапке файла:

```python
from src.ai.ai_workflow_branch import ai_workflow_branch_catalog, ai_workflow_branch_pick, ai_workflow_branch_topics
```

- [ ] **Step 4: Проверить, что стенд поднимается с новым импортом**

Проверка чтением исходника (`inspect.getsource`) из плана убрана: она сторожит текст, а не поведение. Вместо неё — перезапуск и журнал:

```bash
docker restart uvicorn
for i in $(seq 1 30); do code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8011/); \
  [ "$code" != "000" ] && echo "поднялся: $code" && break; sleep 4; done
docker logs uvicorn --since 120s 2>&1 | grep -iE "traceback|importerror|modulenotfound"
```
Expected: «поднялся: 307», grep пуст.

⚠⚠ Тесты `test_workflow_branch_catalog.py` — **синхронные и со своим циклом событий**: пул соединений лежит в модульной переменной и привязан к циклу, в котором создан, а pytest-asyncio заводит на каждый тест новый. Второй поход в базу иначе встречает пул закрытым («Event loop is closed»), и красным становится не то, что сломалось. Идиома — `asyncio.new_event_loop()` + `mysql_pool_close()` + `loop.close()`, та же, что у чисток в `conftest.py`.

- [ ] **Step 5: Коммит**

```bash
git add src/ai/framework/agent/ai_framework_manager.py tests/test_workflow_branch_catalog.py
git commit -m "Ветки и темы: словарь меток служебной переменной прогона"
```

---

### Task 4: Тип шага `branch` в движке

**Files:**
- Modify: `src/ai/framework/agent/ai_framework_manager.py` — новый `elif step_type == 'branch'` **перед** `elif step_type == 'workflow_invoke'` (около строки 847)
- Test: `tests/test_workflow_branch_step.py`

**Interfaces:**
- Consumes: `ai_workflow_branch_topics`, `ai_workflow_branch_pick` (Task 2).
- Produces: переменные `topic_name`, `topic_title`, `topic_tags`, `topic_accept`, `topic_direction`, `topic_restrict`, `topic_score`; алиас `branch_{step_id}_result_str` у ветки с subflow.

- [ ] **Step 1: Вынести вызов subflow в общую подпрограмму**

⚠⚠ Повторять 180 строк `workflow_invoke` нельзя: там защита от рекурсии, вложенная трассировка, `repeat` и алиасы. Выделить тело ветки `elif step_type == 'workflow_invoke'` (строки 848–1024) в метод:

```python
    async def _workflow_child_run(self, model, variables: dict, invoke_meta: dict,
                                  step_id: int, depth: int, workflow_stack: list | None,
                                  trace_run_id: int | None, scope_extra: dict | None = None) -> str:
        """Вызов вложенного workflow: один код на шаги `workflow_invoke` и `branch`.

        scope_extra — значения, которые кладутся в scope ребёнка ПОМИМО
        inputs_map. Шаг `branch` передаёт ими семь `topic_*`: объявлять их в
        контракте ребёнка не требуется, как не требуется объявлять
        `user_language`.
        """
```

Тело переносится без изменений, с двумя правками: `child_scope` после служебных переменных дополняется `scope_extra or {}`, а в конце возвращается `child_result or ''`. Шаг `workflow_invoke` после выноса зовёт метод и сам ставит `result_var` и `alias_var`.

- [ ] **Step 2: Прогнать существующие тесты workflow — вынос не должен ничего менять**

Run: `pytest tests/test_agent_workflow_steps.py -v`
Expected: PASS, столько же тестов, сколько до правки.

- [ ] **Step 3: Коммит выноса отдельно от нового шага**

```bash
git add src/ai/framework/agent/ai_framework_manager.py
git commit -m "Движок: вызов вложенного workflow вынесен в общую подпрограмму"
```

- [ ] **Step 4: Написать падающий тест на шаг**

Create `tests/test_workflow_branch_step.py`:

```python
"""
Шаг `branch`: выбор темы по всему реестру и поведение проигравшего шага.

⚠⚠ Главное здесь — третий тест. Проигравший шаг обязан НЕ ТРОГАТЬ переменные, а
не класть пустые строки: ветка, стоящая ниже победителя, затёрла бы его значения,
и «Генерация ответа» увидела бы пустоту при верно выбранной теме. Отказ был бы
молчаливым и плавал бы от порядка шагов.
"""

import pytest

from src.ai.ai_workflow_branch import ai_workflow_branch_pick

pytestmark = pytest.mark.ai

TOPIC_VARIABLES = ('topic_name', 'topic_title', 'topic_tags',
                   'topic_accept', 'topic_direction', 'topic_restrict', 'topic_score')


def _topics():
    return [
        {'id': 1, 'branch_id': 1, 'name': 'photo_mail', 'title': 'Письма и фото',
         'tags': 'обмен письмами, пришли письмо', 'acceptance': 'соглашайся',
         'direction': 'веди в письма', 'restriction': 'не обещай откровенного',
         'branch_name': 'deal', 'match_min': 1, 'workflow_id': None},
        {'id': 2, 'branch_id': 2, 'name': 'money', 'title': 'Деньги',
         'tags': 'перевод денег', 'acceptance': '', 'direction': '',
         'restriction': 'не проси денег',
         'branch_name': 'dodge', 'match_min': 1, 'workflow_id': None},
    ]


class TestBranchStepRules:
    def test_winner_is_global_not_per_branch(self):
        picked = ai_workflow_branch_pick(_topics(), 'обмен письмами, пришли письмо, перевод денег')
        assert picked['branch_id'] == 1

    def test_step_of_another_branch_must_not_claim_the_winner(self):
        picked = ai_workflow_branch_pick(_topics(), 'перевод денег')
        assert picked['branch_id'] == 2
        # Шаг ветки 1 обязан увидеть «не моя» и не вмешиваться
        assert picked['branch_id'] != 1

    def test_loser_leaves_variables_untouched(self):
        """Переменные победителя переживают проход проигравшего шага."""
        variables = {name: f'от победителя {name}' for name in TOPIC_VARIABLES}
        before = dict(variables)

        picked = ai_workflow_branch_pick(_topics(), 'перевод денег')
        my_branch_id = 1
        if picked is not None and int(picked['branch_id']) == my_branch_id:
            for name in TOPIC_VARIABLES:
                variables[name] = ''

        assert variables == before
```

- [ ] **Step 5: Прогнать — тест обязан пройти (правило чистое), затем дописать шаг в движок**

Run: `pytest tests/test_workflow_branch_step.py -v`
Expected: PASS — здесь проверяется правило, а не движок.

Вставить в `_workflow_steps_run` перед `elif step_type == 'workflow_invoke'`:

```python
            # ОБРАБОТКА ШАГА: Ветка разговора
            elif step_type == 'branch':
                branch_meta = step_meta.get('branch', {})
                branch_id = int(branch_meta.get('branch_id') or 0)
                tags_var = str(branch_meta.get('tags') or '').strip()
                step_id = current_step.get('id')

                if not branch_id:
                    raise ValueError(f"Шаг '{current_step['title']}': в branch не выбрана ветка.")

                node_id = model.entity_agent.get('node_id') or 0
                topics = await ai_workflow_branch_topics(node_id)
                topic = ai_workflow_branch_pick(topics, variables.get(tags_var, '') if tags_var else '')

                # ⚠⚠ Не моя тема — НЕ ТРОГАЕМ переменные вовсе. Пустые строки
                # здесь затёрли бы значения победителя, стоящего выше в цепочке.
                if topic is None or int(topic['branch_id']) != branch_id:
                    trace_output = ''
                    logger_info(
                        f"🌿 Ветка '{current_step['title']}': тема не моя "
                        f"({(topic or {}).get('name') or 'темы нет'}) — пропускаем"
                    )
                else:
                    found = ai_workflow_branch_tags_split(topic.get('tags'))
                    named = ai_workflow_branch_tags_split(variables.get(tags_var, '') if tags_var else '')
                    topic_scope = {
                        'topic_name': topic.get('name') or '',
                        'topic_title': topic.get('title') or '',
                        'topic_tags': topic.get('tags') or '',
                        'topic_accept': topic.get('acceptance') or '',
                        'topic_direction': topic.get('direction') or '',
                        'topic_restrict': topic.get('restriction') or '',
                        'topic_score': str(sum(1 for tag in found if tag in named)),
                    }
                    variables.update(topic_scope)
                    logger_info(f"🌿 Ветка '{current_step['title']}': тема '{topic.get('name')}'")

                    # Ветка со своей дорогой — вызов subflow общей подпрограммой.
                    # ⚠ Темовые переменные едут scope_extra: объявлять их в
                    # контракте ребёнка не требуется.
                    if topic.get('workflow_id'):
                        invoke_meta = dict(branch_meta)
                        invoke_meta['workflow_id'] = topic['workflow_id']
                        child_result = await self._workflow_child_run(
                            model, variables, invoke_meta, step_id, depth,
                            workflow_stack, trace_run_id, scope_extra=topic_scope
                        )
                        # ⚠⚠ Алиас НЕСЁТ НОМЕР ШАГА, и это не украшение: переход
                        # «я сработала» обязан проверять именно его. Проверка
                        # вида `topic_name != ''` сработала бы и у проигравшего
                        # шага, если выше по цепочке уже победила inline-ветка.
                        variables[f'branch_{step_id}_result_str'] = child_result
                        trace_output = child_result
```

Импорт `ai_workflow_branch_tags_split` добавить к импорту из Task 3.

- [ ] **Step 6: Прогнать сюиту workflow целиком**

Run: `pytest tests/test_agent_workflow_steps.py tests/test_workflow_branch_step.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add src/ai/framework/agent/ai_framework_manager.py tests/test_workflow_branch_step.py
git commit -m "Ветки и темы: тип шага branch в движке"
```

---

### Task 5: Права и ручки веток

**Files:**
- Modify: `src/auth/auth_permission.py` (после блока `WORKFLOW_VARIABLE_*`), `src/auth/auth_role.py:18` (список полной роли)
- Create: `src/uvicorn/routers/workflow/workflow_branch.py`
- Modify: точка подключения роутеров (там же, где подключён `workflow_variable`)
- Test: `tests/test_workflow_branch.py`

**Interfaces:**
- Produces: `GET /workflow_branch/list?node_id=`, `POST /workflow_branch`, `PUT /workflow_branch/{branch_id}`, `DELETE /workflow_branch/{branch_id}`. Ответ — `{"result": {...}}`, как у соседей.

- [ ] **Step 1: Добавить права**

В `src/auth/auth_permission.py`:

```python
    # Ветки разговора — вкладка «Branch»
    WORKFLOW_BRANCH_VIEW = "workflow_branch:view"
    WORKFLOW_BRANCH_CREATE = "workflow_branch:create"
    WORKFLOW_BRANCH_UPDATE = "workflow_branch:update"
    WORKFLOW_BRANCH_DELETE = "workflow_branch:delete"
```

В `src/auth/auth_role.py` — дописать четыре имени в тот же список, где стоит `AuthPermission.WORKFLOW_VARIABLE_VIEW`.

- [ ] **Step 2: Написать падающий тест**

Create `tests/test_workflow_branch.py`:

```python
"""
Ветки: заведение, правка, удаление, привязка subflow.

HTTP-часть идёт на стенд — ручки это контракт, и проверять их вызовом функций
значило бы не проверить ни маршрут, ни права.
"""

import os

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_BRANCH_PREFIX = 'test_branch_'
TEST_NODE_ID = 2


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        await client.post("/auth/login", json=TEST_AUTH)
        yield client


class TestBranchCrud:
    async def test_create_and_read(self, client: httpx.AsyncClient):
        response = await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID,
            "name": f"{TEST_BRANCH_PREFIX}deal",
            "title": "Договориться",
            "description": "",
            "workflow_id": None,
            "match_min": 1,
        })
        assert response.status_code == 200
        branch = response.json()["result"]
        assert branch["name"] == f"{TEST_BRANCH_PREFIX}deal"
        assert branch["match_min"] == 1
        assert branch["workflow_id"] is None

    async def test_match_min_default_is_one(self, client: httpx.AsyncClient):
        response = await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID,
            "name": f"{TEST_BRANCH_PREFIX}default",
            "title": "Умолчание порога",
        })
        assert response.json()["result"]["match_min"] == 1

    async def test_name_is_unique_in_node(self, client: httpx.AsyncClient):
        body = {"node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}twice", "title": "Дубль"}
        first = await client.post("/workflow_branch", json=body)
        assert first.status_code == 200
        second = await client.post("/workflow_branch", json=body)
        assert second.status_code == 400
```

- [ ] **Step 3: Прогнать и убедиться, что падает**

Run: `pytest tests/test_workflow_branch.py -v`
Expected: FAIL — `404 Not Found` на `POST /workflow_branch`.

- [ ] **Step 4: Написать роутер**

Create `src/uvicorn/routers/workflow/workflow_branch.py`:

```python
"""
Ветки разговора и темы внутри них: реестр для шага `branch`.

Ветка — род разговора со своим контрактом и необязательным subflow. Тема —
запись внутри ветки: метки и три текста. Правила выбора темы живут не здесь, а
в `src/ai/ai_workflow_branch.py`: здесь только хранение и контракт HTTP.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Колонки, которые принимаются снаружи. ⚠ Белым списком, а не `**body`:
# `id`, `node_id` и отметки времени правит сервер.
BRANCH_COLUMNS = ('name', 'title', 'description', 'workflow_id', 'match_min',
                  'is_enabled', 'position')


async def _branch_row(branch_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM `agent_workflow_branch` WHERE `id` = %s", (branch_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Ветка не найдена')
    return row


@router.get("/workflow_branch/list")
async def workflow_branch_list(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_VIEW]))
):
    sql = """
        SELECT b.*,
               (SELECT COUNT(*) FROM `agent_workflow_branch_topic` t
                 WHERE t.`branch_id` = b.`id`) AS `topic_count`
          FROM `agent_workflow_branch` b
         WHERE b.`node_id` = %s
         ORDER BY b.`position` ASC, b.`title` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = list(await db.fetchall())
    return {"result": rows}


@router.post("/workflow_branch")
async def workflow_branch_create(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_CREATE]))
):
    body = await request.json()
    node_id = int(body.get('node_id') or 0)
    name = str(body.get('name') or '').strip()
    if not node_id or not name:
        raise HTTPException(status_code=400, detail='Нужны node_id и name')

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT `id` FROM `agent_workflow_branch` WHERE `node_id` = %s AND `name` = %s",
            (node_id, name)
        )
        if await db.fetchone():
            raise HTTPException(status_code=400, detail='Ветка с таким именем в ноде уже есть')

        await db.execute(
            """INSERT INTO `agent_workflow_branch`
                      (`node_id`, `name`, `title`, `description`, `workflow_id`,
                       `match_min`, `is_enabled`, `position`)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (node_id, name, str(body.get('title') or name),
             body.get('description') or None,
             body.get('workflow_id') or None,
             int(body.get('match_min') or 1),
             int(body.get('is_enabled', 1)),
             int(body.get('position') or 0))
        )
        branch_id = db.lastrowid

    return {"result": await _branch_row(branch_id)}


@router.put("/workflow_branch/{branch_id}")
async def workflow_branch_update(
        branch_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_UPDATE]))
):
    body = await request.json()
    await _branch_row(branch_id)

    fields = {key: body[key] for key in BRANCH_COLUMNS if key in body}
    if not fields:
        return {"result": await _branch_row(branch_id)}

    # Привязка subflow проверяется контрактом — Task 7.
    if 'workflow_id' in fields and fields['workflow_id']:
        await _branch_contract_check(branch_id, int(fields['workflow_id']))

    sets = ', '.join(f"`{key}` = %s" for key in fields)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE `agent_workflow_branch` SET {sets} WHERE `id` = %s",
            (*fields.values(), branch_id)
        )

    return {"result": await _branch_row(branch_id)}


@router.delete("/workflow_branch/{branch_id}")
async def workflow_branch_delete(
        branch_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_DELETE]))
):
    await _branch_row(branch_id)
    async with mysql_get_db_async() as db:
        # Темы уносит каскад внешнего ключа
        await db.execute("DELETE FROM `agent_workflow_branch` WHERE `id` = %s", (branch_id,))
    return {"result": {"deleted": branch_id}}
```

⚠ `_branch_contract_check` появляется в Task 7 — до неё строку с проверкой закомментировать либо завести заглушку `async def _branch_contract_check(branch_id, workflow_id): return None` и убрать её в Task 7.

Подключить роутер там же, где подключены остальные из `routers/workflow/`.

- [ ] **Step 5: Прогнать тест**

Run: `pytest tests/test_workflow_branch.py -v`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add src/auth/auth_permission.py src/auth/auth_role.py \
        src/uvicorn/routers/workflow/workflow_branch.py tests/test_workflow_branch.py
git commit -m "Ветки: права и ручки реестра"
```

---

### Task 6: Ручки тем

**Files:**
- Modify: `src/uvicorn/routers/workflow/workflow_branch.py`
- Test: `tests/test_workflow_branch.py` (новый класс)

**Interfaces:**
- Produces: `GET /workflow_branch/{branch_id}/topic/list`, `POST /workflow_branch/{branch_id}/topic`, `PUT /workflow_branch/topic/{topic_id}`, `DELETE /workflow_branch/topic/{topic_id}`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_workflow_branch.py`:

```python
class TestTopicCrud:
    async def test_topic_lives_in_its_branch(self, client: httpx.AsyncClient):
        branch = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}topics", "title": "С темами",
        })).json()["result"]

        response = await client.post(f"/workflow_branch/{branch['id']}/topic", json={
            "name": "photo_mail", "title": "Письма и фотографии",
            "tags": "обмен письмами, пришли письмо",
            "acceptance": "Соглашайся охотно.",
            "direction": "Уводи разговор в письма.",
            "restriction": "Не обещай откровенного, не давай контактов вне сайта.",
        })
        assert response.status_code == 200
        topic = response.json()["result"]
        assert topic["branch_id"] == branch["id"]
        assert topic["tags"] == "обмен письмами, пришли письмо"

    async def test_topic_name_is_unique_in_node_not_only_in_branch(self, client: httpx.AsyncClient):
        """⚠ По коду тема называется в промптах и в журнале: два `money` в разных
        ветках сделали бы журнал нечитаемым."""
        first = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}uniq_a", "title": "A",
        })).json()["result"]
        second = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}uniq_b", "title": "B",
        })).json()["result"]

        await client.post(f"/workflow_branch/{first['id']}/topic",
                          json={"name": "money", "title": "Деньги", "tags": "перевод денег"})
        clash = await client.post(f"/workflow_branch/{second['id']}/topic",
                                  json={"name": "money", "title": "Деньги", "tags": "оплата письма"})
        assert clash.status_code == 400

    async def test_deleting_branch_takes_its_topics(self, client: httpx.AsyncClient):
        branch = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}cascade", "title": "Каскад",
        })).json()["result"]
        await client.post(f"/workflow_branch/{branch['id']}/topic",
                          json={"name": "gone_with_branch", "title": "Уйдёт", "tags": "метка"})

        assert (await client.delete(f"/workflow_branch/{branch['id']}")).status_code == 200
        listing = await client.get(f"/workflow_branch/{branch['id']}/topic/list")
        assert listing.status_code in (200, 404)
        if listing.status_code == 200:
            assert listing.json()["result"] == []
```

- [ ] **Step 2: Прогнать — падает на 404**

Run: `pytest tests/test_workflow_branch.py::TestTopicCrud -v`
Expected: FAIL.

- [ ] **Step 3: Дописать ручки тем**

Уникальность кода темы в ноде — отдельной проверкой перед вставкой (ключ в базе держит только пару «ветка + имя»):

```python
    check = """
        SELECT t.`id` FROM `agent_workflow_branch_topic` t
          JOIN `agent_workflow_branch` b ON b.`id` = t.`branch_id`
         WHERE b.`node_id` = %s AND t.`name` = %s AND t.`id` <> %s
    """
```

- [ ] **Step 4: Прогнать тест**

Run: `pytest tests/test_workflow_branch.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/uvicorn/routers/workflow/workflow_branch.py tests/test_workflow_branch.py
git commit -m "Ветки: ручки тем и уникальность кода темы в ноде"
```

---

### Task 7: Привязка subflow и кнопка «Создать subflow»

**Files:**
- Modify: `src/uvicorn/routers/workflow/workflow_branch.py`
- Test: `tests/test_workflow_branch.py` (новый класс)

**Interfaces:**
- Produces: `POST /workflow_branch/{branch_id}/subflow` — заводит скелет и привязывает; `PUT /workflow_branch/{branch_id}` отвергает `workflow_id` с несовпадающим контрактом.

- [ ] **Step 1: Написать падающий тест**

```python
class TestBranchSubflow:
    async def test_created_skeleton_has_two_steps(self, client: httpx.AsyncClient):
        """⚠⚠ Скелет из одного llm_to_json молча возвращал бы пустоту: движок
        отдаёт результат родителю только на return-шаге, а дойдя до конца
        списка без него, возвращает None — без ошибки."""
        branch = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}skeleton", "title": "Скелет",
        })).json()["result"]

        response = await client.post(f"/workflow_branch/{branch['id']}/subflow")
        assert response.status_code == 200
        workflow_id = response.json()["result"]["workflow_id"]

        steps = (await client.get(f"/workflow_step/list?workflow_id={workflow_id}")).json()["result"]
        assert len(steps) == 2
        assert [step["step_type_name"] for step in steps] == ['llm_to_json', 'return_response_text']

    async def test_skeleton_prompt_carries_topic_variables(self, client: httpx.AsyncClient):
        branch = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}skeleton_vars", "title": "Метки",
        })).json()["result"]
        workflow_id = (await client.post(f"/workflow_branch/{branch['id']}/subflow")).json()["result"]["workflow_id"]

        steps = (await client.get(f"/workflow_step/list?workflow_id={workflow_id}")).json()["result"]
        prompt = steps[0]["metadata"]["prompt_user"]
        for mark in ('%topic_accept%', '%topic_direction%', '%topic_restrict%'):
            assert mark in prompt

    async def test_attaching_foreign_subflow_is_refused(self, client: httpx.AsyncClient):
        """Контракты обязаны совпадать — иначе движок упадёт на проверке входа
        уже в проде, с именем непереданной переменной."""
        branch = (await client.post("/workflow_branch", json={
            "node_id": TEST_NODE_ID, "name": f"{TEST_BRANCH_PREFIX}foreign", "title": "Чужой",
        })).json()["result"]

        response = await client.put(f"/workflow_branch/{branch['id']}", json={"workflow_id": 9})
        assert response.status_code == 400
        assert 'контракт' in response.json()["detail"].lower()
```

- [ ] **Step 2: Прогнать — падает**

Run: `pytest tests/test_workflow_branch.py::TestBranchSubflow -v`
Expected: FAIL — `404` на `/workflow_branch/{id}/subflow`.

- [ ] **Step 3: Реализовать заведение скелета и проверку контракта**

Скелет: строка в `agent_workflow` с `subflow = 1`, `input`/`output`-переменные по контракту ветки, затем **два** шага. Промпт первого:

```python
SKELETON_PROMPT = (
    '=== %companion_title% пишет ===\n%prompt_user%\n\n'
    '%if talk_history%=== Разговор с этим человеком ===\n%talk_history%\n\n%endif%'
    '=== Что нужно ===\n'
    '%if topic_accept%%topic_accept%\n\n%endif%'
    '%if topic_direction%Куда вести разговор: %topic_direction%\n\n%endif%'
    '%if topic_restrict%⚠ Нельзя: %topic_restrict%\n\n%endif%'
    'Отвечай строго на языке: %user_language%.\n\n'
    '=== Important information about final response ===\n'
    'Please return your response in JSON format. The JSON response must contain '
    'follow keys: \n- "branch_response": твой ответ\n'
    '- "branch_result": чем кончилось, одним словом\n'
)
```

Второй шаг — `return_response_text` с `prompt_user` = `%branch_response%` и `continue_workflow: false`.

Проверка контракта у `PUT`: `input`-переменные выбранного workflow обязаны совпасть по именам с контрактом ветки; расхождение — `HTTPException(400, 'Контракт subflow не совпадает с контрактом ветки: …')`.

- [ ] **Step 4: Прогнать тест**

Run: `pytest tests/test_workflow_branch.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/uvicorn/routers/workflow/workflow_branch.py tests/test_workflow_branch.py
git commit -m "Ветки: скелет subflow из двух шагов и проверка совпадения контрактов"
```

---

### Task 8: Вкладка «Branch»

**Files:**
- Create: `data/uvicorn/template/admin/workflow_branch.html`, `data/uvicorn/public/js/workflow/branch.js`
- Modify: `src/uvicorn/routers/dashboard.py` (новый маршрут рядом с `/admin/workflow_trace`), шапка панели с пунктами меню

- [ ] **Step 1: Добавить маршрут страницы**

```python
@router.get("/admin/workflow_branch", response_class=HTMLResponse)
async def dashboard_workflow_branch_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/workflow_branch.html"
    )
```

- [ ] **Step 2: Нарисовать страницу в две колонки**

Выкройку списка и формы брать с существующей страницы переменных ноды, своей не рисовать. Слева — список веток с постраничной навигацией: название, код серым, точка «включена», число тем. Справа — карточка ветки (название, код, `match_min`, селект subflow с кнопкой «Создать subflow») и под ней список тем с формой из шести полей.

⚠ В строке темы показывать **число меток** — им виден перекос в пользу «жирных» тем (спека §4.2).

- [ ] **Step 3: Проверить руками**

Run: открыть `http://localhost:8011/admin/workflow_branch`, завести ветку, тему, нажать «Создать subflow».
Expected: ветка и тема сохраняются; кнопка заводит workflow и привязывает его; перезагрузка страницы показывает сохранённое.

- [ ] **Step 4: Коммит**

```bash
git add data/uvicorn/template/admin/workflow_branch.html \
        data/uvicorn/public/js/workflow/branch.js src/uvicorn/routers/dashboard.py
git commit -m "Ветки: вкладка Branch — список веток и форма темы"
```

---

### Task 9: Форма шага `branch` в редакторе

**Files:**
- Modify: `data/uvicorn/public/js/workflow/steps.js`, `data/uvicorn/public/js/workflow/graph.js`

- [ ] **Step 1: Добавить форму шага**

Поля: селект ветки (`branch_id`), поле имени переменной с метками (`tags`), карты `inputs_map` / `outputs_map` — те же виджеты, что у `workflow_invoke`. Контракт выбранной ветки подтягивать с сервера и показывать списками.

⚠⚠ Семь `topic_*` показывать **серым, без полей ввода**, с подписью «из темы»: карты для них нет намеренно — с ней один забытый маппинг выключал бы тему молча.

⚠ Значение в `inputs_map` — **короткое имя переменной**, не текст. Проверка перед сохранением та же, что у `tool_invoke`: длиннее ~50 символов — почти наверняка вставлен промпт.

- [ ] **Step 2: Научить граф рисовать ветку**

У шага `branch` с привязанным subflow — стрелка к нему, как у `workflow_invoke`.

⚠ Общую ложь графа («следующий по номеру» рисуется каждому нетерминальному шагу) эта задача **не чинит** — отдельная работа, см. спеку §11.

- [ ] **Step 3: Проверить руками**

Run: открыть workflow `dating_talk`, добавить шаг типа «Ветка разговора», выбрать ветку.
Expected: контракт показан, `topic_*` серым, сохранение проходит, перезагрузка показывает выбранное.

- [ ] **Step 4: Коммит**

```bash
git add data/uvicorn/public/js/workflow/steps.js data/uvicorn/public/js/workflow/graph.js
git commit -m "Редактор: форма шага branch и стрелка графа к subflow ветки"
```

---

### Task 10: Сиды — ветка «Договориться» и тема `photo_mail`

**Files:**
- Create: `migrations/20261006160000_branch_deal_photo_mail.sql`

- [ ] **Step 1: Написать миграцию с сидами**

Ветка `deal` («Договориться») на ноде `dating`, `match_min = 1`, `workflow_id` — номер существующего `dating_talk_about_photo`. Тема `photo_mail`: метки, а в `acceptance` / `restriction` — тексты, **перенесённые из нынешних промптов** subflow (четыре случая «он предлагает / он просит / он зовёт в письма / он спрашивает, почему не отвечаешь» и список запретов).

Метки темы — из двух слов и больше:

```
обмен письмами, пришли письмо, интимное письмо, перейти в письма,
прислать фотографии, покажи фото, скинь фотку, почему не отвечаешь письмом
```

⚠ Идемпотентность: `INSERT … SELECT … WHERE NOT EXISTS` по `name`.

- [ ] **Step 2: Применить и проверить словарь**

Run:
```bash
PYTHONPATH=py_modules python -m mysql_.mysql_query sql \
  "SELECT b.name, t.name, t.tags FROM agent_workflow_branch_topic t
     JOIN agent_workflow_branch b ON b.id = t.branch_id"
```
Expected: одна строка — `deal` / `photo_mail` / список меток.

- [ ] **Step 3: Прогнать тест словаря — теперь он содержателен**

Run: `pytest tests/test_workflow_branch_catalog.py -v`
Expected: PASS, и `catalog` непустой.

- [ ] **Step 4: Коммит**

```bash
git add migrations/20261006160000_branch_deal_photo_mail.sql
git commit -m "Ветки: сид ветки «Договориться» и темы про письма и фотографии"
```

---

### Task 11: Перевод `dating_talk` на слой

**Files:**
- Create: `migrations/20261006170000_wf_talk_branch_step.sql`

- [ ] **Step 1: Переписать промпт шага «Тема разговора»**

Перечень `photo_mail` / `usual` заменяется словарём: `%topic_catalog%`, и модель просят выбрать из него подходящие метки. Выход шага — `topic_tags` вместо `talk_topic`:

```
'=== Известные метки ===\n%topic_catalog%\n\n'
'=== Что нужно ===\n'
'Выбери из списка выше метки, подходящие к последней реплике. Своих не придумывай.\n'
'Не подходит ни одна — верни пустую строку.\n\n'
'- "topic_tags": метки через запятую\n'
```

- [ ] **Step 2: Заменить два шага ветки одним шагом `branch`**

Вместо `workflow_invoke` «Ветка: письма и фото» встаёт шаг типа `branch` с `branch_id` ветки `deal` и `tags: "topic_tags"`.

⚠⚠ Переход «я сработала» обязан проверять `branch_{step_id}_result_str` оператором `exists`, **а не** `topic_name != ''`: при inline-ветке, победившей выше по цепочке, второе сработало бы и у проигравшего шага.

- [ ] **Step 3: Переписать «Ответ ветки»**

Сегодня там `%workflow_invoke_{id}_result_str%` — станет `%branch_{step_id}_result_str%`.

⚠⚠ Не переписать — шаг отдаст **пустую строку**, молча: метка с пустым значением промпт не роняет. Номер шага в каждой установке свой, поэтому миграция обязана подставить его после вставки, а не зашивать числом.

- [ ] **Step 4: Вставить блоки темы в «Генерацию ответа» и судью**

В промпт генерации — `%if topic_accept%…%endif%`, `%if topic_direction%…%endif%`; в промпт валидации — `%if topic_restrict%…%endif%`.

- [ ] **Step 5: Объявить `topic_*` в реестре переменных workflow**

Семь переменных типа `workflow` с пустым умолчанием.

⚠ Без них сторож меток `ai_workflow_marks_check` уронит промпт, когда ни одна ветка не сработала: шаг, который можно пропустить, своей переменной не заводит (`workflow.md` §4a-bis).

- [ ] **Step 6: Прогнать разговор тестером**

Run: прогон `workflow_shell_test` (workflow 9, агент Workflow tester, нода Dev) по сценарию «просит прислать фотографии».
Expected: ответ идёт веткой; в журнале прогона у шага `branch` видно `topic_name = photo_mail` и `variables_changed` с семью `topic_*`.

Повторить по сценарию «рассказывает про письмо от деда».
Expected: тема не выбрана, ответ идёт обычным путём.

- [ ] **Step 7: Коммит**

```bash
git add migrations/20261006170000_wf_talk_branch_step.sql
git commit -m "dating_talk: тема выбирается слоем веток, ветка про фото переведена на критерии"
```

---

### Task 12: Документация

**Files:**
- Modify: `.claude/docs/workflow.md` (новый §4c), `.claude/docs/workflow/dating_talk.md` (§1 — карта шагов)
- Create: `.claude/docs/workflow_branch.md`

- [ ] **Step 1: Написать `.claude/docs/workflow_branch.md`**

Что такое ветка и тема, шесть полей темы, правило выбора, семь `topic_*`, две грабли (проигравший шаг не пишет; алиас с номером шага), вкладка.

- [ ] **Step 2: Дописать §4c в `workflow.md`**

Тип шага `branch` рядом с §4a (`llm_to_json`) и §4b (`tool_invoke`): метаданные, что кладёт сам, чем отличается от `workflow_invoke`.

- [ ] **Step 3: Обновить карту шагов в `dating_talk.md`**

- [ ] **Step 4: Коммит**

```bash
git add .claude/docs/workflow_branch.md .claude/docs/workflow.md .claude/docs/workflow/dating_talk.md
git commit -m "Документация: слой веток и тем, тип шага branch"
```

---

## Проверка перед сдачей

- [ ] Полный прогон: `pytest -m ai -v`
- [ ] ⚠ Чужого прогона в это время быть не должно — две сессии по одной базе дают плавающие падения: `pgrep -af "bin/python.*pytest"`
- [ ] Разговор без темы отвечает как до работы (обычный путь не тронут)
- [ ] Вкладка открывается, ветка и тема заводятся, «Создать subflow» даёт два шага
