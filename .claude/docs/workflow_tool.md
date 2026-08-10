# Tools — инструменты для агентов и workflow

> Инструмент — обычная python-функция в `src/tool/<область>/`. Регистрация ручная не
> нужна: `ai_tool_sync()` сканирует папку через AST, вытаскивает сигнатуру и docstring
> и пересобирает таблицы `tool` / `tool_group`. Вызов из workflow — шаг `tool_invoke`.

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `src/tool/` | Сами инструменты, по одной папке на предметную область |
| `src/ai/ai_tool.py` | `ai_tool_sync()` (discovery), `ai_tool_get()`, `ai_tool_args_prepare()` (приведение типов) |
| `src/uvicorn/routers/tool/tool.py` | REST API: список, sync, изолированный тестовый запуск |
| `data/uvicorn/template/admin/tool.html` | Страница `/admin/tool` — каталог инструментов и кнопка sync |
| `src/ai/framework/agent/ai_framework_manager.py` | Шаг `tool_invoke`: сбор аргументов, вызов, запись результата в переменные |

## Создание инструмента

**Путь:** `src/tool/<область>/<файл>.py`. Вложенность разрешена
(`src/tool/project/planning/planning_phase.py`).

Правила именования — общие для проекта (`architecture_rules.md`): имя функции
начинается с префикса, совпадающего с именем файла. Для инструментов это обычно
означает и совпадение с папкой: `src/tool/mysql/mysql_.py` → `mysql_tables_find`.

Реальный пример — `src/tool/env/env_.py`:

```python
from config.config import config_get


async def env_is_prod() -> dict:
    """
    Проверяет, выполняется ли приложение на проде (APP_ENV содержит 'prod' -
    на проде выставлен в '_prod', см. docker-compose.yml). Используется для
    прод-заглушек в workflow (например workflow_shell_test - тестовые прогоны
    должны выполняться только локально).
    Returns:
        dict: Словарь с результатом, содержащий:
            is_prod (str): '1' - выполняется на проде, '0' - локально/иное окружение.
    """
    return {"is_prod": '1' if 'prod' in config_get('APP_ENV', '').lower() else '0'}
```

Требования к функции:

1. **Публичная** — имя без ведущего `_`. Приватные хелперы (`_github_auth`) в БД не попадают.
2. **`async def` или `def`** — движок сам разбирается через `inspect.iscoroutinefunction`.
3. **Аннотации у всех аргументов** — по ним `ai_tool_args_prepare()` приводит типы
   (без аннотации значение уходит в функцию как есть, строкой из workflow-переменной).
4. **Простые типы аргументов** (`str`, `int`, `bool`, `list`, `dict`): значения приходят из
   workflow-переменных, то есть почти всегда строками. Списки/структуры передаются
   JSON-строкой и парсятся автоматически.
5. **Возврат — `dict` с говорящими ключами.** Каждый ключ станет отдельной
   workflow-переменной. Не-dict тоже работает, но переменная будет одна.
6. **Ключи результата описаны в docstring** (секция `Returns:`) — иначе UI и Output Mapping
   не узнают, что вернёт инструмент (см. ниже).
7. **Инструменты узкие и составные.** Вместо одного «умного» — цепочка простых, соединяемых
   через переменные: `mysql_tables_find(tables)` даёт `tables_str`, который идёт на вход
   `mysql_export_to_migration(tables, migration_file)`.
8. **Валидация всего, что уходит в SQL/shell/пути.** Аргументы приходят от LLM
   (см. очистку имён таблиц в `src/tool/mysql/tables_.py`).
9. **Ошибки — в результат, а не в исключение,** если workflow должен продолжиться:
   `{"success": False, "error": str(e)}`. Проброшенное исключение валит весь шаг
   (движок пишет `status='error'` в trace и прерывает workflow).

### Docstring: секция `Returns:`

`ai_tool_sync()` парсит `Returns:` только если аннотация возврата — `dict` или `tuple`.
Формат строки: `имя (тип): описание`, отступ любой. Секция обрывается на `Raises:`,
`Args:` или `Examples:`.

