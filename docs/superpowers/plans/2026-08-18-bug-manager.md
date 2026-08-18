# Вкладка «Баги» и агент-багфиксер — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Отделить баги от тестовых задач своей вкладкой на `/admin/task` и завести роль `bugfixer` с агентом, который берёт баг в работу автоматически и одним прогоном доводит его до `done` либо `blocked`.

**Architecture:** Тип задачи `bug` переходит от роли `qa` к новой роли `bugfixer`. В конвейере появляется одно новое действие `bugfix`: захват корневой задачи типа `bug` в состояние `bugfixing`, прогон агента `task_bug_fixer` в своей shell-оболочке и своём git-worktree, запись результата в `done`/`failed`. Плана, подзадач и кругов «не сошлось» у бага нет — один прогон, один ответ.

**Tech Stack:** Python 3.11 (FastAPI/Uvicorn, aiomysql, rq/Redis), MySQL 8, Jinja2 + ванильный JS в `data/uvicorn/template/`, pytest поверх HTTP к запущенному uvicorn.

**Spec:** `docs/superpowers/specs/2026-08-18-bug-manager-design.md`

## Global Constraints

- Имя функции начинается с имени модуля: в `task_agent_bugfixer.py` — `task_agent_bugfixer_*`, в `task_role.py` — `task_role_*`. Приватные функции (`_name`) — всегда ниже публичных, в конце файла (`.claude/docs/architecture_rules.md`).
- Константы — UPPER_CASE с префиксом namespace: `TASK_METADATA_KEY_BUGFIX`, `TASK_SETTING_TIMEOUT_BUGFIX_RUN`.
- Схема БД меняется только в `migrations/0001.sql`. В этой работе схема **не меняется вовсе** — ни одного `ALTER TABLE`.
- Агенты и workflow — данные: заводятся в БД и переносятся seed-файлом из `data/seeds/`, не миграцией.
- Комментарии и docstring — по-русски, объясняют «почему», а не «что» (`.claude/docs-common/docs_rules.md`).
- После правки `.py` нужен `docker restart uvicorn worker_task` — иначе изменения не подхватятся.
- Тесты гоняются по HTTP к запущенному стеку: `.venv/bin/python3 -m pytest tests/... -v`, учётка из `tests/constants.py` (`QA_USERNAME`/`QA_PASSWORD` в `.env.local`).
- Ничего не коммитить и не пушить без явной просьбы владельца репозитория. Шаги «Commit» ниже выполняются только по его команде.
- Имена ролей и типов — часть контракта: роль `bugfixer`, тип `bug`, состояние `bugfixing`, ключ пометки `to_bugfix`, агент и workflow `task_bug_fixer`.

## Порядок и зависимости

```
Task 1  claude-shell --bugfixer  (чужой репозиторий)
Task 2  task_role.py         ──┐
Task 3  task_metadata.py     ──┤
Task 4  task_state.py        ──┼──> Task 6  task_claim.py
Task 5  task_setting_timeout ──┘
Task 7  task_agent_bugfixer.py
Task 8  task_pipeline.py        (нужны 2,3,4,5,6,7)
Task 9  task_stop.py            (нужны 3,7)
Task 10 team_project/member/agent  (нужен 7)
Task 11 workflow в БД + seed       (нужен 7)
Task 12 task.html
Task 13 тесты                      (нужны все)
Task 14 документация
```

---

### Task 1: Флаг `--bugfixer` в claude-shell

Оболочка знает свою роль из флага запуска и сообщает её в реестр сессий. Без флага карточка багфиксера никогда не станет живой, `task_role_shell_live_by_project()` роли не увидит, и захват не сработает ни разу.

**Files:**
- Modify: `/home/vasyl/PycharmProjects/claude-shell/src/cli.py` (другой git-репозиторий)

**Interfaces:**
- Produces: запуск `claude-shell --gx10 --bugfixer` регистрирует сессию с `role = 'bugfixer'` в `ai_claude_session_registry`.

- [ ] **Step 1: Посмотреть текущий разбор роли**

```bash
sed -n '1,20p;60,90p;115,135p' /home/vasyl/PycharmProjects/claude-shell/src/cli.py
```

Ожидается: строка примера `claude-shell --gx10 --qa`, функция `_role_of()` с ветками `args.qa` / `args.developer`, и `parser.add_argument("--qa", ...)`.

- [ ] **Step 2: Добавить строку в пример использования**

В docstring вверху файла, после строки с `--qa`:

```
  claude-shell --gx10 --bugfixer
```

- [ ] **Step 3: Добавить ветку в `_role_of()`**

После ветки `args.developer` (порядок веток роли не важен, важно только чтобы флаг проверялся):

```python
    if args.bugfixer:
        return "bugfixer"
```

- [ ] **Step 4: Зарегистрировать флаг**

Рядом с `add_argument("--qa", ...)`:

```python
    parser.add_argument("--bugfixer", action="store_true",
                        help="роль команды: багфиксер (правит баги)")
```

- [ ] **Step 5: Проверить, что флаг разбирается**

```bash
cd /home/vasyl/PycharmProjects/claude-shell && python3 -c "
import sys; sys.path.insert(0, 'src')
import cli
p = cli.__dict__
print('--bugfixer' in open('src/cli.py').read())
"
claude-shell --help | grep bugfixer
```

Ожидается: `True` и строка `--bugfixer` в выводе `--help`.

- [ ] **Step 6: Commit (в репозитории claude-shell, по команде владельца)**

```bash
cd /home/vasyl/PycharmProjects/claude-shell
git add src/cli.py
git commit -m "Роль bugfixer: флаг --bugfixer"
```

---

### Task 2: Роль `bugfixer` в карте типов

**Files:**
- Modify: `src/project/task/task_role.py:32-48` (карты ролей), конец файла (новая функция перед приватными)
- Test: `tests/test_task_role_bugfixer.py` (создать)

**Interfaces:**
- Produces:
  - `TASK_ROLE_BUGFIXER = 'bugfixer'`
  - `TASK_ROLE_TYPES['bugfixer'] == ('bug',)`, `TASK_ROLE_TYPES['qa'] == ('test',)`
  - `TASK_ROLE_TITLE['bugfixer'] == 'Багфиксер'`
  - `task_role_planners_only(roles_by_project: dict) -> dict[int, list[str]]`
- Consumes: ничего.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_task_role_bugfixer.py`:

```python
"""
Роль bugfixer: тип `bug` принадлежит ей, а не QA, и в менеджерский захват она не попадает.

`task_role` импортируется внутри тестов, а не сверху файла: он тянет `mysql_`, который
читает `MYSQL_HOST` один раз при импорте, а подмену хоста на `localhost` ставят
сессионные фикстуры `conftest.py`.
"""


class TestTaskRoleBugfixer:

    def test_bug_type_belongs_to_bugfixer(self):
        from src.project.task.task_role import task_role_by_type
        assert task_role_by_type('bug') == 'bugfixer'

    def test_qa_keeps_only_test_type(self):
        from src.project.task.task_role import TASK_ROLE_TYPES
        assert TASK_ROLE_TYPES['qa'] == ('test',)
        assert TASK_ROLE_TYPES['bugfixer'] == ('bug',)

    def test_unknown_type_still_goes_to_manager(self):
        from src.project.task.task_role import task_role_by_type
        assert task_role_by_type('') == 'manager'
        assert task_role_by_type('что-то новое') == 'manager'

    def test_planners_only_drops_bugfixer(self):
        from src.project.task.task_role import task_role_planners_only
        live = {2: ['manager', 'bugfixer'], 3: ['bugfixer'], 0: ['qa']}
        assert task_role_planners_only(live) == {2: ['manager'], 0: ['qa']}

    def test_planners_only_survives_empty_input(self):
        from src.project.task.task_role import task_role_planners_only
        assert task_role_planners_only({}) == {}
        assert task_role_planners_only(None) == {}

    def test_bug_type_sql_selects_by_name(self):
        from src.project.task.task_role import task_role_type_sql
        sql, params = task_role_type_sql(['bugfixer'])
        assert 'project_task_type' in sql
        assert params == ['bug']
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: FAIL — `task_role_by_type('bug')` возвращает `'qa'`, а `task_role_planners_only` не существует (`ImportError`).

- [ ] **Step 3: Переписать карты ролей**

В `src/project/task/task_role.py` заменить блок `TASK_ROLE_TYPES` / `TASK_ROLE_TITLE`:

```python
# Роль багфиксера. Вынесена отдельной константой: её имя — часть контракта, по нему
# бьёт захват (`task_claim_task_bug`), карточка команды и флаг оболочки `--bugfixer`.
TASK_ROLE_BUGFIXER = 'bugfixer'

# Имена типов — ключи `project_task_type.name`, а не id: id зависят от установки,
# имена — часть контракта (их же читает промпт менеджера через `task_type`).
TASK_ROLE_TYPES = {
    'manager':           ('plan', 'research'),
    'developer':         ('dev',),
    'qa':                ('test',),
    TASK_ROLE_BUGFIXER:  ('bug',),
}

# Роли, которые пишут план. Багфиксер в список не входит: у бага плана не бывает, он
# идёт в работу сразу. Не отдели мы его здесь, `_claim_manager_plan` увидел бы живую
# карточку багфиксера, её тип `bug` — и отправил бы баг писать план менеджерским
# workflow, то есть ровно тем путём, от которого эта роль и уводит.
TASK_ROLE_PLANNERS = ('manager', 'developer', 'qa')

# Короткие имена для отчётов задачи — не то же самое, что заголовки карточек в
# `team_project`: там подпись под аватаром, здесь подлежащее в строке отчёта.
TASK_ROLE_TITLE = {
    'manager':           'Менеджер',
    'developer':         'Разработчик',
    'qa':                'QA',
    TASK_ROLE_BUGFIXER:  'Багфиксер',
}
```

- [ ] **Step 4: Добавить `task_role_planners_only`**

В `src/project/task/task_role.py`, публичная функция — ставим её после `task_role_project_sql` и **до** `task_role_shell_live_by_project`:

```python
def task_role_planners_only(roles_by_project) -> dict[int, list[str]]:
    """
    Тот же словарь живых оболочек, но без ролей, которые план не пишут.

    Нужен менеджерским захватам (`task_claim_task_unplanned`, `task_claim_task_review`):
    они отбирают задачи по типам живых ролей, а тип `bug` теперь принадлежит багфиксеру.
    Без фильтра менеджерский шаг забирал бы баг себе и писал ему план — работу, которой
    у бага нет.

    Проект, у которого после отсева не осталось ролей, из словаря выпадает целиком:
    пустой список ролей даёт в `task_role_type_sql` заведомо ложное условие, и держать
    его в словаре незачем.
    """
    planners: dict[int, list[str]] = {}
    for project_id, roles in (roles_by_project or {}).items():
        kept = [role for role in (roles or []) if role in TASK_ROLE_PLANNERS]
        if kept:
            planners[int(project_id or TASK_ROLE_PROJECT_NONE)] = kept

    return planners
```

- [ ] **Step 5: Запустить тест — должен пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 6 passed.

- [ ] **Step 6: Убедиться, что старые ссылки на `qa: ('bug', 'test')` не остались**

```bash
grep -rn "'bug', 'test'\|\"bug\", \"test\"" src/ tests/
```

Ожидается: пусто.

- [ ] **Step 7: Commit**

```bash
git add src/project/task/task_role.py tests/test_task_role_bugfixer.py
git commit -m "Роль bugfixer: тип bug уходит от QA, менеджерский захват его не видит"
```

---

### Task 3: Пометка «в багфикс» в metadata

**Files:**
- Modify: `src/project/task/task_metadata.py` (константа рядом с `TASK_METADATA_KEY_PLAN`, функция рядом с `task_metadata_plan_free_sql`, приватный помощник в конец файла)
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Produces:
  - `TASK_METADATA_KEY_BUGFIX = 'to_bugfix'`
  - `task_metadata_bugfix_free_sql(column: str = 'metadata') -> str`
