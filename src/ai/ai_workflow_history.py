"""История правок workflow: одна дверь записи и расчёт «что на что».

## ⚠⚠⚠ Зачем: ошибка была неявной

03.10.2026 цикл инвайтов стал давать один шаблон вместо одиннадцати — у шага
`workflow_invoke` поле `repeat.count` потеряло метку `%invite_count%` и стало
единицей. Потерял её редактор, а **ошибки не было ни одной**: прогон шёл, пул
набирался, панель докладывала «готово 93».

Следа правки при этом не было нигде. Время поломки определяли косвенно — по
числу разных текстов в чужой базе, заход за заходом, — и вышло с точностью до
трёх минут.

Отсюда правило: **любая правка workflow оставляет запись**.

## Где это стоит и почему не в репозитории

Запись зовут **ручки** (`src/uvicorn/routers/workflow/`), а не
`AbstractRepository`, и доводов два:

1. репозиторий лежит в **общем слое** `py_modules` — он общий для всех проектов,
   и правка ради одной вкладки одного проекта затронула бы соседей;
2. репозиторий **не знает автора**: `AuthSession` известна только ручке. История
   без автора отвечает на половину вопроса.

⚠ Импорт (`ai_workflow_import.py`) пишет прямым SQL, минуя репозитории: хук в
репозитории не поймал бы его вовсе, а он меняет всё сразу.

## ⚠⚠ Автосохранение — не изменение

Правка шага уходит в базу сама, через 400 мс после касания поля (`steps.js`),
кнопки «Сохранить» нет. Поэтому запись заводится **только когда дифф непустой**:
щелчок по полю и правка, отменённая тут же, изменением не являются. Иначе лента
наполнилась бы событиями «ничего не изменилось» и похоронила бы те, ради которых
её читают.

## ⚠ Длинные значения — только изменившиеся части

Промпт шага бывает по 9 КБ, и полный текст в истории не нужен ни «до», ни
«после» (решение человека). Строки длиннее `HISTORY_VALUE_SHORT` сравниваются
**построчно**, и в запись идут только изменившиеся строки с номерами.
"""

import difflib
import json

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Что правили.
HISTORY_OBJECT_WORKFLOW = 'workflow'
HISTORY_OBJECT_STEP = 'step'
HISTORY_OBJECT_VARIABLE = 'variable'

# Что сделали.
HISTORY_ACTION_CREATE = 'create'
HISTORY_ACTION_UPDATE = 'update'
HISTORY_ACTION_DELETE = 'delete'
HISTORY_ACTION_REORDER = 'reorder'
HISTORY_ACTION_IMPORT = 'import'

# Кто. ⚠ `agent` — правка инструментом, человека за ней нет вовсе.
HISTORY_AUTHOR_HUMAN = 'human'
HISTORY_AUTHOR_AGENT = 'agent'
HISTORY_AUTHOR_IMPORT = 'import'

# Докуда значение считается коротким и хранится целиком.
#
# ⚠ Двести знаков — это примерно три строки текста: заголовок шага, имя
# переменной, число, метка. Всё, что длиннее, почти всегда промпт, и там нужен
# построчный дифф, а не два полных текста.
HISTORY_VALUE_SHORT = 200

# Докуда обрезается одна строка построчного диффа. ⚠ Нужен предел: строка
# промпта бывает абзацем на тысячу знаков, а в ленте читают начало.
HISTORY_LINE_MAX = 300

# Сколько изменившихся строк храним у одного поля. ⚠ Правка, задевшая полсотни
# строк, — это переписанный промпт: перечислять их все незачем, довольно сказать
# «и ещё N».
HISTORY_LINES_MAX = 20

# Поля, которые в историю не идут вовсе: они меняются сами и смысла не несут.
#
# ⚠ `position` исключён **только у правки шага**, а не у перестановки: там он и
# есть предмет события (`HISTORY_ACTION_REORDER`).
HISTORY_SKIP_FIELDS = ('id', 'created_at', 'updated_at')