```python
async def mysql_tables_find(tables: list) -> dict:
    """
    Проверяет существование таблиц базы данных по точным именам.
    Returns:
        A dictionary with the found database tables.
        tables_str (str): Имена найденных таблиц через запятую.
        tables_qty (int): Количество найденных таблиц.
    """
```

Распарсенные ключи попадают в `tool.args` → `output.keys` и показываются в
деталях инструмента и в Output Mapping шага `tool_invoke`. Нет `Returns:` —
UI покажет только `{"type": "dict"}`, и маппинг придётся заполнять руками.

## Как работает auto-discovery

`ai_tool_sync(force=False)` (`src/ai/ai_tool.py`):

1. `count_by({})` по таблице `tool`. **Если записей > 0 и `force=False` — синк молча
   пропускается** и возвращает текущее количество.
2. `rglob('*.py')` по `src/tool/`, `__init__.py` игнорируется.
3. AST-разбор файла → имена `FunctionDef` / `AsyncFunctionDef` без ведущего `_`.
4. Динамический импорт файла (`spec_from_file_location`), корень `src/` добавляется в
   `sys.path`. **Импорт файла выполняет его код на верхнем уровне** — тяжёлых side effects
   в module scope быть не должно.
5. Из каждой функции: `inspect.getdoc()` → `description`, `inspect.signature()` → `args`.
6. Группа = имя родительской папки через `.capitalize()`:
   `src/tool/github/github_.py` → `Github`, `src/tool/project/planning/…` → `Planning`.
7. Группы upsert-ятся в `tool_group` по имени, затем `tool` **полностью очищается**
   (`empty()`) и заполняется заново (`add_many`).

Формат `tool.args`:

```json
{
  "input": {
    "tables": { "type": "list", "default": "Required" },
    "limit":  { "type": "int",  "default": "10" }
  },
  "output": {
    "type": "dict",
    "keys": {
      "tables_str": { "type": "str" },
      "tables_qty": { "type": "int" }
    }
  }
}
```

Ошибка в одном файле (битый импорт, исключение на верхнем уровне) логируется и файл
пропускается — остальные инструменты синхронизируются.

### Грабли

- **Имя инструмента уникально глобально.** `tool.name` — `UNIQUE CHAR(50)`. Две одноимённые
  функции в разных папках → `add_many` падает целиком, а `empty()` уже выполнен: таблица
  `tool` остаётся **пустой**, `ai_tool_sync` вернёт `0`. Имя длиннее 50 символов — та же
  история.
- **`path` — абсолютный путь** (`CHAR(200)`), записанный тем процессом, который делал синк.
  После переноса кода в другой каталог/контейнер нужен новый синк.
- **Одинаковые имена папок сливаются в одну группу:** `src/tool/design/` и
  `src/tool/project/design/` дают группу `Design`.
- **`empty()` временно обнуляет таблицу.** Поэтому в `main_uvicorn.py` `planning_runner`
  стартует строго после синка — иначе он загрузит `{}` и упадёт с «инструмент не найден».
- **Локально простого рестарта недостаточно.** В `lifespan()` вызов зависит от окружения:
  на проде `ai_tool_sync(force=True)` (каждый рестарт подхватывает изменения), локально
  `ai_tool_sync()` — без force, то есть новый/переименованный/перемещённый инструмент в БД
  не появится. Нужен ручной sync.

## Синхронизация вручную

Кнопка на странице `/admin/tool` (шлёт `POST /tool/sync`) либо:

```bash
curl -X POST http://localhost:8011/tool/sync -b cookies.txt   # нужна авторизация: tool:update
```

Из контейнера (функция асинхронная):

```bash
docker exec uvicorn python3 -c "
import asyncio
from src.ai.ai_tool import ai_tool_sync
print(asyncio.run(ai_tool_sync(force=True)))
"
```

## REST API

Роутер подключён без префикса (`main_uvicorn.py`).

