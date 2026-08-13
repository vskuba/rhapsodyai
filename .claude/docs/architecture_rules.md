# Architecture Rules — правила написания кода

> Обязательные правила для всего кода в `src/` и `py_modules/`: префикс функции равен
> namespace файла, файлы дробятся по ответственности, `src/cronjob/` — только точки входа.
> Применяются и к новым файлам, и к правкам существующих.

## 0. Перед созданием нового файла — проверь паттерн

**Перед тем как создать новый файл, всегда посмотри на уже существующие файлы в целевой
папке и используй тот же шаблон именования.**

Правило применяется перед `Write` и перед `Edit` при создании нового файла.

```
src/project/task/
    task_agent_developer.py
    task_agent_manager.py
    task_agent_qa.py
    task_claim.py
    task_pipeline.py
    task_plan.py
    task_revision.py
    task_state.py
    task_tree.py
```

Шаблоны:
- `task_<domain>_<action>.py` → функции `task_<domain>_<action>_...`
- `task_<domain>.py`          → функции `task_<domain>_...`
- `tool_<feature>_`           → функции `tool_<feature>_...`

Ошибочный паттерн (обратный порядок слов):
- `bug_task_create.py` ❌ — нарушает существующий `task_*` шаблон модуля

Правильный паттерн:
- `task_bug_create.py` ✅ — продолжает `task_*` шаблон

```bash
# Посмотри, какие файлы уже есть в папке, прежде чем создавать новый:
ls src/project/task/*.py

# Посмотри префиксы функций в существующих файлах:
grep -oP '^async def \K[a-z_0-9]+' src/project/task/*.py | sort -u
```

## 0.5 Константы: UPPER_CASE с префиксом namespace

Публичные константы (UPPER_CASE) в файлах — тоже с префиксом namespace.
Namespace = путь от `src/` до файла, разделители `/` → `_`.

```
src/project/task/task_pipeline.py      → namespace: project_task
src/ai/ai_llm.py                       → namespace: ai
src/uvicorn/routers/project/project_task.py → namespace: project_task_project_task
```

Правило:
```python
# ❌ — без префикса (может конфликтовать с другими модулями)
MAX_ATTEMPTS = 3
BUG_TASK_SCAN_ENABLED = True

# ✅ — с префиксом namespace
PROJECT_TASK_BUG_SCAN_ENABLED = True  # из task_pipeline.py
AI_LLM_TIMEOUT = 120.0                # из ai_llm.py
```

Разбор: `PROJECT_TASK` = namespace модуля, `BUG_SCAN` = подсистема, `ENABLED` = тип переключателя.

Константы, используемые только внутри файла (локальные утилиты), допускаются без префикса.
Но при сомнениях — всегда добавляй префикс: безопаснее избыточный, чем конфликт имён.

## 1. Имена функций соответствуют namespace файла

Все публичные функции внутри файла начинаются с префикса, равного пути «папка + имя
файла».

```
src/tool/fact/fact_collection_.py   ->  fact_collection_add()
                                        fact_collection_remove_by()
                                        fact_collection_output_format()

src/tool/project/design/design_block.py  ->  design_block_save()
                                             design_block_list()

src/ai/ai_llm.py                    ->  ai_llm_node_get()
                                        ai_llm_image_generate()
```

### Хвостовое подчёркивание в имени файла — не часть префикса

`_` на конце имени файла ставится, чтобы не конфликтовать с именем пакета или
встроенным модулем. В префикс он не входит:

| Файл | Префикс |
|------|---------|
| `src/tool/fact/fact_collection_.py` | `fact_collection_` |
| `src/tool/mysql/mysql_.py` | `mysql_` → `mysql_find_by()` |
| `py_modules/queue_/queue_.py` | `queue_` → `queue_get()` |

### Точки входа кронджобов

Скрипты в `src/cronjob/**`, запускаемые как процесс, используют `async def main()` —
это единственное исключение из правила префикса, и оно распространяется на все кронджобы
без разбора (см. `src/cronjob/task_orchestrator.py`). Вся логика при этом выносится в
модуль в `src/<domain>/` и уже подчиняется правилу полностью.