async def workflow_history_write(workflow_id: int, object_: str, action: str,
                                 changes: list = None, user=None,
                                 object_id: int = 0, object_name: str = '',
                                 author: str = '') -> None:
    """Пишет одну правку в историю. **Ничего не бросает.**

    Args:
        workflow_id: чей workflow.
        object_: что правили — `workflow`, `step`, `variable`.
        action: что сделали — `create`, `update`, `delete`, `reorder`, `import`.
        changes: что именно изменилось — список `{field, was, now}` от
            `workflow_history_changes`. Пустой список у `update` означает «ничего
            не изменилось», и запись **не заводится**.
        user: `AuthSession` запроса. `None` — правка не человеком.
        object_id: номер шага или переменной. Ноль — правка самого workflow.
        object_name: имя предмета на момент правки, копией.
        author: род автора. Пусто — `human` при наличии `user`, иначе `agent`.

    ## ⚠⚠ Почему не бросает

    Правка workflow важнее своей записи в истории: уроним правку из-за журнала —
    человек потеряет работу. Тот же приём и тот же довод, что у `log_write` в
    DatingAi.

    ## ⚠ Почему не `create_task`

    Запись идёт **в том же запросе**, последовательно. «Fire and forget»
    (`event_emit`) теряет порядок, а история без порядка врёт в ответе на
    «когда» — то есть именно на тот вопрос, ради которого её заводили.
    """
    workflow_id = int(workflow_id or 0)
    if not workflow_id or not object_ or not action:
        return

    # ⚠⚠ **Пустой дифф — не событие.** Автосохранение шлёт правку и на щелчок по
    # полю; см. шапку модуля. То же у перестановки: список позиций приезжает
    # целиком, и «перетащили, но вернули на место» изменением не является.
    #
    # ⚠ У `create`/`delete`/`import` пустой дифф **законен**: там событие — сам
    # факт, а не разница значений.
    if action in (HISTORY_ACTION_UPDATE, HISTORY_ACTION_REORDER) and not changes:
        return

    if not author:
        author = HISTORY_AUTHOR_HUMAN if user else HISTORY_AUTHOR_AGENT

    user_id = int(getattr(user, 'user_id', 0) or 0)
    username = str(getattr(user, 'username', '') or '')[:190]

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO `agent_workflow_history`'
                ' (`workflow_id`, `object`, `object_id`, `object_name`,'
                '  `action`, `changes`, `user_id`, `username`, `author`)'
                ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (workflow_id, str(object_), int(object_id or 0),
                 str(object_name or '')[:190], str(action),
                 json.dumps(changes or [], ensure_ascii=False),
                 user_id, username, str(author)))
    except Exception as e:
        # ⚠ Молчим в лог, а не наружу: правка уже случилась, и отменять её
        # из-за журнала нельзя.
        logger_info(f'⚠️ История workflow #{workflow_id} не записалась: {e}')


def workflow_history_changes(was: dict, now: dict,
                             skip: tuple = HISTORY_SKIP_FIELDS) -> list[dict]:
    """Что изменилось между «до» и «после». Пустой список — ничего.

    Args:
        was: строка предмета до правки (из базы).
        now: что пришло в запросе. ⚠ Сравниваются **только присланные поля**: в
            запросе шага приезжают `metadata` и `title`, и отсутствие прочих не
            значит, что их стёрли.
        skip: поля, которые в историю не идут.

    Returns:
        list: `[{field, was, now}, …]`. У длинных строк вместо `was`/`now` —
        `lines` с изменившимися строками.

    ## ⚠⚠ `metadata` разворачивается по ключам, рекурсивно

    Плоское «изменилось metadata» на 656 знаков вернуло бы ту же слепоту, из-за
    которой история и понадобилась: глазами разницу в одном вложенном поле там не
    находят. Поэтому путь до листа — `metadata.workflow_invoke.repeat.count`.
    """
    rows = []

    for key, value in (now or {}).items():
        if key in skip:
            continue

        before = (was or {}).get(key)

        # ⚠ `metadata` у шага приезжает **строкой JSON**, а в базе лежит тоже
        # строкой: сравнивать их как строки значило бы объявлять правкой смену
        # порядка ключей. Разбираем обе и идём по ключам.
        one, two = _maybe_json(before), _maybe_json(value)
        if isinstance(one, (dict, list)) or isinstance(two, (dict, list)):
            rows.extend(_deep(key, one, two))
            continue

        if _same(one, two):
            continue

        rows.append(_change(key, one, two))

    return rows


def workflow_history_name(row: dict) -> str:
    """Имя предмета для записи: заголовок шага, имя переменной, имя workflow.

    ⚠ Берётся из строки **до** правки, если она есть: событие «переименован»
    должно называться прежним именем, иначе в ленте оно выглядит как правка
    того, чего тогда не существовало.
    """
    row = row or {}

    return str(row.get('title') or row.get('name') or '')[:190]


# ── Приватное ────────────────────────────────────────────────────────────────

def _maybe_json(value):
    """Строка, похожая на JSON, — разобранной. Прочее — как есть.

    ⚠ Не разобралось — возвращаем исходное, а не падаем: в метаданных живого
    шага встречается и то, что JSON-ом не является, и история не должна ронять
    правку из-за своего разбора.
    """
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text or text[0] not in '{[':
        return value

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return value