| Метод | Путь | Права | Назначение |
|-------|------|-------|-----------|
| GET | `/tool/list` | `tool:view` | Все инструменты + имя группы |
| GET | `/tool/group/list` | `tool:view` | Группы, сортировка по имени |
| GET | `/tool/{tool_id}` | `tool:view` | Один инструмент |
| POST | `/tool/sync` | `tool:update` | `ai_tool_sync(force=True)`, вернёт `synced_count` |
| POST | `/tool/test/{tool_id}` | `tool:test` | Запуск инструмента с произвольными аргументами |

`POST /tool/test/{tool_id}` — тот же путь исполнения, что и в workflow
(`ai_tool_args_prepare` → вызов), поэтому это честная проверка приведения типов.
Тело — словарь аргументов; ответ `{"status": "success"|"error", "result": …}`,
исключение не пробрасывается, а возвращается текстом.

## Приведение типов (`ai_tool_args_prepare`)

Аргументы из workflow приходят строками, поэтому перед вызовом они кастуются по
аннотациям:

| Аннотация | Что делает |
|-----------|-----------|
| `bool` | строка → `True` для `true / 1 / yes / on` (регистр не важен), иначе `bool(value)` |
| `dict`, `list`, `list[...]`, `dict[...]` | строка → `json.loads`; не JSON → остаётся строкой |
| `str` | `dict`/`list` → `json.dumps(ensure_ascii=False)` (не python-repr с кавычками-апострофами) |
| `X \| None`, `Optional[X]` | берётся первый не-`None` тип и применяется как `X(value)` |
| прочее callable (`int`, `float`, …) | `expected_type(value)` |
| нет аннотации, значение `None`, аргумент не в сигнатуре | передаётся как есть |

Неудачный каст логируется и **не** прерывает вызов — уходит сырое значение.

## Вызов из workflow

Шаг `tool_invoke`: `inputs_map` — соответствие «аргумент функции → **имя**
workflow-переменной» (литерал задаётся префиксом `_const_`). Полные правила, частые
ошибки и чек-лист — `workflow.md`, раздел «Тип шага `tool_invoke`».

Результат раскладывается в переменные автоматически:

| Что вернул инструмент | Переменные |
|---|---|
| `dict` | по одной на ключ: `{tool_name}_{step_id}_result_{key}` |
| `str` / `int` / `bool` / `float` / `list` / `tuple` | одна: `{tool_name}_{step_id}_result_{str\|int\|bool\|float\|list}` |
| прочий объект | `{tool_name}_{step_id}_result_{имя_типа}` |

`step_id` в имени делает переменные уникальными: два вызова одного инструмента в одном
workflow не перетирают друг друга. Вложенные `dict`/`list` внутри значений сериализуются
в JSON-строку. `outputs_map` задаёт короткие алиасы к этим автоименам.

Каждый вызов пишется в историю сессии (`ai_session_message`, `kind_type='tool-call'`)
и в trace шага — см. `workflow_trace.md`.

## Существующие области

| Папка | Группа | Примеры |
|-------|--------|---------|
| `agent/` | `Agent` | `agent_.py`, `agent_workflow_.py` |
| `claude_/`, `claude_shell/` | `Claude_`, `Claude_shell` | `claude_shell_call` (`claude_shell.md`) |
| `companion/`, `counter/`, `datetime_/`, `session/`, `setting/` | по папке | служебные |
| `design/`, `project/design/` | `Design` | блоки, страницы, виджеты, wireframe |
| `detective/`, `fact/`, `qdrant/` | `Detective`, `Fact`, `Qdrant` | факты и векторный поиск |
| `dict/`, `list/`, `text/` | `Dict`, `List`, `Text` | преобразование переменных |
| `env/` | `Env` | `env_is_prod` |
| `github/` | `Github` | репозитории, коммиты, PR |
| `mysql/` | `Mysql` | `mysql_tables_find`, экспорт в миграцию |
| `project/`, `project/planning/` | `Project`, `Planning` | `project_planning.md` |
| `weather/`, `web/` | `Weather`, `Web` | внешние запросы, скриншоты |

Актуальный список всегда в `/admin/tool`.

## MCP как источник инструментов

Инструменты MCP-серверов регистрируются отдельным путём (`py_modules/ai/ai_mcp.py`),
в таблицу `tool` не попадают и в `src/tool/` не лежат — см. `ai_framework.md`.