- Consumes: ничего.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskMetadataBugfixFree:

    def test_key_name(self):
        from src.project.task.task_metadata import TASK_METADATA_KEY_BUGFIX
        assert TASK_METADATA_KEY_BUGFIX == 'to_bugfix'

    def test_free_sql_checks_explicit_false(self):
        from src.project.task.task_metadata import task_metadata_bugfix_free_sql
        sql = task_metadata_bugfix_free_sql()
        # Умолчание «включено», поэтому ищем именно отклонение — явный false.
        assert '$.to_bugfix' in sql
        assert '= FALSE' in sql
        assert sql.startswith('NOT COALESCE(')
        # COALESCE обёрнут вокруг сравнения, а не вокруг JSON_EXTRACT: иначе MySQL
        # приведёт JSON-значение к типу второго аргумента и условие станет ложным
        # для всех строк разом.
        assert 'JSON_EXTRACT' in sql and sql.index('JSON_EXTRACT') > sql.index('COALESCE')

    def test_free_sql_respects_column_name(self):
        from src.project.task.task_metadata import task_metadata_bugfix_free_sql
        assert 'JSON_VALID(t.metadata)' in task_metadata_bugfix_free_sql('t.metadata')

    def test_plan_free_sql_unchanged(self):
        from src.project.task.task_metadata import task_metadata_plan_free_sql
        sql = task_metadata_plan_free_sql()
        assert '$.to_planning' in sql
        assert sql.startswith('NOT COALESCE(')
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskMetadataBugfixFree -v
```

Ожидается: FAIL — `ImportError: cannot import name 'TASK_METADATA_KEY_BUGFIX'`.

- [ ] **Step 3: Добавить константу**

В `src/project/task/task_metadata.py`, сразу после блока `TASK_METADATA_KEY_PLAN`:

```python
# Пометка «в багфикс»: флажок на вкладке «Баги». Хранится наизнанку, как `to_planning`
# и `to_testing`, и по той же причине: заведённый баг по умолчанию идёт в работу сам,
# а решением человека является отказ — «этот пока не чинить». Ключа нет = баг чинится,
# снятый флажок пишется явным `false`.
#
# Читает захват (`task_metadata_bugfix_free_sql` в `task_claim_task_bug`), снимает
# остановка (`task_stop._task_stop_patch`) — на вкладке «Баги» этот флажок и есть
# выключатель фазы, как «в тестирование» на «Тестировании».
TASK_METADATA_KEY_BUGFIX = 'to_bugfix'
```

- [ ] **Step 4: Свести два одинаковых условия в один помощник**

Заменить тело `task_metadata_plan_free_sql` и добавить рядом `task_metadata_bugfix_free_sql`:

```python
def task_metadata_plan_free_sql(column: str = 'metadata') -> str:
    """
    Условие «планирование не запрещено человеком» — кусок SQL без параметров.

    Умолчание здесь «разрешено», поэтому и проверяется отклонение от него: явный
    `false` в `$.to_planning`. Отсутствующий ключ, NULL и битый JSON — это задача,
    которую никто не откладывал, и она к менеджеру идёт.

    Родителя, в отличие от остановки, не смотрим: план пишется только листьям, и
    строки с подзадачами захват отбрасывает раньше этого условия.
    """
    return _key_free_sql(TASK_METADATA_KEY_PLAN, column)


def task_metadata_bugfix_free_sql(column: str = 'metadata') -> str:
    """
    Условие «починка бага не запрещена человеком» — фильтр захвата в `task_claim_task_bug`.

    Устроено как `task_metadata_plan_free_sql`, отличается только ключом: умолчание
    «разрешено», проверяется отклонение — явный `false` в `$.to_bugfix`.

    Родителя не смотрим: баг всегда корневая строка, подзадач у него не бывает.
    """
    return _key_free_sql(TASK_METADATA_KEY_BUGFIX, column)
```

- [ ] **Step 5: Добавить приватный помощник в конец файла**

В самый конец `src/project/task/task_metadata.py`, после всех публичных функций:

```python
def _key_free_sql(key: str, column: str) -> str:
    """
    Условие «пометка `key` не снята явным `false`» — общий вид для ключей с
    умолчанием «разрешено» (`to_planning`, `to_bugfix`).

    Без параметров намеренно: путь в JSON — константа, а условие подставляется в
    `where`, который в захвате повторяется дважды (SELECT и UPDATE, см. `_task_claim`),
    и второй список параметров пришлось бы тянуть через все вызовы.

    `COALESCE` обёрнут вокруг сравнения, а не вокруг `JSON_EXTRACT`, — та же ловушка,
    что в `task_metadata_stop_sql`: у второго аргумента тип не JSON, MySQL привёл бы к
    нему всё выражение, и условие стало бы ложным для всех строк разом. Ошибка тихая:
    синтаксис верный, смысл потерян.
    """
    return (f"NOT COALESCE(JSON_EXTRACT(IF(JSON_VALID({column}), {column}, '{{}}'), "
            f"'$.{key}') = FALSE, FALSE)")
```

- [ ] **Step 6: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 10 passed.

- [ ] **Step 7: Commit**

```bash
git add src/project/task/task_metadata.py tests/test_task_role_bugfixer.py
git commit -m "Пометка to_bugfix и общий помощник условий отбора по metadata"
```

---

### Task 4: Состояние `bugfixing` и закрытие задачи в `done`

**Files:**
- Modify: `src/project/task/task_state.py:516-531` (карта статусов), после `task_state_task_fail` (строка ~308)
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `_TASK_STATE_KANBAN['bugfixing'] == 'active'`
  - `async task_state_task_done(task_id: int, report: str) -> None`

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskStateBugfixing:

    def test_bugfixing_is_active(self):
        from src.project.task.task_state import task_state_kanban_status
        assert task_state_kanban_status('bugfixing') == 'active'

    def test_failed_stays_blocked(self):
        from src.project.task.task_state import task_state_kanban_status
        # Провалившийся баг человек видит как «Заблокировано» — отдельного маппинга
        # для него не нужно, `failed` уже ведёт туда.
        assert task_state_kanban_status('failed') == 'blocked'
        assert task_state_kanban_status('done') == 'done'

    def test_task_done_is_public_coroutine(self):
        import inspect
        from src.project.task.task_state import task_state_task_done
        assert inspect.iscoroutinefunction(task_state_task_done)
        assert list(inspect.signature(task_state_task_done).parameters) == ['task_id', 'report']
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskStateBugfixing -v
```

Ожидается: FAIL — `task_state_kanban_status('bugfixing')` возвращает `''`, `task_state_task_done` не существует.

- [ ] **Step 3: Добавить состояние в карту статусов**

В `src/project/task/task_state.py`, в словарь `_TASK_STATE_KANBAN`, строкой после `'reviewing': 'active',`:

```python
    # Баг у багфиксера: работа идёт прямо сейчас, значит «В работе». Своё состояние,
    # а не `developing`, потому что `developing` бывает только у подзадач плана, и
    # карты реклейма у корневых строк и подзадач разные.
    'bugfixing':        'active',
```

- [ ] **Step 4: Добавить `task_state_task_done`**

В `src/project/task/task_state.py`, сразу после `task_state_task_fail`:

```python
async def task_state_task_done(task_id: int, report: str) -> None:
    """
    Закрыть корневую задачу как выполненную: `pipeline_state = done`, `status = done`.

    Отдельно от `task_state_task_finalize()`: та закрывает задачу по терминальности её
    подзадач, а у бага подзадач нет вовсе — финализация его просто не увидит.

    Обе оси ставим разом, потому что решение об этом принял агент: у бага нет ни
    утверждения плана человеком, ни приёмки QA, и «конвейер закончил, а человек ещё
    нет» здесь означало бы просто забытую строку.

    Блокировку снимаем той же правкой, а `pipeline_error` чистим: у бага, дошедшего до
    `done` со второго захода, там осталась бы причина прошлого срыва.

    `task_state_kanban_sql` не даёт перебить статус отменённой и остановленной строки —
    прогон, доигрывающий свой конец в воркере, не воскресит их своим `done`.
    """
    kanban_sql, kanban_params = task_state_kanban_sql('done')
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = 'done', {kanban_sql}, pipeline_error = '', "
            "pipeline_locked_at = NULL, pipeline_locked_by = '' WHERE id = %s",
            kanban_params + [task_id],
        )
        await db.connection.commit()

    await task_report_write(task_id, report)
    logger_info(f'[task] task#{task_id} -> done')
```

- [ ] **Step 5: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 13 passed.

- [ ] **Step 6: Проверить, что модуль импортируется**

```bash
.venv/bin/python3 -c "import ast; ast.parse(open('src/project/task/task_state.py').read()); print('ok')"
```

Ожидается: `ok`.

- [ ] **Step 7: Commit**

```bash
git add src/project/task/task_state.py tests/test_task_role_bugfixer.py
git commit -m "Состояние bugfixing и закрытие бага в done"
```

---

### Task 5: Настройка `timeout_bugfix_run`

**Files:**
- Modify: `src/project/task/task_setting_timeout.py:24-38` (ключи), `:52-65` (реестр), `:176-198` (проверка лестницы)
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: ничего.
- Produces: `TASK_SETTING_TIMEOUT_BUGFIX_RUN = 'timeout_bugfix_run'`, строка реестра с `role='bugfixer'`, участие ключа в проверке лестницы.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskSettingTimeoutBugfix:

    def test_registry_has_bugfix_item(self):
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_BUGFIX_RUN, TASK_SETTING_TIMEOUT_ITEMS)
        item = next(i for i in TASK_SETTING_TIMEOUT_ITEMS
                    if i['key'] == TASK_SETTING_TIMEOUT_BUGFIX_RUN)
        assert item['default'] == 3600
        assert item['role'] == 'bugfixer'
        assert item['group'] == 'Агент'

    def test_ladder_counts_bugfix_timeout(self):
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_BUGFIX_RUN, TASK_SETTING_TIMEOUT_MANAGER_RUN,
            TASK_SETTING_TIMEOUT_DEVELOPER_RUN, TASK_SETTING_TIMEOUT_QA_RUN,
            TASK_SETTING_TIMEOUT_TASK_LOCK, TASK_SETTING_TIMEOUT_WORKER_JOB,
            task_setting_timeout_ladder_problem)
        values = {
            TASK_SETTING_TIMEOUT_MANAGER_RUN: 3600,
            TASK_SETTING_TIMEOUT_DEVELOPER_RUN: 3600,
            TASK_SETTING_TIMEOUT_QA_RUN: 3600,
            TASK_SETTING_TIMEOUT_BUGFIX_RUN: 3600,
            TASK_SETTING_TIMEOUT_WORKER_JOB: 3900,
            TASK_SETTING_TIMEOUT_TASK_LOCK: 4200,
        }
        assert task_setting_timeout_ladder_problem(values) == ''

        # Багфиксер, переросший job воркера, обязан ломать лестницу так же, как остальные.
        values[TASK_SETTING_TIMEOUT_BUGFIX_RUN] = 4000
        assert 'Ожидание агента' in task_setting_timeout_ladder_problem(values)
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskSettingTimeoutBugfix -v
```

Ожидается: FAIL — `ImportError: cannot import name 'TASK_SETTING_TIMEOUT_BUGFIX_RUN'`.

- [ ] **Step 3: Добавить ключ**

В `src/project/task/task_setting_timeout.py`, после `TASK_SETTING_TIMEOUT_QA_RUN`:

```python
TASK_SETTING_TIMEOUT_BUGFIX_RUN = 'timeout_bugfix_run'
```

- [ ] **Step 4: Добавить строку реестра**

В кортеж `TASK_SETTING_TIMEOUT_ITEMS`, после элемента `TASK_SETTING_TIMEOUT_QA_RUN`:

```python
    {'key': TASK_SETTING_TIMEOUT_BUGFIX_RUN, 'default': 3600, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_AGENT, 'role': 'bugfixer', 'unit': 'с',
     'title': 'Ответ багфиксера',
     'hint': 'Сколько ждать починку бага. Должно быть меньше job воркера.'},
```

- [ ] **Step 5: Включить ключ в проверку лестницы**

В `task_setting_timeout_ladder_problem` заменить вычисление `agent`:

```python
    # Потолок берём максимальный из агентских: лестницу ломает самый долгий прогон,
    # а не «средний по ролям» — job воркера убьёт любого из них одинаково.
    agent = max(int(values.get(TASK_SETTING_TIMEOUT_MANAGER_RUN) or 0),
                int(values.get(TASK_SETTING_TIMEOUT_DEVELOPER_RUN) or 0),
                int(values.get(TASK_SETTING_TIMEOUT_QA_RUN) or 0),
                int(values.get(TASK_SETTING_TIMEOUT_BUGFIX_RUN) or 0))
```

- [ ] **Step 6: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add src/project/task/task_setting_timeout.py tests/test_task_role_bugfixer.py
git commit -m "Настройка timeout_bugfix_run в реестре таймаутов"
```

---

### Task 6: Захват бага