## 2. Приватные функции: имя по смыслу, место — в конце файла

**Правило 1 на приватные функции (`_prefix`) не распространяется** — их можно называть
по смыслу, без префикса namespace:

```python
# src/tool/mysql/mysql_.py — имена по смыслу, префикс не нужен
def _where_build(table_name: str, criteria: dict) -> tuple:
    ...

def _row_json_safe(row: dict) -> dict:
    ...
```

Префикс в приватной функции не ошибка (`_ai_llm_comfyui_workflow()` в `ai_llm.py`), но
и не требование.

**Зато место строго фиксировано: все приватные — ниже всех публичных, в конце файла.**

```python
# ── публичный API модуля ──

async def task_state_task_get(task_id: int) -> dict:
    ...

async def task_state_plan_save(task_id: int, plan_json: str) -> None:
    ...


# ── детали реализации ──

def _where_build(table_name: str, criteria: dict) -> tuple:
    ...
```

Причина — порядок чтения: файл открывают, чтобы понять, что модуль умеет, а не как он
это делает. Публичные функции сверху дают ответ сразу.

Правило распространяется и на правки: если в файле приватная функция оказалась выше
публичных — переместить вниз, даже если менял в файле что-то другое.

## 3. Файлы дробить по функционалу и namespace

Один файл — одна ответственность. Вместо толстого модуля создаётся директория-namespace
с несколькими небольшими файлами:

```
src/tool/project/design/
    design_block.py       66 строк
    design_page.py        89 строк
    design_widget.py     202 строки
    design_wireframe.py  351 строка
```

Ориентир по размеру — **до ~150-200 строк**. Само по себе превышение не криминал
(`design_wireframe.py` — 351), но это сигнал проверить, не совмещает ли файл несколько
ответственностей.

### Признак, что пора делить

Файл делает несколько разных вещей. Пример из `src/project/task/` — исходно один
`task_pipeline.py` на ~370 строк совмещал четыре ответственности, разделён на:

| Файл                | Ответственность                   |
|---------------------|-----------------------------------|
| `task_pipeline.py`  | машина состояний                  |
| `task_claim.py`     | захват работы, реклейм блокировок |
| `task_state.py`     | запись состояний и истории в БД   |
| `task_plan.py`      | формат плана (сериализация)       |
| `task_agent_manager.py`   | роль Manager: план, разбиение     |
| `task_agent_developer.py` | роль Developer: реализация        |
| `task_agent_qa.py`        | роль QA: приёмка по целям         |

Каждый файл после деления получает **свой префикс функций** по правилу 1:
`task_claim_worker_id()`, `task_state_subtask_set()`, `task_plan_parse()`.

То же и для роутеров: CRUD задач — `project_task.py`, конвейер — `project_task_pipeline.py`.

## 4. Где размещаются файлы

Три ветки с разным назначением. Положить файл не в ту ветку — не стилистическая
погрешность, а функциональная ошибка: у `src/tool/` и `src/cronjob/` особое поведение.

### 4.1 `src/**` — основные функции по namespace

Бизнес-логика приложения раскладывается по папкам и подпапкам, отражающим namespace
функционала:

```
src/ai/                          AI-фреймворк, workflow, инструменты, факты
src/auth/                        аутентификация, права, полевые политики
src/project/task/                конвейер задач
src/uvicorn/routers/<entity>/    HTTP-эндпоинты
```

Глубина — по смыслу, не ради глубины. Имя файла = последний уровень namespace, оно же
даёт префикс функций (правило 1).

### 4.2 `src/tool/**` — инструменты Engine Workflow

Отдельная ветка **только** для функций, вызываемых как инструменты из движка workflow
(шаг `tool_invoke`). Раскладка — так же по namespace в папках и подпапках:

```
src/tool/fact/fact_collection_.py
src/tool/project/design/design_block.py
src/tool/project/planning/planning_block.py
```

Чем эта ветка отличается от остального `src/` (механика в `src/ai/ai_tool.py`):