def _same(one, two) -> bool:
    """Одно и то же? Сравниваем **как текст**: `2` и `"2"` — одно значение.

    ## ⚠⚠⚠ Строгое сравнение по типу писало фантомные правки

    Здесь стояло `type(one) is type(two) and one == two`, и довод был про
    `repeat.count`: единица и метка `%invite_count%` — ровно та разница, ради
    которой история завелась. Довод верный, вывод — нет.

    Форма workflow берёт `node_id` из `<select>`, а оттуда всё приходит
    **строкой**; в базе колонка `INT`. Каждое нажатие «Сохранить workflow»
    писало в историю `node_id: 2 → 2` — правку, которой не было. Лента
    набивалась фантомами, и настоящая правка тонула среди них: на вопрос «что
    именно поменяли» она отвечала «ничего, но много раз».

    ⚠ Защита от той самой беды цела: `%invite_count%` и `1` различны и как
    текст. Текстовое сравнение ловит подмену значения, а не подмену типа при
    том же значении, — а движку важно именно значение.

    ⚠⚠ `None` держится особняком: «не было поля» и «пустая строка» — разные
    состояния (лента так их и показывает: «нет» против «пусто»), а `str(None)`
    слил бы их с текстом `'None'`.
    """
    if one is None or two is None:
        return one is None and two is None

    return str(one) == str(two)


def _deep(path: str, one, two) -> list[dict]:
    """Дифф двух вложенных значений: путь до листа.

    ⚠ Списки сравниваются **целиком**, а не поэлементно: `transitions_after` —
    это перечень, и «изменился элемент 2» человеку говорит меньше, чем «изменился
    перечень». Поэлементный дифф списков оставлен за ненадобностью.
    """
    # ⚠⚠ **Достаточно, чтобы словарём был один из двух.** Требуй оба — и путь
    # обрывался бы на появившемся ключе: `{}` → `{"repeat": {"count": 3}}` дало
    # бы «изменилось metadata.repeat» вместо `metadata.repeat.count`, то есть ту
    # самую слепоту, из-за которой история и завелась. Поймано тестом.
    if isinstance(one, dict) or isinstance(two, dict):
        one = one if isinstance(one, dict) else {}
        two = two if isinstance(two, dict) else {}

        rows = []
        for key in list(one.keys()) + [k for k in two if k not in one]:
            if key in one and key in two and _same(one[key], two[key]):
                continue

            rows.extend(_deep(f'{path}.{key}', one.get(key), two.get(key)))

        return rows

    if _same(one, two):
        return []

    return [_change(path, one, two)]


def _change(field: str, one, two) -> dict:
    """Одна запись диффа. Длинные строки — построчно (см. шапку модуля)."""
    if isinstance(one, str) and isinstance(two, str) \
            and (len(one) > HISTORY_VALUE_SHORT or len(two) > HISTORY_VALUE_SHORT):
        return {'field': field, 'lines': _lines(one, two)}

    return {'field': field, 'was': _short(one), 'now': _short(two)}


def _short(value):
    """Значение для записи: коротким — как есть, длинным — обрезанным."""
    if isinstance(value, str) and len(value) > HISTORY_VALUE_SHORT:
        return value[:HISTORY_VALUE_SHORT] + '…'

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:HISTORY_VALUE_SHORT]

    return value


def _lines(one: str, two: str) -> list[dict]:
    """Изменившиеся строки двух текстов — и только они.

    ⚠⚠ Полного текста не храним ни «до», ни «после»: правка одной фразы в
    промпте на 9 КБ даёт одну строку истории, а не девять килобайт дважды.

    Returns:
        list: `[{op: '-'|'+', line: N, text: '…'}, …]`; последним элементом
        может стоять `{'more': N}` — сколько изменений не показано.
    """
    rows = []
    before, after = one.splitlines(), two.splitlines()

    for mark in difflib.SequenceMatcher(None, before, after).get_opcodes():
        kind, a1, a2, b1, b2 = mark
        if kind == 'equal':
            continue

        # ⚠ Номер строки — **человеческий**, с единицы: по нему ищут глазами в
        # поле промпта, а там нумерация с первой строки.
        for at in range(a1, a2):
            rows.append({'op': '-', 'line': at + 1,
                         'text': before[at][:HISTORY_LINE_MAX]})
        for at in range(b1, b2):
            rows.append({'op': '+', 'line': at + 1,
                         'text': after[at][:HISTORY_LINE_MAX]})

    if len(rows) > HISTORY_LINES_MAX:
        more = len(rows) - HISTORY_LINES_MAX

        return rows[:HISTORY_LINES_MAX] + [{'more': more}]

    return rows