**Files:**
- Modify: `src/project/task/task_claim.py:15-20` (импорты), `:58` (карта реклейма), после `task_claim_task_review` (строка ~163)
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: `TASK_ROLE_BUGFIXER`, `task_role_type_sql`, `task_role_project_sql` (Task 2); `task_metadata_bugfix_free_sql` (Task 3).
- Produces:
  - `TASK_CLAIM_STATE_RECLAIM['bugfixing'] == 'new'`
  - `async task_claim_task_bug(worker: str, roles_by_project) -> dict | None`

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskClaimBug:

    def test_reclaim_returns_bugfixing_to_new(self):
        from src.project.task.task_claim import TASK_CLAIM_STATE_RECLAIM
        # Брошенная блокировка возвращает баг в очередь, а не хоронит его.
        assert TASK_CLAIM_STATE_RECLAIM['bugfixing'] == 'new'

    def test_bugfixing_counts_as_inflight(self):
        from src.project.task.task_claim import TASK_CLAIM_INFLIGHT_STATES
        # Отсюда же берётся предел «Parallel LLM»: прогон занимает живую оболочку.
        assert 'bugfixing' in TASK_CLAIM_INFLIGHT_STATES

    def test_claim_task_bug_is_public_coroutine(self):
        import inspect
        from src.project.task.task_claim import task_claim_task_bug
        assert inspect.iscoroutinefunction(task_claim_task_bug)
        assert list(inspect.signature(task_claim_task_bug).parameters) == [
            'worker', 'roles_by_project']
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskClaimBug -v
```

Ожидается: FAIL — `KeyError: 'bugfixing'` и `ImportError: cannot import name 'task_claim_task_bug'`.

- [ ] **Step 3: Дописать импорты**

В `src/project/task/task_claim.py` заменить блоки импорта `task_metadata` и `task_role`:

```python
from src.project.task.task_metadata import (
    task_metadata_bugfix_free_sql,
    task_metadata_plan_free_sql,
    task_metadata_stop_free_sql,
    task_metadata_test_free_sql,
)
from src.project.task.task_role import (TASK_ROLE_BUGFIXER, task_role_project_sql,
                                        task_role_project_type_sql, task_role_type_sql)
```

- [ ] **Step 4: Дописать карту реклейма**

Заменить строку `TASK_CLAIM_STATE_RECLAIM`:

```python
# `bugfixing` возвращается в `new`: брошенная починка — это работа, которой не было,
# и баг снова встаёт в очередь к багфиксеру. В `failed` его такой возврат уводить не
# должен — там баг ждал бы человека из-за упавшего воркера, а не из-за самого бага.
TASK_CLAIM_STATE_RECLAIM = {'planning': 'new', 'reviewing': 'reviewing', 'bugfixing': 'new'}
```

- [ ] **Step 5: Добавить захват**

В `src/project/task/task_claim.py`, сразу после `task_claim_task_review`:

```python
async def task_claim_task_bug(worker: str, roles_by_project) -> dict | None:
    """
    Захватить баг и увести его в `bugfixing`.

    Вход в работу у бага автоматический: заведённая строка типа `bug` уходит
    багфиксеру ближайшим тиком. Плана он не пишет и утверждения не ждёт — чинить
    начинают сразу, поэтому и состояние тут одно, рабочее.

    Отбираем только корневые строки: подзадач у бага не бывает, а `parent_id IS NOT NULL`
    в этом состоянии означало бы строку чужого плана.

    `status <> 'cancelled'` стоит здесь явно, в отличие от остальных шагов. Те смотрят
    только на `pipeline_state`, и отменённая задача им не попадается по другой причине:
    у неё либо уже есть план, либо человек её в конвейер не заводил. У бага же по пути
    нет ни одного человеческого решения — без этого условия отменённый баг ушёл бы
    чиниться молча.

    Тип отбираем через `task_role_type_sql`, а не руками: условие по именам типов уже
    описано там, и второй его экземпляр разошёлся бы с первым при первой же правке карты.

    `roles_by_project` — живые оболочки в разрезе проектов (`task_role`). Роль здесь
    одна, `bugfixer`, и тип задан отдельным условием, поэтому берём
    `task_role_project_sql` (только проект), а не `task_role_project_type_sql`.
    Нет живой карточки — не берём вовсе: прогон сорвался бы на первом же обращении к
    оболочке, а баг ушёл бы в `failed` и потребовал человека на ровном месте.

    Снятый флажок «в багфикс» (`metadata.to_bugfix = false`) баг отсюда убирает: человек
    завёл его, но чинить пока не просит.
    """
    type_sql, type_params = task_role_type_sql([TASK_ROLE_BUGFIXER])
    role_sql, role_params = task_role_project_sql(roles_by_project, TASK_ROLE_BUGFIXER)
    return await _task_claim(
        "parent_id IS NULL AND (pipeline_state IS NULL OR pipeline_state = 'new') "
        f"AND status <> 'cancelled' AND {type_sql} "
        f"AND {task_metadata_bugfix_free_sql()} AND {role_sql}",
        type_params + role_params, 'bugfixing', worker)
```

- [ ] **Step 6: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 18 passed.

- [ ] **Step 7: Проверить SQL глазами на живой базе**

```bash
docker exec rhapsodyai-mysql-1 mysql -udeveloper -ppassword project --default-character-set=utf8mb4 -e "
SELECT id, title, status, pipeline_state
  FROM project_task
 WHERE parent_id IS NULL AND (pipeline_state IS NULL OR pipeline_state = 'new')
   AND status <> 'cancelled'
   AND task_type_id IN (SELECT id FROM project_task_type WHERE name IN ('bug'))
   AND NOT COALESCE(JSON_EXTRACT(IF(JSON_VALID(metadata), metadata, '{}'), '\$.to_bugfix') = FALSE, FALSE)
 LIMIT 5;"
```

Ожидается: запрос выполняется без ошибок (список может быть пустым — это нормально).

- [ ] **Step 8: Commit**

```bash
git add src/project/task/task_claim.py tests/test_task_role_bugfixer.py
git commit -m "Захват бага: task_claim_task_bug и реклейм bugfixing"
```

---

### Task 7: Модуль прогона `task_agent_bugfixer.py`

**Files:**
- Create: `src/project/task/task_agent_bugfixer.py`
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: `TASK_SETTING_TIMEOUT_BUGFIX_RUN` (Task 5).
- Produces:
  - `TASK_BUGFIXER_AGENT_NAME = 'task_bug_fixer'`
  - `TASK_BUGFIXER_ROLE = 'bugfixer'`
  - `async task_agent_bugfixer_run(task: dict, role: str = TASK_BUGFIXER_ROLE, work_dir: str = '', task_dir: str = '') -> dict` → `{'ok': bool, 'output': str, 'error': str}`

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskAgentBugfixer:

    def test_names(self):
        from src.project.task.task_agent_bugfixer import (
            TASK_BUGFIXER_AGENT_NAME, TASK_BUGFIXER_ROLE)
        assert TASK_BUGFIXER_AGENT_NAME == 'task_bug_fixer'
        assert TASK_BUGFIXER_ROLE == 'bugfixer'

    def test_run_signature(self):
        import inspect
        from src.project.task.task_agent_bugfixer import task_agent_bugfixer_run
        assert inspect.iscoroutinefunction(task_agent_bugfixer_run)
        assert list(inspect.signature(task_agent_bugfixer_run).parameters) == [
            'task', 'role', 'work_dir', 'task_dir']

    def test_result_parse_plain_json(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        out = _result_parse('json:{"ok": true, "report": {"summary": "починил"}, "error": ""}')
        assert out['ok'] is True
        assert 'починил' in out['output']
        assert out['error'] == ''

    def test_result_parse_report_ok_false_wins(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        # Прогон состоялся (внешний ok), но фикса нет (report.ok) — это `blocked`.
        out = _result_parse('json:{"ok": true, "report": {"ok": false, "error": "не воспроизвёлся"}}')
        assert out['ok'] is False
        assert out['error'] == 'не воспроизвёлся'

    def test_result_parse_garbage_is_not_an_exception(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        out = _result_parse('оболочка ответила текстом, а не JSON')
        assert out['ok'] is False
        assert 'не JSON' in out['error']

    def test_result_parse_missing_reason(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        out = _result_parse('json:{"ok": false}')
        assert out['ok'] is False
        assert out['error'] == 'Багфиксер не назвал причину отказа'
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskAgentBugfixer -v
```

Ожидается: FAIL — `ModuleNotFoundError: No module named 'src.project.task.task_agent_bugfixer'`.

- [ ] **Step 3: Создать модуль**

Создать `src/project/task/task_agent_bugfixer.py`:

```python
"""
Багфиксер конвейера задач: чинит один баг через свою shell-оболочку.

Устроен как QA (`task_agent_qa`) — агентный движок, агент `task_bug_fixer`, свой
workflow. Отличие в объёме работы: у бага нет плана, нет подзадач и нет второго круга.
Один прогон делает всё — воспроизводит, ищет причину, правит код, проверяет — и
возвращает вердикт. Не сошлось — баг уходит человеку в `blocked`, а не на новый круг:
второй заход по той же фактуре дал бы тот же ответ.

Роль `bugfixer` работает в каталоге проекта своей живой оболочкой, а код правит в
отдельной выкладке репозитория с веткой бага. Оболочка остаётся на месте, меняется
только рабочий каталог — так правки не задевают ни главную ветку, ни каталог человека.

Зовётся из воркера очереди (`src/worker/project/task_worker.py`), то есть из отдельного
процесса. Ошибки наружу отдаются исключением — `task_pipeline` ловит их и уводит баг в
повтор, воркер от этого не падает.
"""
import asyncio
import uuid

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import (ai_workflow_load, ai_workflow_variables_base,
                                ai_workflow_variables_defaults_apply)
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_plan import task_plan_goals_text
from src.project.task.task_role import task_role_project_server_url
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_BUGFIX_RUN,
    task_setting_timeout_get)
from src.project.task.task_worktree import task_worktree_branch
from src.project.team.team_session import team_session_restart_role

TASK_BUGFIXER_AGENT_NAME = 'task_bug_fixer'
TASK_BUGFIXER_ROLE = 'bugfixer'

# Потолок на весь прогон, а не сумма шагов: `timeout_bugfix_run` (3600s по умолчанию).
# Граница та же, что у остальных ролей: прогон агента < job воркера < блокировка строки.
# Значение правится на `/admin/team` — см. `task_setting_timeout`.
BUGFIXER_USER_ID = 1  # только для атрибуции session/log


async def task_agent_bugfixer_run(task: dict, role: str = TASK_BUGFIXER_ROLE,
                                  work_dir: str = '', task_dir: str = '') -> dict:
    """
    Починить один баг силами оболочки багфиксера.

    Args:
        task: строка бага. Из неё идут название, описание и `trace_meta` — у багов,
            заведённых сканером трейса, вся фактура лежит именно там: какой workflow,
            какой шаг и с каким текстом упал.
        role: чья оболочка чинит. По умолчанию `bugfixer`.
        work_dir: каталог проекта. Роль отвечает «кто», каталог — «в чьём проекте»:
            команды заведены на каждый проект отдельно, и багфиксеры разных проектов
            называются одинаково. Пустая строка — адресация только по роли.
        task_dir: рабочий каталог бага — своя выкладка репозитория с выкаченной веткой.
            Пустая строка — каталога нет, работаем в каталоге проекта.

    Returns:
        ok: баг починен, задачу можно закрывать.
        output: отчёт для журнала попыток и отчёта задачи.
        error: почему починить не удалось (пусто при ok) — этот текст уходит человеку
            в `pipeline_error`.
    """
    entity_agent = await _agent_get()
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise RuntimeError(f'у ноды агента {TASK_BUGFIXER_AGENT_NAME!r} нет LLM-моделей')

    workflow_id   = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid  = str(uuid.uuid4())
    prompt_user   = str(task.get('description') or task.get('title') or '')

    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=prompt_user,
            user_id=BUGFIXER_USER_ID,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        # Номер задачи промпту не нужен, но по нему карточка команды находит прогон в
        # трейсе и показывает, какой шаг идёт (`team_progress`).
        'task_id':          str(task.get('id') or ''),
        'task_title':       str(task.get('title') or ''),
        'task_description': str(task.get('description') or ''),
        'task_goals':       task_plan_goals_text(task.get('goals')),
        # Фактура автозаведённого бага: workflow, агент, шаг и текст ошибки. Пустая
        # строка ложна для `%if%` — у бага, заведённого руками, блок не раскроется.
        'task_trace_meta':  _trace_meta_text(task.get('trace_meta')),
        'task_shell_role':  role,
        'task_shell_work_dir': str(work_dir or ''),
        # Где править код. Ветка в каталоге уже выкачена конвейером — переключать её
        # багфиксеру не нужно и не должно.
        'task_work_dir':    str(task_dir or ''),
        'task_branch':      task_worktree_branch(int(task.get('id') or 0)),
        # Адрес сервера проекта — на нём багфиксер проверяет, что фикс работает. Нет
        # каталога бага — нет и своего сервера: проверять было бы негде.
        'task_server_url':  await task_role_project_server_url(
            (task or {}).get('project_id')) if task_dir else '',
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    # Ровно один перезапуск на прогон и до первого шага: оболочка поднимается заново, и
    # прошлый баг не попадает в контекст этого. Между шагами перезапускать нельзя — они
    # продолжают один разговор, и вердикт опирается на проверку, сделанную шагом раньше.
    await team_session_restart_role(role, work_dir)

    loop   = asyncio.get_running_loop()
    future = loop.create_future()

    agent_manager   = AiFrameworkAgentManager()
    framework_model = await agent_manager.framework_model_create({
        'entity_agent':       entity_agent,
        'entities_llm':       entities_llm,
        'workflow_steps':     workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':        prompt_user,
        'user_id':            BUGFIXER_USER_ID,
        'companion_id':       None,
        'session_uuid':       session_uuid,
        'tools':              await _tools_load(),
    })
    workflow_task = agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_BUGFIX_RUN)
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        # Отменяем сам прогон, а не только ожидание: иначе брошенный workflow
        # продолжает шагать и слать сообщения оболочке.
        workflow_task.cancel()
        future.cancel()
        raise RuntimeError(f'Багфиксер не уложился в {timeout}s')

    return _result_parse(result_text)


async def _agent_get() -> dict:
    entity_agent = await AgentRepository().find_one_by({'name': TASK_BUGFIXER_AGENT_NAME})
    if not entity_agent:
        raise RuntimeError(f'агент {TASK_BUGFIXER_AGENT_NAME!r} не найден')
    if not entity_agent.get('workflow_id'):
        raise RuntimeError(f'у агента {TASK_BUGFIXER_AGENT_NAME!r} не задан workflow')
    return entity_agent


async def _tools_load() -> dict:
    """
    Карта `имя -> путь` для шагов `tool_invoke`.

    Движок берёт список из метаданных модели, а не из БД, — без этой карты шаг
    `claude_shell_call` не найдёт инструмент и прогон встанет на первом же обращении
    к оболочке.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}


def _trace_meta_text(value) -> str:
    """
    `trace_meta` бага — в плоский текст для промпта.

    У бага, заведённого сканером трейса, это единственный источник фактуры: описание
    пересказывает ошибку словами, а здесь лежат номера прогона и шага, по которым её
    можно найти в журнале. Заведённый руками баг сюда не попадает вовсе — пустая
    строка ложна для `%if%`, и блок промпта не раскроется.
    """
    meta = json_from_string(value) if value else {}
    if not meta:
        return ''

    fields = (('workflow_title', 'Workflow'), ('workflow_id', 'ID workflow'),
              ('agent_name', 'Агент'), ('step_title', 'Шаг'), ('step_type', 'Тип шага'),
              ('trace_run_id', 'Прогон трейса'), ('trace_step_id', 'Шаг трейса'),
              ('error_summary', 'Ошибка'))
    lines = []
    for key, title in fields:
        text = str(meta.get(key) or '').strip()
        if text:
            lines.append(f'{title}: {text}')

    return '\n'.join(lines)


def _result_parse(result_text) -> dict:
    """
    Ответ шага `return_response_text` приходит с префиксом `json:`.

    Форма — `{"ok": bool, "report": {...}, "error": str}`, где внешний `ok` говорит
    «прогон состоялся», а `report.ok` — «баг починен». Различие не формальное:
    багфиксер может отработать безупречно и вернуть отрицательный вердикт («не
    воспроизводится», «нужен доступ, которого нет») — это не сбой прогона, но и не
    повод закрывать баг.

    Разбор терпимый к мусору: отчёт пишет живой Claude Code, и сорванный JSON (обрыв
    строки в тексте, лишний markdown) не должен ронять воркер исключением — иначе
    `task_pipeline` счёл бы это техническим срывом и запустил бы прогон заново, хотя
    работа была сделана.
    """
    raw    = str(result_text or '').removeprefix('json:').strip()
    parsed = json_from_string(raw)
    # `json_from_string` не бросает и не возвращает не-словарь: сорванный разбор,
    # массив вместо объекта и пустой ответ — всё это приходит пустым словарём.
    if not parsed:
        return {'ok': False, 'output': raw[:2000],
                'error': f'Багфиксер вернул не JSON: {raw[:200]}'}

    report = parsed.get('report')
    if not isinstance(report, dict):
        report = {}

    ok    = bool(parsed.get('ok', True)) and bool(report.get('ok', True))
    error = str(report.get('error') or parsed.get('error') or '').strip()
    if not ok and not error:
        error = 'Багфиксер не назвал причину отказа'

    return {'ok': ok, 'output': _report_text(report) or raw[:2000], 'error': error}


def _report_text(report: dict) -> str:
    """Отчёт багфиксера — в плоский текст для журнала попыток и отчёта задачи."""
    lines = []
    summary = str(report.get('summary') or '').strip()
    if summary:
        lines.append(summary)

    for key, title in (('cause', 'Причина'), ('files', 'Файлы'),
                       ('checks', 'Проверки'), ('error', 'Не сделано')):
        value = report.get(key)
        if isinstance(value, list):
            value = '; '.join(str(v).strip() for v in value if str(v).strip())
        value = str(value or '').strip()
        if value:
            lines.append(f'{title}: {value}')

    return '\n'.join(lines)
```

- [ ] **Step 4: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 24 passed.

- [ ] **Step 5: Проверить, что все импорты модуля разрешаются**

```bash
docker exec uvicorn python3 -c "
from src.project.task.task_agent_bugfixer import task_agent_bugfixer_run, TASK_BUGFIXER_ROLE
print('импорт ok:', TASK_BUGFIXER_ROLE)
"
```

Ожидается: `импорт ok: bugfixer`.

- [ ] **Step 6: Commit**

```bash
git add src/project/task/task_agent_bugfixer.py tests/test_task_role_bugfixer.py
git commit -m "Агент-багфиксер: прогон workflow через свою оболочку"
```

---

### Task 8: Действие `bugfix` в конвейере