- **автообнаружение** — `rglob('*.py')` по `src/tool/`, ручная регистрация не нужна
  (`ai_tool.py:33-45`)
- инструментом становится **каждая публичная функция** файла; приватные (`_prefix`)
  пропускаются (`ai_tool.py:57`)
- **докстринг = описание инструмента для LLM**, поэтому он обязателен и пишется для
  читателя-модели; секция `Returns:` разбирается на ключи результата
- **группа инструмента = имя родительской папки** (`ai_tool.py:69`) — структура папок
  видна в UI
- после перемещения или переименования файла — `POST /tool/sync`, пути хранятся в БД

> Обычную бизнес-логику в `src/tool/` не класть: она автоматически станет инструментом,
> попадёт в БД и будет предложена LLM.

### 4.3 `src/cronjob/**` — только точки входа планировщика

Файлы, которые дёргает Cronicle через `POST /cronjob`. Каждый — тонкий: разбор
`sys.argv[1]`, вызов доменной функции, `print(json.dumps(...))`, закрытие пула в
`finally`. Логика живёт в `src/<domain>/` и вызывается оттуда.

```
src/cronjob/task_orchestrator.py    ← точка входа, ~35 строк
src/project/task/task_pipeline.py   ← логика, которую она вызывает
```

Признак нарушения — файл в `src/cronjob/` без `__main__`. Единственное исключение —
`src/cronjob/cronjob.py` (исполнитель джобов, сам не джоб).

Отдельно: asyncio-раннеры, живущие в процессе uvicorn и запускаемые из lifespan, —
не кронджобы. Их место в `src/<domain>/`, а не в `src/cronjob/`.

## 5. Приведение существующего кода

Если правишь файл, где имена не совпадают с namespace, — приводи к правилу заодно.
Это ожидаемая часть работы, а не выход за рамки задачи.

Пример: в `src/uvicorn/routers/project/project_task.py` функции назывались
`planning_task_*` (наследие от старого расположения) → переименованы в `project_task_*`.

При переименовании проверить, что имя нигде не используется как строка:

```bash
grep -rn "старое_имя" src/ py_modules/ tests/ data/uvicorn/
```

Для инструментов в `src/tool/**` после переименования или перемещения файла вызвать
`POST /tool/sync` — пути инструментов хранятся в БД.

## Автопроверка

Найти функции, нарушающие правило 1, в конкретной директории:

```bash
for f in src/tool/fact/*.py; do
  base=$(basename "$f" .py); base=${base%_}   # снять хвостовое подчёркивание
  bad=$(grep -oP '^(async )?def \K[a-z_0-9]+' "$f" | grep -v "^_" | grep -v "^${base}_" || true)
  [ -n "$bad" ] && echo "$f: $(echo $bad)"
done
```

Единственное допустимое совпадение в выводе — `main` в точке входа кронджоба.
Всё остальное чинится, а не заносится в список исключений.

Найти файлы, где приватная функция стоит выше публичной (правило 2):

```bash
find src py_modules -name '*.py' -not -path '*/__pycache__/*' | while read -r f; do
  last_pub=$(grep -nP '^(async )?def [a-z]' "$f" | tail -1 | cut -d: -f1)
  first_priv=$(grep -nP '^(async )?def _' "$f" | head -1 | cut -d: -f1)
  [ -n "$last_pub" ] && [ -n "$first_priv" ] && [ "$first_priv" -lt "$last_pub" ] && echo "$f"
done
```

Вывод должен быть пустым. Найденное чинится по мере правок этих файлов (правило 5) —
списка «согласованных исключений» не существует.

Найти в `src/cronjob/` файлы, которые не являются точками входа (правило 4.3):

```bash
find src/cronjob -name '*.py' -not -path '*__pycache__*' -not -name 'cronjob.py' \
  | while read -r f; do grep -q "__main__" "$f" || echo "не точка входа: $f"; done
```

Найти файлы-кандидаты на дробление:

```bash
find src/ py_modules/ -name '*.py' -exec wc -l {} + | sort -rn | head -20
```