**Files:**
- Modify: `src/project/task/task_pipeline.py:1-60` (docstring), `:61-127` (импорты), `:280-296` (порядок захвата), `:337-357` (менеджерские захваты), после `_claim_qa` (строка ~373), после `_run_qa` (строка ~574), `:899-907` (карта runner'ов)
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: `task_claim_task_bug` (Task 6), `task_agent_bugfixer_run` / `TASK_BUGFIXER_ROLE` (Task 7), `task_state_task_done` (Task 4), `task_role_planners_only` (Task 2).
- Produces: действие `{'kind': 'bugfix', 'task_id': int}` в очереди; запись `_RUNNERS['bugfix']`.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskPipelineBugfix:

    def test_runner_registered(self):
        from src.project.task.task_pipeline import _RUNNERS
        assert 'bugfix' in _RUNNERS

    def test_bugfix_claimed_after_developer_before_plan_split(self):
        import inspect
        from src.project.task import task_pipeline
        source = inspect.getsource(task_pipeline._action_claim)
        order = [name for name in ('_claim_qa', '_claim_developer', '_claim_bugfix',
                                   '_claim_plan_split', '_claim_manager_review',
                                   '_claim_manager_plan')
                 if name in source]
        assert order == ['_claim_qa', '_claim_developer', '_claim_bugfix',
                         '_claim_plan_split', '_claim_manager_review', '_claim_manager_plan']

    def test_manager_claims_filter_planners(self):
        import inspect
        from src.project.task import task_pipeline
        # Менеджерские захваты обязаны отсеивать багфиксера, иначе баг уйдёт писать план.
        for fn in (task_pipeline._claim_manager_plan, task_pipeline._claim_manager_review):
            assert 'task_role_planners_only' in inspect.getsource(fn)
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskPipelineBugfix -v
```

Ожидается: FAIL — `'bugfix'` нет в `_RUNNERS`.

- [ ] **Step 3: Дописать импорты**

В `src/project/task/task_pipeline.py`:

добавить строкой после импорта `task_agent_qa`:

```python
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE, task_agent_bugfixer_run
```

в блок импорта `task_claim` добавить `task_claim_task_bug,` (алфавитный порядок — после `task_claim_subtask_testable`);

в блок импорта `task_role` добавить `task_role_planners_only`:

```python
from src.project.task.task_role import (TASK_ROLE_DEFAULT, TASK_ROLE_TITLE, task_role_of_task,
                                        task_role_planners_only, task_role_project_work_dir,
                                        task_role_shell_live_by_project)
```

в блок импорта `task_state` добавить `task_state_task_done,` (после `task_state_subtasks_create,`).

- [ ] **Step 4: Добавить багфикс в порядок захвата**

В `_action_claim` заменить кортеж перебора:

```python
    for claim in (
        _claim_qa,
        _claim_developer,
        # Починка бага — такая же работа роли, как разработка, поэтому идёт до
        # планирования: закрыть начатое важнее, чем добавить незакрытого. После
        # разработки, а не до неё: подзадача идущего плана ближе к финишу, чем баг,
        # которым ещё не занимались.
        _claim_bugfix,
        # Разбор плана на подзадачи — перед менеджерскими шагами, но после работы
        # ролей: оболочки и похода в LLM тут нет, зато он даёт разработчику работу.
        _claim_plan_split,
        # Пересмотр — первый из менеджерских: на другом конце этого шага человек,
        # который нажал «Обновить план» и ждёт результата.
        _claim_manager_review,
        _claim_manager_plan,
    ):
```

- [ ] **Step 5: Отсечь багфиксера от менеджерских захватов**

Заменить первые строки `_claim_manager_review` и `_claim_manager_plan`:

```python
async def _claim_manager_review(worker: str, roles_by_project) -> dict | None:
    # Багфиксер плана не пишет: тип `bug` принадлежит ему, и без отсева менеджерский
    # шаг забрал бы баг себе (`task_role_planners_only`).
    task = await task_claim_task_review(worker, task_role_planners_only(roles_by_project))
```

```python
async def _claim_manager_plan(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task_unplanned(worker, task_role_planners_only(roles_by_project))
```

- [ ] **Step 6: Добавить `_claim_bugfix`**

В `src/project/task/task_pipeline.py`, сразу после `_claim_qa`:

```python
async def _claim_bugfix(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task_bug(worker, roles_by_project)
    if not task:
        return None
    await task_report_write(task['id'], 'Баг взят в работу (Багфиксер)', ok=None)
    return {'kind': 'bugfix', 'task_id': task['id']}
```

- [ ] **Step 7: Добавить `_run_bugfix`**

В `src/project/task/task_pipeline.py`, сразу после `_run_qa`:

```python
async def _run_bugfix(action: dict) -> str | None:
    """
    bugfixing -> done | failed.

    Один прогон, один ответ: кругов «не сошлось» у бага нет. `ok: false` — это
    состоявшаяся работа с отрицательным вердиктом («не воспроизводится», «причина вне
    проекта»), и второй заход по той же фактуре дал бы тот же ответ. Такой баг уходит
    человеку в `blocked` (через `failed`, который карта статусов и переводит в
    «Заблокировано»).

    Сорвавшийся прогон — другое дело: оболочка не ответила, Claude Code мёртв, вернулся
    не-JSON. Работы не было, и хоронить баг не за что — уходит на повтор тем же
    `_retry_task`, что и менеджер, с возвратом в `new`.

    Каталогов здесь два, и путать их нельзя. `work_dir` — адрес оболочки, там запущен
    живой Claude Code. `task_dir` — где лежит код, который правят: своя выкладка
    репозитория с веткой бага. Ключом выкладки идёт id самой задачи: у бага нет
    подзадач, и ветка у него своя, как у любого листа конвейера.
    """
    task = await task_state_task_get(int(action.get('task_id') or 0))
    if not task:
        return None

    started  = time.monotonic()
    work_dir = await task_role_project_work_dir(task.get('project_id'))
    task_dir = await _subtask_dir(work_dir, task['id'])

    try:
        result = await task_agent_bugfixer_run(
            task, role=TASK_BUGFIXER_ROLE, work_dir=work_dir, task_dir=task_dir)
    except Exception as e:
        return await _retry_task(task, 'bugfix', 'new', TASK_BUGFIXER_ROLE,
                                 work_dir, f'Багфиксер: {e}')

    await task_retry_clear(task['id'])
    # Попытка всегда первая: круг у бага один, и `pipeline_attempt_count` он не растит.
    # Строка журнала нужна ради времени прогона и текста отчёта — по ней видно, сколько
    # багфиксер думал и что сделал.
    await task_state_attempt_log(task['id'], 1, TASK_BUGFIXER_ROLE, result, started)

    if result.get('ok'):
        report = str(result.get('output') or '').strip() or 'отчёт не заполнен'
        await task_state_task_done(task['id'], f'Баг починен (Багфиксер): {report}')
        return f"task#{task['id']} bugfix -> done"

    error = str(result.get('error') or 'багфиксер не назвал причину')
    await task_state_task_fail(task['id'], f'Баг не починен: {error}')
    return f"task#{task['id']} bugfix -> failed"
```

- [ ] **Step 8: Зарегистрировать runner**

Заменить словарь `_RUNNERS`:

```python
_RUNNERS = {
    'bug_scan':       _run_bug_scan,
    'manager_review': _run_manager_review,
    'manager_plan':   _run_manager_plan,
    'plan_split':     _run_plan_split,
    'developer':      _run_developer,
    'qa':             _run_qa,
    'bugfix':         _run_bugfix,
    'finalize':       _run_finalize,
}
```

- [ ] **Step 9: Дописать машину состояний в docstring модуля**

В docstring `src/project/task/task_pipeline.py`, после блока про подзадачу, добавить:

```
    Баг.pipeline_state:
        (тип `bug`) -> bugfixing -> done | failed

    У бага нет плана, подзадач и второго круга: багфиксер воспроизводит, чинит и
    проверяет за один прогон. Отрицательный вердикт — это `failed`, то есть
    «Заблокировано» для человека, а не новый круг: та же фактура дала бы тот же ответ.
```

- [ ] **Step 10: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 27 passed.

- [ ] **Step 11: Перезапустить контейнеры и убедиться, что тик жив**

```bash
docker restart uvicorn worker_task && sleep 12
curl -s -X POST localhost:8011/cronjob -H 'Content-Type: application/json' \
  -d '{"cronjob_path":"src/cronjob/task_orchestrator.py","metadata":{"max_actions":1},"timeout":60}'
```

Ожидается: ответ со `"status": "success"` и JSON тика вида `{"queued": N, "reclaimed": N, "jobs": [...]}` — без трейсбека.

- [ ] **Step 12: Commit**

```bash
git add src/project/task/task_pipeline.py tests/test_task_role_bugfixer.py
git commit -m "Действие bugfix в конвейере: захват, прогон, done/failed"
```

---

### Task 9: Остановка снимает флажок «в багфикс»

**Files:**
- Modify: `src/project/task/task_stop.py:31-44` (импорты), `:138-146` (`_task_stop_patch`)
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: `TASK_BUGFIXER_ROLE` (Task 7), `TASK_METADATA_KEY_BUGFIX` (Task 3).
- Produces: остановка бага пишет `metadata.to_bugfix = false` вместе с `stopped = true`.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTaskStopBugfixFlag:

    def test_bug_task_stop_clears_bugfix_flag(self):
        from src.project.task.task_stop import _task_stop_patch
        patch = _task_stop_patch({'id': 1, 'parent_id': None}, 'bugfixer')
        assert patch['stopped'] is True
        # Флажок вкладки снимаем явным false: умолчание у него «включено», и
        # оставленный ключ увёл бы баг обратно в работу следующим же тиком.
        assert patch['to_bugfix'] is False

    def test_developer_task_stop_unchanged(self):
        from src.project.task.task_stop import _task_stop_patch
        patch = _task_stop_patch({'id': 1, 'parent_id': None}, 'developer')
        assert patch['to_testing'] is False
        assert 'to_bugfix' not in patch

    def test_manager_task_stop_unchanged(self):
        from src.project.task.task_stop import _task_stop_patch
        patch = _task_stop_patch({'id': 1, 'parent_id': None}, 'manager')
        assert patch['to_development'] is None
        assert 'to_bugfix' not in patch
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTaskStopBugfixFlag -v
```

Ожидается: FAIL — `KeyError: 'to_bugfix'` (роль `bugfixer` попадает в ветку `else` и получает `to_development`).

- [ ] **Step 3: Дописать импорты**

В `src/project/task/task_stop.py`:

```python
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_ROLE
from src.project.task.task_agent_developer import TASK_DEVELOPER_ROLE
from src.project.task.task_agent_qa import TASK_QA_ROLE
```

и в блок импорта `task_metadata` добавить `TASK_METADATA_KEY_BUGFIX,` первой строкой.

- [ ] **Step 4: Переписать `_task_stop_patch`**

```python
def _task_stop_patch(task: dict, role: str) -> dict:
    """
    Патч пометок для остановки: сам запрет плюс снятый флажок фазы.

    Флажок снимаем тот, который человек на своей вкладке и видит: «в багфикс» у бага,
    «в тестирование» у задачи разработчика, «в разработку» у задачи менеджера. Иначе
    снятая остановка сработала бы повторно — оставшийся флажок увёл бы задачу дальше
    сам, тем же тиком.

    Значения разные не для красоты: у `to_bugfix` и `to_testing` умолчание «включено»,
    и снять их можно только явным `false`; у `to_development` умолчание «выключено»,
    и снятие — это стирание ключа (`None` в JSON_MERGE_PATCH).
    """
    patch = {TASK_METADATA_KEY_STOP: True}
    if role == TASK_BUGFIXER_ROLE:
        patch[TASK_METADATA_KEY_BUGFIX] = False
    elif role == TASK_DEVELOPER_ROLE:
        if not task.get('parent_id'):
            patch[TASK_METADATA_KEY_TEST] = False
    else:
        patch[TASK_METADATA_KEY_DEV] = None
    return patch
```

- [ ] **Step 5: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 30 passed.

- [ ] **Step 6: Commit**

```bash
git add src/project/task/task_stop.py tests/test_task_role_bugfixer.py
git commit -m "Остановка бага снимает флажок «в багфикс»"
```

---

### Task 10: Карточка багфиксера на `/admin/team`

**Files:**
- Modify: `src/project/team/team_project.py:29-40`, `src/project/team/team_member.py:23-27`, `src/project/team/team_agent.py:14-24`
- Test: `tests/test_task_role_bugfixer.py` (дописать класс)

**Interfaces:**
- Consumes: `TASK_BUGFIXER_AGENT_NAME` (Task 7).
- Produces: четвёртая базовая роль в блоке проекта, заготовка карточки, ссылка карточки на агента.

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/test_task_role_bugfixer.py`:

```python
class TestTeamBugfixerCard:

    def test_role_is_base_for_every_project(self):
        from src.project.team.team_project import (
            TEAM_PROJECT_ROLE_BASE, TEAM_PROJECT_ROLE_ORDER, TEAM_PROJECT_ROLE_TITLE)
        assert 'bugfixer' in TEAM_PROJECT_ROLE_BASE
        assert TEAM_PROJECT_ROLE_TITLE['bugfixer'] == 'Багфиксер'
        # Порядок в ряду: менеджер, разработчик, багфиксер, QA — проверяющий последний.
        assert TEAM_PROJECT_ROLE_ORDER['bugfixer'] == 2
        assert TEAM_PROJECT_ROLE_ORDER['qa'] == 3

    def test_card_template_has_launch_command(self):
        from src.project.team.team_member import TEAM_MEMBER_ROLE_CARD
        name, command = TEAM_MEMBER_ROLE_CARD['bugfixer']
        assert name == 'Bugfixer'
        assert command == 'claude-shell --gx10 --bugfixer'

    def test_agent_bound_to_role(self):
        from src.project.team.team_agent import TEAM_AGENT_BY_ROLE
        assert TEAM_AGENT_BY_ROLE['bugfixer'] == 'task_bug_fixer'
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py::TestTeamBugfixerCard -v
```

Ожидается: FAIL — `'bugfixer' not in TEAM_PROJECT_ROLE_BASE`.

- [ ] **Step 3: Добавить роль в блок проекта**

В `src/project/team/team_project.py` заменить три константы:

```python
# Роли, которые в блоке проекта есть всегда: нет живой сессии — карточка серая.
TEAM_PROJECT_ROLE_BASE = ('manager', 'developer', 'bugfixer', 'qa')

# Карточки одной роли идут рядом, QA — последней. Роль вне списка попадает
# между developer и qa, чтобы QA осталась в конце ряда. Багфиксер занимает то же
# место осознанно: он правит код, как разработчик, и стоять ему рядом с ним.
TEAM_PROJECT_ROLE_ORDER = {'manager': 0, 'developer': 1, 'bugfixer': 2, 'qa': 3}
TEAM_PROJECT_ROLE_ORDER_OTHER = 2

TEAM_PROJECT_ROLE_TITLE = {
    'manager': 'Менеджер задач',
    'developer': 'Разработчик',
    'bugfixer': 'Багфиксер',
    'qa': 'Тестировщик',
}
```

- [ ] **Step 4: Добавить заготовку карточки**

В `src/project/team/team_member.py`:

```python
TEAM_MEMBER_ROLE_CARD = {
    'manager':   ('Manager',   'claude-shell --gx10 --manager'),
    'developer': ('Developer', 'claude-shell --gx10 --developer'),
    'bugfixer':  ('Bugfixer',  'claude-shell --gx10 --bugfixer'),
    'qa':        ('QA',        'claude-shell --gx10 --qa'),
}
```

- [ ] **Step 5: Связать роль с агентом**

В `src/project/team/team_agent.py`:

```python
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_AGENT_NAME
from src.project.task.task_agent_developer import TASK_DEVELOPER_AGENT_NAME
from src.project.task.task_agent_manager import TASK_MANAGER_AGENT_NAME
from src.project.task.task_agent_qa import TASK_QA_AGENT_NAME

# Роль карточки → имя агента, который делает её работу. Имя, а не id: id агента
# зависит от установки, имя — часть контракта (по нему агента ищет и сам конвейер).
TEAM_AGENT_BY_ROLE = {
    'manager':   TASK_MANAGER_AGENT_NAME,
    'developer': TASK_DEVELOPER_AGENT_NAME,
    'bugfixer':  TASK_BUGFIXER_AGENT_NAME,
    'qa':        TASK_QA_AGENT_NAME,
}
```

- [ ] **Step 6: Запустить тесты — должны пройти**

```bash
.venv/bin/python3 -m pytest tests/test_task_role_bugfixer.py -v
```

Ожидается: 33 passed.

- [ ] **Step 7: Завести карточки существующим проектам и посмотреть страницу**

```bash
docker restart uvicorn && sleep 12
docker exec uvicorn python3 -c "
import asyncio
from src.mysql_.repository.project.project_repository import PlanningProjectRepository
from src.project.team.team_member import team_member_cards_ensure

async def main():
    for project in await PlanningProjectRepository().find_by({}):
        added = await team_member_cards_ensure(project['id'])
        print(project['id'], project.get('title') or project.get('name'), '->', added)

asyncio.run(main())
"
```

Ожидается: у каждого проекта добавлена как минимум одна карточка (`-> 1`), а повторный запуск даёт `-> 0`.

- [ ] **Step 8: Commit**

```bash
git add src/project/team/team_project.py src/project/team/team_member.py \
        src/project/team/team_agent.py tests/test_task_role_bugfixer.py
git commit -m "Карточка багфиксера в блоке проекта на /admin/team"
```

---

### Task 11: Workflow `task_bug_fixer` в базе и seed

Агент и workflow — данные, а не схема: заводим их в локальной БД скриптом и переносим seed-файлом.

**Files:**
- Create: временный скрипт в `/tmp/claude-1000/-home-vasyl-PycharmProjects-RhapsodyAi/4968a6f3-8a5f-4172-ab18-3293fe57acec/scratchpad/bugfixer_workflow.py` (в репозиторий не идёт)
- Create: `data/seeds/seed_<дата>.sql` (результат генерации, идёт в репозиторий)

**Interfaces:**
- Consumes: `TASK_BUGFIXER_AGENT_NAME = 'task_bug_fixer'` (Task 7).
- Produces: строка `agent_workflow` с `name='task_bug_fixer'`, её шаги в `agent_workflow_step`, строка `agent` с `name='task_bug_fixer'` и `workflow_id` на этот workflow.

- [ ] **Step 1: Посмотреть id типов шагов и ноду соседних агентов**

```bash
docker exec rhapsodyai-mysql-1 mysql -udeveloper -ppassword project --default-character-set=utf8mb4 -e "
SELECT id, name FROM agent_workflow_step_type WHERE name IN ('variable_conversion','tool_invoke','return_response_text');
SELECT id, name, node_id, workflow_id FROM agent WHERE name = 'task_qa_tester';
SELECT id, name, node_id FROM agent_workflow WHERE name = 'task_qa_tester';"
```

Ожидается: `variable_conversion = 5`, `tool_invoke = 3`, `return_response_text = 4`; агент `task_qa_tester` с `node_id = 6`.

- [ ] **Step 2: Написать скрипт создания workflow**

Создать `/tmp/claude-1000/-home-vasyl-PycharmProjects-RhapsodyAi/4968a6f3-8a5f-4172-ab18-3293fe57acec/scratchpad/bugfixer_workflow.py`:

```python
"""
Завести workflow `task_bug_fixer` и его агента. Одноразовый скрипт: результат
переносится seed-файлом, сам скрипт в репозиторий не идёт.

Идемпотентен: повторный запуск чистит свои же шаги и переписывает их заново, поэтому
править промпты можно прямо здесь и запускать сколько угодно раз.

Переходы (`transitions_after`) ссылаются на шаги по id, а id известны только после
вставки. Поэтому проход два: сперва шаги без переходов, потом — переходы по карте
«позиция → id».
"""
import asyncio
import json

from mysql_.mysql_ import mysql_get_db_async

WORKFLOW_NAME = 'task_bug_fixer'
AGENT_NAME = 'task_bug_fixer'
NODE_ID = 6
TYPE_VAR, TYPE_TOOL, TYPE_RETURN = 5, 3, 4

# Позиция шага «оболочка недоступна» и «среда не готова» — на них уводят переходы.
POS_SHELL_DEAD = 11
POS_ENV_BAD = 98

PROMPT_RECON = """Ты чинишь баг в этом проекте. Сейчас только разбор: код НЕ меняй,
файлы не правь, коммитов не делай.
%if task_work_dir%
Работай в каталоге %task_work_dir% — это отдельная выкладка репозитория, ветка бага
в ней уже выкачена. Начни с перехода в этот каталог.
%endif%

=== БАГ ===
#%task_id% %task_title%

%task_description%

%if task_trace_meta%=== СЛЕД ИЗ ЖУРНАЛА ВЫПОЛНЕНИЯ ===
%task_trace_meta%

%endif%%if task_goals%=== ЦЕЛИ ===
%task_goals%

%endif%Что сделать:
1. Пойми, о чём баг: какой код за него отвечает, конкретные пути к файлам и функции.
2. Попробуй воспроизвести. Скажи прямо, воспроизвёлся он или нет и чем ты проверял.
3. Если воспроизвёлся — назови причину: строку, условие, состояние данных.
4. Прочитай правила проекта, которые тут действуют: CLAUDE.md и нужные файлы
   .claude/docs/ и .claude/docs-common/.
5. Наметь минимальную правку: какие файлы меняешь и чем проверишь результат.

Отвечай обычным текстом, не длиннее 15 строк, строка на мысль. Без заголовков и
таблиц — этот ответ целиком уходит в следующий промпт. JSON сейчас не нужен."""

PROMPT_FIX = """Теперь почини баг по своему же разбору.

%if task_work_dir%Работай в каталоге %task_work_dir%, ветка %task_branch% уже выкачена —
переключать её не нужно.
%endif%
Правила:
- правка минимальная: чинишь причину, а не переписываешь модуль;
- ничего постороннего в тех же файлах не трогаешь;
- следуешь правилам проекта из CLAUDE.md и .claude/docs/;
- изменения коммитишь в свою ветку.

Если по ходу выяснилось, что починить нельзя — не выдумывай правку. Скажи прямо, что
именно мешает: не воспроизводится, причина вне проекта, нужен доступ, которого нет.

Отвечай обычным текстом: что изменил, в каких файлах, каким коммитом. Не длиннее
15 строк."""

PROMPT_CHECK = """Проверь свой фикс.

%if task_server_url%Сервер этого проекта: %task_server_url% — проверяй на нём.
%endif%%if task_work_dir%Каталог: %task_work_dir%.
%endif%
Что сделать:
1. Прогони существующие тесты проекта, которые задевает правка.
2. Воспроизведи исходный сценарий бага заново и убедись, что он больше не повторяется.
3. Проверь, что рядом ничего не сломалось.

Новых тестов ради галочки не пиши. Если проверить нечем — скажи об этом прямо, а не
выдавай непроверенное за проверенное.

Отвечай обычным текстом: что прогнал и с каким результатом. Не длиннее 10 строк."""

PROMPT_JSON = """Верни тот же самый ответ в машинном виде. Ничего заново не придумывай
и не переделывай — это ровно то, что ты только что сделал.

Ответь ОДНИМ JSON-объектом, без markdown, без ограды из обратных кавычек и без текста
вокруг:
{"bug_report_json": {"ok": true, "summary": "что сделано", "cause": "причина бага", "files": ["путь/к/файлу"], "branch": "%task_branch%", "checks": "чем проверял и с каким результатом", "error": "почему не починено, если ok=false"}}

- bug_report_json — ВСЕГДА объект, поля ровно те, что перечислены.
- files — массив строк, ok — true или false.
- ok=false ставь, если баг починить не удалось: не воспроизвёлся, причина вне проекта,
  не хватило доступа. Тогда в error — причина одной фразой.
- summary, cause, checks и error — обычный текст, без двойных кавычек и фрагментов JSON."""


def _shell_step(out_variable: str) -> dict:
    """
    Шаг обращения к оболочке: вызов один и тот же, разнится только переменная ответа.

    Определён выше `STEPS` намеренно: `STEPS` — модульная константа, и вызов на этапе
    её построения обязан видеть функцию уже определённой. Правило «приватные внизу» на
    одноразовый скрипт в scratchpad не распространяется.
    """
    return {
        'tool_invoke': {'tool_name': 'claude_shell_call',
                        'inputs_map': {'role': 'task_shell_role', 'prompt': 'bugfixer_prompt',
                                       'work_dir': 'task_shell_work_dir', 'timeout': '_const_1200'},
                        'outputs_map': {'error': 'bug_error', 'status': 'bug_status',
                                        'response': out_variable}},
        'transitions_after': [
            {'variable': 'bug_status', 'operator': '!=', 'value': 'answered',
             'step_pos': POS_SHELL_DEAD},
            {'variable': out_variable, 'operator': 'empty', 'value': '',
             'step_pos': POS_SHELL_DEAD}],
    }


STEPS = [
    (0, TYPE_VAR, 'Инициализация', {
        'variable_conversion': [
            {'variable': 'env_ok', 'text': 'yes'},
            {'variable': 'env_error', 'text': ''},
            {'variable': 'bug_recon', 'text': ''},
            {'variable': 'bug_fix', 'text': ''},
            {'variable': 'bug_check', 'text': ''},
            {'variable': 'bug_report_json', 'text': ''},
            {'variable': 'bug_status', 'text': ''},
            {'variable': 'bug_error', 'text': ''},
        ]}),
    (1, TYPE_TOOL, 'Проверка среды', {
        'tool_invoke': {'tool_name': 'task_server_check',
                        'inputs_map': {'subtask_id': 'task_id'},
                        'outputs_map': {'env_ok': 'env_ok', 'env_error': 'env_error'}},
        'transitions_after': [{'variable': 'env_ok', 'operator': '==', 'value': 'no',
                               'step_pos': POS_ENV_BAD}]}),
    (2, TYPE_VAR, 'Промпт: разбор бага', {
        'variable_conversion': [{'variable': 'bugfixer_prompt', 'text': PROMPT_RECON}]}),
    (3, TYPE_TOOL, 'Багфиксер: разбор', _shell_step('bug_recon')),
    (4, TYPE_VAR, 'Промпт: починка', {
        'variable_conversion': [{'variable': 'bugfixer_prompt', 'text': PROMPT_FIX}]}),
    (5, TYPE_TOOL, 'Багфиксер: починка', _shell_step('bug_fix')),
    (6, TYPE_VAR, 'Промпт: самопроверка', {
        'variable_conversion': [{'variable': 'bugfixer_prompt', 'text': PROMPT_CHECK}]}),
    (7, TYPE_TOOL, 'Багфиксер: самопроверка', _shell_step('bug_check')),
    (8, TYPE_VAR, 'Промпт JSON: вердикт', {
        'variable_conversion': [{'variable': 'bug_report_json', 'text': ''},
                                {'variable': 'bugfixer_prompt', 'text': PROMPT_JSON}]}),
    (9, TYPE_TOOL, 'Ответ JSON: вердикт', {
        'tool_invoke': {'tool_name': 'claude_shell_call',
                        'inputs_map': {'role': 'task_shell_role', 'prompt': 'bugfixer_prompt',
                                       'work_dir': 'task_shell_work_dir', 'timeout': '_const_1200'},
                        'outputs_map': {'error': 'bug_error', 'status': 'bug_status',
                                        'payload_json': 'bug_report_json'}},
        'transitions_after': [
            {'variable': 'bug_status', 'operator': '!=', 'value': 'answered',
             'step_pos': POS_SHELL_DEAD},
            {'variable': 'bug_report_json', 'operator': 'empty', 'value': '',
             'step_pos': POS_SHELL_DEAD}]}),
    (10, TYPE_RETURN, 'Вернуть результат', {
        'prompt_user': 'json:{"ok": true, "report": %bug_report_json%, "error": ""}',
        'continue_workflow': False}),
    (POS_SHELL_DEAD, TYPE_RETURN, 'Оболочка недоступна', {
        'prompt_user': 'json:{"ok": false, "report": {}, '
                       '"error": "Багфиксер не ответил: %bug_error%"}',
        'continue_workflow': False}),
    (POS_ENV_BAD, TYPE_RETURN, 'Среда не готова', {
        'prompt_user': 'json:{"ok": false, "env_ok": false, "report": {}, '
                       '"error": "Среда не готова: %env_error%"}',
        'continue_workflow': False}),
]


async def main() -> None:
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM agent_workflow WHERE name = %s', (WORKFLOW_NAME,))
        row = await db.fetchone()
        if row:
            workflow_id = row['id']
            await db.execute('DELETE FROM agent_workflow_step WHERE workflow_id = %s', (workflow_id,))
        else:
            await db.execute(
                'INSERT INTO agent_workflow (node_id, name, title, description, position, '
                'group_name, subflow) VALUES (%s, %s, %s, %s, %s, %s, 0)',
                (NODE_ID, WORKFLOW_NAME, 'Task: Фикс бага',
                 'Багфиксер: разбор, воспроизведение, починка, самопроверка, вердикт',
                 0, 'task'))
            workflow_id = db.lastrowid

        pos_to_id = {}
        for position, type_id, title, metadata in STEPS:
            payload = {k: v for k, v in metadata.items() if k != 'transitions_after'}
            payload.setdefault('transitions_before', [])
            payload.setdefault('transitions_after', [])
            await db.execute(
                'INSERT INTO agent_workflow_step (workflow_id, type_id, title, position, metadata) '
                'VALUES (%s, %s, %s, %s, %s)',
                (workflow_id, type_id, title, position,
                 json.dumps(payload, ensure_ascii=False)))
            pos_to_id[position] = db.lastrowid

        # Второй проход: переходы знают позиции, а в metadata обязаны лежать id.
        for position, _type_id, _title, metadata in STEPS:
            transitions = metadata.get('transitions_after')
            if not transitions:
                continue
            await db.execute('SELECT metadata FROM agent_workflow_step WHERE id = %s',
                             (pos_to_id[position],))
            payload = json.loads((await db.fetchone())['metadata'])
            payload['transitions_after'] = [
                {'variable': t['variable'], 'operator': t['operator'], 'value': t['value'],
                 'step_id': str(pos_to_id[t['step_pos']])}
                for t in transitions]
            await db.execute('UPDATE agent_workflow_step SET metadata = %s WHERE id = %s',
                             (json.dumps(payload, ensure_ascii=False), pos_to_id[position]))

        await db.execute('SELECT id FROM agent WHERE name = %s', (AGENT_NAME,))
        agent = await db.fetchone()
        if agent:
            await db.execute('UPDATE agent SET workflow_id = %s, node_id = %s WHERE id = %s',
                             (workflow_id, NODE_ID, agent['id']))
            agent_id = agent['id']
        else:
            await db.execute(
                'INSERT INTO agent (node_id, name, title, description, workflow_id, '
                'prompt_system, greeting, position, group_name, dynamic) '
                "VALUES (%s, %s, %s, %s, %s, '', '', 0, %s, 0)",
                (NODE_ID, AGENT_NAME, 'Task Bugfixer',
                 'Чинит баг целиком: разбор, воспроизведение, фикс, самопроверка',
                 workflow_id, 'task'))
            agent_id = db.lastrowid

        await db.connection.commit()

    print(f'workflow #{workflow_id}, агент #{agent_id}, шагов: {len(STEPS)}')


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 3: Прогнать скрипт**

```bash
docker cp /tmp/claude-1000/-home-vasyl-PycharmProjects-RhapsodyAi/4968a6f3-8a5f-4172-ab18-3293fe57acec/scratchpad/bugfixer_workflow.py uvicorn:/app/bugfixer_workflow.py
docker exec uvicorn python3 /app/bugfixer_workflow.py
```

Ожидается: `workflow #NN, агент #NN, шагов: 13`.

- [ ] **Step 4: Проверить, что записалось**

```bash
docker exec rhapsodyai-mysql-1 mysql -udeveloper -ppassword project --default-character-set=utf8mb4 -e "
SELECT w.id, w.name, w.title, COUNT(s.id) AS steps
  FROM agent_workflow w LEFT JOIN agent_workflow_step s ON s.workflow_id = w.id
 WHERE w.name = 'task_bug_fixer' GROUP BY w.id;
SELECT id, name, title, workflow_id, node_id FROM agent WHERE name = 'task_bug_fixer';
SELECT position, title FROM agent_workflow_step
 WHERE workflow_id = (SELECT id FROM agent_workflow WHERE name = 'task_bug_fixer')
 ORDER BY position;"
```

Ожидается: 13 шагов, агент с непустым `workflow_id`, ноль шагов с `step_id` из чужого workflow.

- [ ] **Step 5: Проверить, что переходы указывают на существующие шаги**

```bash
docker exec rhapsodyai-mysql-1 mysql -udeveloper -ppassword project --default-character-set=utf8mb4 -e "
SELECT s.position, s.title, JSON_EXTRACT(s.metadata, '\$.transitions_after[*].step_id') AS targets
  FROM agent_workflow_step s
 WHERE s.workflow_id = (SELECT id FROM agent_workflow WHERE name = 'task_bug_fixer')
   AND JSON_LENGTH(JSON_EXTRACT(s.metadata, '\$.transitions_after')) > 0
 ORDER BY s.position;"
```

Ожидается: у шагов 1, 3, 5, 7, 9 непустые `targets`, и каждый id есть в списке шагов из предыдущей проверки.

- [ ] **Step 6: Проверить, что карточка команды нашла агента**

```bash
docker exec uvicorn python3 -c "
import asyncio
from src.project.team.team_agent import team_agent_by_role
print(asyncio.run(team_agent_by_role()).get('bugfixer'))
"
```

Ожидается: словарь с непустыми `agent_id` и `workflow_id`.

- [ ] **Step 7: Сгенерировать seed**

Открыть `/admin/seed`, убедиться, что в списке таблиц отмечены `agent`, `agent_workflow`, `agent_workflow_step`, `agent_workflow_variable`, `agent_workflow_variable_workflow`, нажать «Сгенерировать». Либо тем же через API:

```bash
curl -s -X POST localhost:8011/seed/generate -H 'Content-Type: application/json' \
  -b /tmp/claude-1000/-home-vasyl-PycharmProjects-RhapsodyAi/4968a6f3-8a5f-4172-ab18-3293fe57acec/scratchpad/cookie.txt \
  -d '{"tables":["agent","agent_workflow","agent_workflow_step","agent_workflow_variable","agent_workflow_variable_workflow"]}'
ls -la data/seeds/ | tail -3
```

Ожидается: новый файл `data/seeds/seed_<дата>.sql`, внутри которого есть `task_bug_fixer`:

```bash
grep -c "task_bug_fixer" data/seeds/seed_*.sql | tail -1
```

- [ ] **Step 8: Commit**

```bash
git add data/seeds/
git commit -m "Seed: агент и workflow task_bug_fixer"
```

---

### Task 12: Вкладка «Баги» на странице задач

**Files:**
- Modify: `data/uvicorn/template/admin/project/task.html` — строки 1253-1257 (кнопки вкладок), 1323-1337 (карты фаз), ~1574-1593 (`taskIsDone`/`taskMatchesPhase`), ~1813-1830 (`phaseTabsCount`), ~2919 (флажки), ~3016-3060 (комментарии кнопок diff/merge), ~3549 и ~3649 (справка)
- Test: `tests/test_team_task_pages.py` (дописать проверку)

**Interfaces:**
- Consumes: ключ `to_bugfix` (Task 3), тип задачи `bug`.
- Produces: четвёртая вкладка `bugs` со счётчиком `tabCount-bugs`, флажок «в багфикс».

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_team_task_pages.py` новый тест в существующий класс страницы задач (рядом с проверками разметки):

```python
    async def test_task_page_has_bugs_tab(self, client: httpx.AsyncClient):
        """Четыре вкладки, и «Тестирование» больше не тянет за собой баги."""
        resp = await client.get('/admin/task')
        assert resp.status_code == 200, resp.text
        html = resp.text

        assert 'data-tab="bugs"' in html
        assert 'tabCount-bugs' in html
        assert '>Баги ' in html
        # Старое имя вкладки ушло вместе с типом `bug` из неё.
        assert 'Тестирование/Баги' not in html
        # Карта фаз развела типы по разным вкладкам.
        assert "testing:     ['test']" in html or "testing: ['test']" in html
        assert "bugs:        ['bug']" in html or "bugs: ['bug']" in html
```

- [ ] **Step 2: Запустить тест и убедиться, что падает**

```bash
.venv/bin/python3 -m pytest tests/test_team_task_pages.py -k bugs_tab -v
```

Ожидается: FAIL — `assert 'data-tab="bugs"' in html`.

- [ ] **Step 3: Добавить кнопку вкладки**

В `data/uvicorn/template/admin/project/task.html` заменить блок `#phaseTabs`:

```html
    <div class="page-tabs" id="phaseTabs">
        <button class="page-tab active" data-tab="planning">Планирование <span class="page-tab-n" id="tabCount-planning"></span></button>
        <button class="page-tab" data-tab="development">Разработка <span class="page-tab-n" id="tabCount-development"></span></button>
        <button class="page-tab" data-tab="testing">Тестирование <span class="page-tab-n" id="tabCount-testing"></span></button>
        <button class="page-tab" data-tab="bugs">Баги <span class="page-tab-n" id="tabCount-bugs"></span></button>
    </div>
```

- [ ] **Step 4: Развести типы по вкладкам**

Заменить `PHASE_TYPE_NAMES` и `PHASE_NEW_TYPE_NAME`:

```js
// Mapping фазы к именам типов задач (из project_task_type.name)
// Реальные данные: dev=1, bug=2, test=3, research=4, plan=5
//
// `bug` уехал с «Тестирования» на свою вкладку вместе с владельцем: тип принадлежит
// роли `bugfixer` (см. src/project/task/task_role.py), а тестирование осталось за QA.
const PHASE_TYPE_NAMES = {
    planning:    ['research', 'plan'],   // 4, 5
    development: ['dev'],                // 1
    testing:     ['test'],               // 3
    bugs:        ['bug'],                // 2
};

// Тип новой задачи — по вкладке, на которой её заводят: полей «Статус» и «Тип» в форме
// больше нет, а тип решает, чья карточка возьмёт задачу в работу (см. `task_role.py`).
// Вкладка перечисляет несколько типов, для новой задачи нужен один — основной для фазы:
// «Планирование» → plan (не research).
const PHASE_NEW_TYPE_NAME = {
    planning:    'plan',
    development: 'dev',
    testing:     'test',
    bugs:        'bug',
};
```

- [ ] **Step 5: Оставить готовые баги на своей вкладке**

Заменить `taskMatchesPhase` (функция рядом со строкой 1583):

Заменить в `taskMatchesPhase` только строку с `taskIsDone` (остальное тело — как есть, включая `getTaskTypeNameById` и ранний выход при пустом `_phaseFilter`):

```js
    if (taskIsDone(t)) return typeName === 'bug' ? _phaseFilter === 'bugs'
                                                 : _phaseFilter === 'testing';
```

Готовое тело функции целиком:

```js
function taskMatchesPhase(t) {
    // Задачи без task_type_id считаются типом "dev" (development)
    const typeName = getTaskTypeNameById(t.task_type_id) || 'dev'; // NULL → dev по умолчанию
    if (!_phaseFilter) return true;
    if (taskIsDone(t)) return typeName === 'bug' ? _phaseFilter === 'bugs'
                                                 : _phaseFilter === 'testing';
    return (PHASE_TYPE_NAMES[_phaseFilter] || []).includes(typeName);
}
```

И в комментарии над функцией дописать абзац после того, что про «Тестирование»:

```js
// У багов инстанция своя. Вкладка «Баги» — полный жизненный цикл бага, от заведения до
// принятой ветки, и уводить закрытый баг на чужую вкладку значило бы прятать его от
// того, кто его завёл. Кнопки приёмки от вкладки не зависят (см. renderPipeDiff).
```

- [ ] **Step 6: Починить счётчик вкладок**

В `phaseTabsCount` заменить строку выбора вкладки на то же правило, что в `taskMatchesPhase`:

```js
            const ok = taskIsDone(t)
                ? (typeName === 'bug' ? phase === 'bugs' : phase === 'testing')
                : PHASE_TYPE_NAMES[phase].includes(typeName);
```

- [ ] **Step 7: Добавить флажок «в багфикс»**

Рядом с `renderQaFlag` (после неё) добавить:

```js
// Ключ пометки «в багфикс» — тот же, что читает захват бага
// (src/project/task/task_metadata.py, TASK_METADATA_KEY_BUGFIX).
const TASK_META_KEY_BUGFIX = 'to_bugfix';

// Флажок «в багфикс» на вкладке «Баги» — выключатель фазы, как «в тестирование» на
// «Тестировании». Стоит галка — багфиксер берёт баг в работу, снята — не берёт, а
// идущий прогон гасится.
//
// Умолчание «включено»: заведённый баг обязан попадать в работу сам, решением человека
// является отказ. Поэтому хранится отклонение от умолчания — ключа нет = флажок стоит,
// снятый пишется явным `false`. Отсюда `!== false`, а не `!!`.
//
// Второго флажка у вкладки нет: после починки баг идёт к человеку, а не следующему
// агенту, и разрешать заранее нечего.
function renderBugFlag(t, status) {
    if (t.parent_id) return '';
    if (_phaseFilter !== 'bugs' || !TASK_RUN_FLAG_STATUS.includes(status)) return '';
    const on = (t.metadata || {})[TASK_META_KEY_BUGFIX] !== false;
    const title = on
        ? 'Баг у багфиксера. Снять — работа прекратится: агента погасим, баг вернём'
          + ' в «Ожидает». Сделанное в ветке не пропадёт'
        : 'Отдать баг багфиксеру — работу отдаст ближайший тик оркестратора';
    return _taskFlagHtml(t.id, 'в багфикс', on, 'toggleBugFlag', title);
}

async function toggleBugFlag(taskId, checked, el) {
    // Выключатель фазы: сперва снимаем разрешение, потом гасим прогон. В обратном
    // порядке тик успел бы подобрать баг в тот же миг, когда его остановили.
    await _taskPhaseSwitch(taskId, TASK_META_KEY_BUGFIX, checked, el);
}
```

- [ ] **Step 8: Вызвать новый флажок там же, где остальные**

Флажки собираются в одну строку около строки 2015 `data/uvicorn/template/admin/project/task.html`. Заменить её:

```js
    return badge + renderRunFlag(t, status) + renderQaFlag(t, status) + renderBugFlag(t, status)
        + renderPlanFlag(t) + renderDevFlag(t) + renderTestFlag(t)
```

Порядок в строке значения не имеет: на каждой вкладке рисуется ровно один из них, остальные возвращают пустую строку.

- [ ] **Step 9: Поправить комментарии кнопок приёмки**

В комментарии над `renderPipeMerge` заменить абзац про вкладку:

```js
// Готовая задача видна на «Тестировании», а готовый баг — на «Багах» (см.
// `taskMatchesPhase`), поэтому обе кнопки живут на той вкладке, где работу и
// принимают. Сама разметка кнопок от вкладки не зависит — только от того, что строка
// корневая и `pipeline_state === 'done'`.
```

- [ ] **Step 10: Дописать справку**

В модальном окне справки (`showHelpModal`, блок со списком состояний конвейера — рядом со строкой с `<code>testing</code>`) добавить:

```html
                                    <span><code>bugfixing</code> <span class="help-branch help-branch-parent">[баг]</span> — баг у багфиксера: он воспроизводит, чинит и проверяет за один прогон. Успех — <code>done</code>, отрицательный вердикт — <code>failed</code>, то есть «Заблокировано».</span>
```

и в компактном списке состояний (рядом со строкой `<span class="pn pn-teal">testing</span>`):

```html
                                <div class="vrow"><span class="pn pn-teal">bugfixing</span><span class="note">баг чинит багфиксер, один прогон: done либо failed</span></div>
```

- [ ] **Step 11: Запустить тест — должен пройти**

```bash
docker restart uvicorn && sleep 12
.venv/bin/python3 -m pytest tests/test_team_task_pages.py -k bugs_tab -v
```

Ожидается: PASS.

- [ ] **Step 12: Проверить страницу глазами**

Открыть `/admin/task`, убедиться:
- четыре вкладки, третья называется «Тестирование», четвёртая «Баги»;
- на «Багах» видны задачи типа `bug`, на «Тестировании» их больше нет;
- «+ Добавить» на «Багах» создаёт задачу, которая остаётся на этой же вкладке;
- у строки бага в статусе «Ожидает» есть флажок «в багфикс», включённый;
- счётчики во вкладках совпадают с числом строк в таблице.

- [ ] **Step 13: Commit**

```bash
git add data/uvicorn/template/admin/project/task.html tests/test_team_task_pages.py
git commit -m "Вкладка «Баги» на странице задач и флажок «в багфикс»"
```

---

### Task 13: Сквозной тест конвейера

**Files:**
- Modify: `tests/test_task_pipeline.py` (новый класс в конец файла)

**Interfaces:**
- Consumes: всё предыдущее.
- Produces: проверка, что баг захватывается, а менеджер его не трогает.

- [ ] **Step 1: Написать тест**

Дописать в конец `tests/test_task_pipeline.py`:

```python
class TestTaskPipelineBug:
    """
    Баг идёт своим путём: его берёт багфиксер, а менеджерский шаг обходит стороной.

    Живой оболочки багфиксера в тестовой среде может не быть, и это не делает тест
    бесполезным: отсутствие захвата менеджером проверяется независимо от неё, а сам
    захват — только когда карточка жива (иначе `task_role_shell_live_by_project` роли
    не увидит, и это законное поведение, а не сбой).
    """

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=CLIENT_TIMEOUT) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    @pytest.fixture(autouse=True)
    async def db_pool_release(self) -> AsyncGenerator[None, None]:
        yield
        from mysql_.mysql_ import mysql_pool_close
        await mysql_pool_close()

    @pytest.fixture
    async def bug_task(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        """
        Баг без проекта — его берёт только оболочка вне проектов, чужие не тронут.

        Типы задач отдаёт карточка команды (`GET /api/team/types`) плоским списком, без
        обёртки `result`; создание задачи возвращает `{'task': {...}}`.
        """
        resp = await client.get("/api/team/types")
        assert resp.status_code == 200, resp.text
        bug_type = next(t for t in resp.json() if t["name"] == "bug")

        resp = await client.post("/tasks/0", json={
            "title": f"{TEST_TASK_TITLE}_bug",
            "description": "Тестовый баг: воспроизведение падает на пустом входе",
            "task_type_id": bug_type["id"],
        })
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["task"]["id"]
        yield task_id
        await client.delete(f"/task/{task_id}")

    async def test_bug_is_not_taken_by_manager(self, client: httpx.AsyncClient, bug_task: int):
        """
        Менеджерский шаг баг не забирает: план у бага не пишут.

        Проверяем состоянием, а не списком jobs: тик мог поставить в очередь чужую
        работу, и её присутствие ничего про наш баг не говорит. `bugfixing` в списке
        допустимых — законный исход, если карточка багфиксера в этой среде жива.
        """
        await _tick(client, max_actions=3)
        state = (await _pipeline(client, bug_task))["pipeline_state"]
        assert state in (None, "", "new", "bugfixing", "done", "failed"), \
            f"баг ушёл в чужое состояние: {state}"

    async def test_bug_flag_off_keeps_it_out_of_work(self, client: httpx.AsyncClient, bug_task: int):
        """Снятый флажок «в багфикс» убирает баг из отбора."""
        resp = await client.post(f"/task/{bug_task}/metadata",
                                 json={"patch": {"to_bugfix": False}})
        assert resp.status_code == 200, resp.text

        await _tick(client, max_actions=3)
        state = (await _pipeline(client, bug_task))["pipeline_state"]
        assert state in (None, "", "new"), f"баг взяли в работу вопреки снятому флажку: {state}"

    async def test_cancelled_bug_is_not_taken(self, client: httpx.AsyncClient, bug_task: int):
        """Отменённый баг в работу не уходит — у него нет ни одного шага с человеком."""
        resp = await client.put(f"/task/{bug_task}", json={"status": "cancelled"})
        assert resp.status_code == 200, resp.text

        await _tick(client, max_actions=3)
        state = (await _pipeline(client, bug_task))["pipeline_state"]
        assert state in (None, "", "new"), f"отменённый баг взяли в работу: {state}"
```

- [ ] **Step 2: Свериться с контрактом API, если тест не завёлся**

Маршруты и формы ответов, на которые тест опирается:

| Вызов | Роутер | Ответ |
|---|---|---|
| `GET /api/team/types` | `project_team.py:137` | плоский список типов |
| `POST /tasks/{project_id}` | `project_task.py:62` | `{'task': {...}}` |
| `PUT /task/{task_id}` | `project_task.py:102` | принимает `status` |
| `GET /task/{task_id}/pipeline` | `project_task_pipeline.py:56` | `{'pipeline_state', 'plan_text', ...}` без обёртки |
| `DELETE /task/{task_id}` | `project_task.py:232` | — |

Разойдись что-то — править **тест** под роутер, а не наоборот: контракт API описан в `.claude/docs/project_task.md` §6.

- [ ] **Step 3: Прогнать тест**

```bash
.venv/bin/python3 -m pytest tests/test_task_pipeline.py::TestTaskPipelineBug -v
```

Ожидается: 3 passed.

- [ ] **Step 4: Прогнать все задачи целиком — ничего не сломалось**

```bash
.venv/bin/python3 -m pytest tests/test_task_pipeline.py tests/test_task_tree.py \
    tests/test_task_metadata.py tests/test_task_role_bugfixer.py \
    tests/test_team_task_pages.py tests/test_team_ping.py -v
```

Ожидается: все passed. Упавшее чинить до перехода дальше — особенно тесты, задевающие роль `qa`: у неё изменился набор типов.

- [ ] **Step 5: Commit**

```bash
git add tests/test_task_pipeline.py
git commit -m "Тесты конвейера: баг идёт мимо менеджера, флажок и отмена его тормозят"
```

---

### Task 14: Документация

**Files:**
- Modify: `.claude/docs/project_task.md` (§2 вкладки, §3 машина состояний, §4 карта ролей и порядок захвата, §5 ключи `metadata`, §7 роли)
- Modify: `.claude/docs/project_team.md` (роли и карточки)

**Interfaces:**
- Consumes: всё реализованное.
- Produces: документация, совпадающая с кодом.

- [ ] **Step 1: Вкладки — §2 `project_task.md`**

В разделе «Готовая работа живёт только на «Тестировании»» дописать абзац:

```markdown
**У багов инстанция своя.** Тип `bug` живёт на вкладке «Баги» и остаётся на ней после
закрытия: эта вкладка — полный жизненный цикл бага, от заведения до принятой ветки.
Кнопки «diff» и «mr2master&rm_worktree» от вкладки не зависят — они смотрят только на
`parent_id` и `pipeline_state = done`, — поэтому принимают работу там же. Правило
`taskIsDone` раздваивается ровно на этом типе, и `phaseTabsCount` обязан повторять
разбор один в один: разойдись он — вкладка звала бы на пустое место.
```

- [ ] **Step 2: Машина состояний — §3**

После блока с подзадачей дописать:

```markdown
```
баг (project_task, тип `bug`, parent_id = NULL) — pipeline_state:

  NULL | new  --(захват)-->  bugfixing  --+--> done    (status = done)
                                          |
                                          +--> failed  (status = blocked)

  failed  --(«Перезапустить»)-->  new
```

Ни плана, ни утверждения, ни подзадач: вся работа идёт в самой строке за один прогон.
Кругов «не сошлось» тоже нет — `ok: false` от багфиксера это состоявшаяся работа с
отрицательным вердиктом («не воспроизводится», «причина вне проекта»), и второй заход по
той же фактуре дал бы тот же ответ. Технический срыв (оболочка не ответила, не-JSON) —
другое дело: он идёт обычным `task_retry` с возвратом в `new`.

Флажок «в багфикс» (`metadata.to_bugfix`) — выключатель фазы на вкладке «Баги», с тем же
обратным умолчанием, что и «в тестирование»: ключа нет = баг чинится, снятый флажок
пишется явным `false`. Второго флажка у вкладки нет: после починки баг идёт к человеку.
```

- [ ] **Step 3: Карта ролей — §4**

Заменить таблицу «Кто планирует: тип задачи → роль карточки»:

```markdown
| Тип задачи (`project_task_type.name`) | Ведёт | Оболочка `claude_shell_call` |
|---|---|---|
| `plan`, `research`, тип не задан, неизвестный тип | Менеджер | `manager` |
| `dev` | Разработчик | `developer` |
| `test` | QA | `qa` |
| `bug` | Багфиксер | `bugfixer` |

Багфиксер в этой таблице стоит особняком: остальные роли по своему типу **пишут план**,
а он по своему — сразу делает работу. Поэтому менеджерские захваты
(`task_claim_task_unplanned`, `task_claim_task_review`) получают словарь живых ролей
через `task_role_planners_only()` — без него они увидели бы живую карточку багфиксера,
её тип `bug` и отправили бы баг писать план.
```

И в порядке захвата заменить строку:

```markdown
`_claim_qa` → `_claim_developer` → `_claim_bugfix` → `_claim_plan_split` →
`_claim_manager_review` → `_claim_manager_plan`

`_claim_bugfix` стоит после разработки, но до планирования: починка бага — такая же
работа роли, как разработка, а подзадача идущего плана всё же ближе к финишу, чем баг,
которым ещё не занимались.
```

- [ ] **Step 4: Ключи `metadata` — §5**

В список ключей дописать строку:

```markdown
| `to_bugfix` | флажок «в багфикс» на вкладке «Баги»; умолчание «включено», снятый пишется явным `false` |
```

- [ ] **Step 5: Роль багфиксера — §7**

Добавить раздел после «QA»:

```markdown
### Багфиксер — живой Claude Code в своей оболочке

Роль `bugfixer`, агент `task_bug_fixer`, модуль `src/project/task/task_agent_bugfixer.py`.
Устроен как QA — агентный движок, свой workflow, своя shell-оболочка, — но объём работы
другой: за один прогон он воспроизводит баг, находит причину, правит код и проверяет
результат. Плана ему не пишут: у бага есть текст ошибки и проект, и разложение на
подзадачи прибавило бы четыре шага там, где хватает одного.

Код правит в своей выкладке репозитория — `task_worktree_ensure` по id самой задачи,
ветка `feature/task_<id>`. Оболочка при этом остаётся в каталоге проекта: меняется
рабочий каталог, а не адрес роли.

Отвечает тем же контрактом, что Developer и QA: `{"ok", "report", "error"}`, где внешний
`ok` говорит «прогон состоялся», а `report.ok` — «баг починен». Различие не формальное:
багфиксер может отработать безупречно и вернуть отрицательный вердикт.

Таймаут прогона — настройка `timeout_bugfix_run` (3600s), блок «⏱ Таймауты» на карточке
`/admin/team`. Лестница прежняя: прогон агента < job воркера < блокировка строки.
```

- [ ] **Step 6: Команда — `project_team.md`**

Дописать четвёртую роль в таблицу ролей и упомянуть флаг запуска:

```markdown
| `bugfixer` | Багфиксер | `claude-shell --gx10 --bugfixer` | `task_bug_fixer` | чинит баги целиком |

Флаг `--bugfixer` живёт в отдельном репозитории `claude-shell` (`src/cli.py`): роль
оболочка знает из флага запуска и сообщает её в реестр сессий. Без флага карточка
багфиксера не станет живой, и захват багов не сработает ни разу.
```

- [ ] **Step 7: Свериться, что документация не расходится с кодом**

```bash
grep -n "bugfixer\|to_bugfix\|bugfixing" .claude/docs/project_task.md .claude/docs/project_team.md | head -30
grep -rn "TASK_ROLE_TYPES" -A 8 src/project/task/task_role.py | head -12
```

Ожидается: имена ролей, типов, состояний и ключей в документации совпадают с кодом посимвольно.

- [ ] **Step 8: Commit**

```bash
git add .claude/docs/project_task.md .claude/docs/project_team.md
git commit -m "Документация: роль bugfixer, вкладка «Баги», состояние bugfixing"
```

---

## Финальная проверка

- [ ] **Полный прогон тестов**

```bash
.venv/bin/python3 -m pytest tests/ -q
```

Ожидается: столько же passed, сколько было до работы, плюс новые.

- [ ] **Ручной круг на живом баге**

1. Поднять оболочку багфиксера в каталоге проекта: `claude-shell --gx10 --bugfixer`.
2. Открыть `/admin/team` — карточка «Багфиксер» стала активной.
3. На `/admin/task`, вкладка «Баги», завести баг с воспроизводимым описанием.
4. Дождаться тика (или дёрнуть вручную) — строка ушла в `bugfixing`, статус «В работе».
5. Дождаться конца прогона — `done` и «Готово» либо `blocked` с причиной в строке.
6. У закрытого бага нажать «diff» — открылась разница ветки `feature/task_<id>` с главной.
7. Нажать «mr2master&rm_worktree» — ветка влита, кнопка посерела.

- [ ] **Проверить, что старая дорога не сломалась**

Завести обычную задачу на «Планировании» и убедиться, что её по-прежнему берёт менеджер,
а не багфиксер: состояние уходит в `planning`, отчёт пишет «Задача взята в планирование
(Менеджер)».
