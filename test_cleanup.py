#!/usr/bin/env python3
"""Уборка за тестами: сносит всё, что они завели, из MySQL и Qdrant.

## ⚠⚠ Зачем

Тесты пишут в те же базы, где живёт работа, и прибирают за собой не всё. Замер
одного прогона быстрой сюиты: 315 строк в журнале событий, пять задач, один
собеседник и **три переменные workflow** — последнее хуже прочего, потому что
`agent_workflow_variable` это справочник, из которого собираются промпты. За всё
время их накопилось **220**.

LLM-тесты добавляют своё в Qdrant: факты о выдуманных собеседниках и о
переписках с ними.

Копится это от прогона к прогону. Само по себе безвредно, но растёт, а главное —
тест, наткнувшийся на след прошлого прогона, краснеет «без причины», и виноватым
выглядит код.

## Правило

**Всё, что заводит тест, начинается с `pytest_`.** Один признак, проверяемый
одним условием; по нему и работает эта уборка.

⚠⚠ Приставка `test` для этого **не годится**: ею начинаются и рабочие имена —
переменные workflow `workflow_shell_test` зовутся `test_dialog`, `test_message`,
`test_workflow_id`. Первая версия уборки насчитала по ней 225 строк к удалению,
из них пять рабочих. Спасла сухая выдача.

Приставку даёт `tests_llm.conftest.test_key`. У старой сюиты свои имена — их
исключения перечислены ниже, в `RULES`, и каждое проверено запросом.

## Как пользоваться

    ./test_cleanup.py            # показать, что будет снесено
    ./test_cleanup.py --apply    # снести

⚠ **Без `--apply` не удаляет ничего.** Уборка ходит в ту же базу, где живёт
работа; молча стирающий скрипт в такой базе — способ однажды потерять чужое.
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

from tests_llm.mark import TEST_MARK

# ── Куда ходим ──────────────────────────────────────────────────────────────
#
# ⚠ Через `docker exec`, а не напрямую: в `.env` адрес базы — имя контейнера
# (`mysql`), с хоста оно не резолвится. Тот же приём, что у прочих скриптов.
MYSQL_CONTAINER = 'rhapsodyai-mysql-1'
MYSQL_DB = 'project'
QDRANT_URL = 'http://localhost:6335'

# ⚠ Приставку берём **у владельца** (`tests_llm/mark.py`), а не объявляем
# свою. Разойдись они — тесты метили бы одним, уборка искала другое, и мусор
# копился бы при работающей на вид уборке.
#
# ⚠⚠ Почему приставка не `test`, а `pytest_`, и чего это чуть не стоило —
# там же, в `mark.py`.
MARK = TEST_MARK

# Заголовок всего, что сюита заводит в конвейере: задачи и проекты под ними
# (`tests/conftest.py`, `TEST_TITLE_LIKE`). Два подчёркивания — начало заголовка,
# экранированы потому, что в LIKE `_` это любой один символ.
TITLE_LIKE = f'\\_\\_{MARK}%'

# Подзапрос «номера тестовых проектов». Обёрнут производной таблицей: MySQL не даёт
# читать в подзапросе ту таблицу, из которой удаляет, а обёртка снимает запрет —
# приём уже применён в `RULES` для собеседников.
PROJECT_IDS = (f"SELECT `id` FROM (SELECT `id` FROM `project`"
               f" WHERE `title` LIKE '{TITLE_LIKE}') p")

# Коллекции фактов, куда пишут LLM-тесты.
COLLECTIONS = ('dating_girl', 'dating_companion', 'dating_talk')

# ⚠⚠ Долг старой фикстуры: документы `9<7 hex>_Zinaida-Test`. Тест `test_route.py`
# строил ключ девушки как `f'9{uuid…}'` — похоже на номер анкеты и **без метки**,
# поэтому ни уборка после теста, ни поиск по приставке их не находили. Фикстура
# исправлена (`mark_key`), а накопленное надо снести.
#
# ⚠ Образец **точный**: `9` + ровно семь шестнадцатеричных + это самое имя. Рабочий
# ключ под него не подойдёт — у живых анкет номер шестизначный и имя человека.
QDRANT_DEBT = re.compile(r'^9[0-9a-f]{7}_Zinaida-Test$')

# ── Что считать тестовым в MySQL ────────────────────────────────────────────
#
# Пара «таблица → условие». Условие пишется так, чтобы **не задеть рабочее**:
# приставка, а не «похоже на тестовое».
RULES = (
    # ── Новый признак: приставка `pytest_` ──────────────────────────────────
    #
    # Безопасны по построению: совпасть с рабочим такое имя не может.
    ('agent_workflow_variable', f"`name` LIKE '{MARK}\\_%'"),
    ('agent', f"`name` LIKE '{MARK}\\_%'"),
    ('user', f"`username` LIKE '{MARK}\\_%'"),
    ('user_access_token', f"`token` LIKE '{MARK}\\_%'"),

    # ── Разговоры пар и их участники ────────────────────────────────────────
    #
    # ⚠⚠ **Порядок здесь обязателен: разговоры раньше собеседников.**
    # `companion_session.owner_id` и `.companion_id` — внешние ключи на
    # `companion`. Снеси собеседника первым, и удаление упрётся в него, а вся
    # уборка оборвётся на середине.
    #
    # ⚠ Отбор по **владельцу или собеседнику** с меткой, а не по своей метке:
    # у строки разговора своего имени нет вовсе, она узнаётся только по паре.
    ('companion_session',
     f"`owner_id` IN (SELECT `id` FROM (SELECT * FROM `companion`) c"
     f" WHERE c.`unique_id` LIKE '{MARK}\\_%')"
     f" OR `companion_id` IN (SELECT `id` FROM (SELECT * FROM `companion`) c2"
     f" WHERE c2.`unique_id` LIKE '{MARK}\\_%')"),

    # ⚠⚠ Столбец `unique_id`, а не `name`. Звался он `name`, и правило искало по
    # прежнему имени — то есть уборка **падала целиком** на первом же запросе
    # («Unknown column 'name'»), причём молча для того, кто смотрел только на
    # итоговую цифру. Тестовый мусор копился при «работающей» уборке.
    ('companion', f"`unique_id` LIKE '{MARK}\\_%'"),

    # ── Долг старой сюиты: имена, заведённые до правила ──────────────────────
    #
    # ⚠⚠ Каждое условие здесь **точное**, а не по приставке, и проверено
    # запросом перед тем, как попасть в список. Приставка `test` тут не годится:
    # ею начинаются и рабочие имена (см. `MARK` выше).
    #
    # Это долг, а не устройство: приведут имена к `pytest_` — строки уйдут.

    # ⚠ Ровно `test_var_<число>` и `test_dup_var_<число>` — то, что заводит
    # сюита переменных. Рабочие переменные workflow `test` (`test_dialog`,
    # `test_workflow_id`) под это не подходят: у них нет числового хвоста.
    # Накопилось 220 штук за всё время.
    ('agent_workflow_variable',
     "`name` REGEXP '^test_(dup_)?var_[0-9]+$'"),
    ('role', "`name` IN ('test_role', 'updated_role')"),
    ('user_access_token', "`token` LIKE '%cleanup_probe'"),

    # ── Проекты сюиты и всё, что на них висит ───────────────────────────────
    #
    # Видно их человеку: `/admin/project` — список проектов установки, и тестовые
    # строки стоят там вперемешку с настоящими.
    #
    # ⚠⚠ **Порядок обязателен: дети раньше проекта.** Внешнего ключа к `project` у
    # этих таблиц нет (единственный — `project_team`, и тот с каскадом), так что
    # снесённый первым проект не уносит их, а обращает в сирот: `project_id`
    # указывает в пустоту, а своего признака в строке нет — тестовые задачи зовутся
    # «родитель» и «первая». Так на этой базе осталась 21 задача и 30 фаз.
    ('project_task', f"`project_id` IN ({PROJECT_IDS})"),
    ('project_planning_phase', f"`project_id` IN ({PROJECT_IDS})"),
    ('project_planning_document', f"`project_id` IN ({PROJECT_IDS})"),
    ('project_task', f"`title` LIKE '{TITLE_LIKE}'"),
    ('project', f"`title` LIKE '{TITLE_LIKE}'"),

    # ⚠ Сироты прошлых прогонов: задача есть, проекта под ней уже нет. Своего
    # признака у них не осталось, поэтому отбор идёт по разрыву связи, а не по имени.
    #
    # ⚠⚠ Это единственное правило, которое **не смотрит на приставку**, — значит
    # единственное, которое может задеть рабочую строку. Задеть, впрочем, нечего:
    # удаление проекта из панели сносит его задачи само (`project_planning_delete`),
    # так что осиротеть задача может только от прерванного теста или правки базы
    # руками. Сухая выдача перед `--apply` — та самая проверка, ради которой она есть.
    ('project_task',
     "`project_id` IS NOT NULL AND `project_id` <> 0"
     " AND `project_id` NOT IN (SELECT `id` FROM (SELECT `id` FROM `project`) p)"),
)

# ⚠ Чего эта уборка **не делает** — не сносит workflow, агентов и роли целиком,
# даже мёртвых. Такое удаление — разовое решение человека, посмотревшего, что
# именно умерло и почему; скрипт, сносящий workflow по расписанию, однажды
# унесёт тот, которым просто давно не пользовались.
#
# Пример из этой же базы: workflow `test` (id 4) не зовёт никто, агентов на нём
# нет, прогонов за всё время ноль. Мёртв — а решать, сносить ли, всё равно
# человеку.


def mysql(sql: str) -> str:
    """Выполняет SQL в рабочей базе. Пароль — из окружения контейнера."""
    out = subprocess.run(
        ['docker', 'exec', '-i', MYSQL_CONTAINER, 'mysql', '-N', '-B',
         '--default-character-set=utf8mb4', '-u', 'root', '-ppassword', MYSQL_DB],
        input=sql, capture_output=True, text=True)

    if out.returncode:
        raise RuntimeError(f'MySQL не ответил: {out.stderr[:200]}')

    return out.stdout.strip()


def qdrant(path: str, body: dict = None) -> dict:
    """Запрос к Qdrant. `body` есть — POST, нет — GET."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f'{QDRANT_URL}{path}', data=data,
        headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req, timeout=30) as answer:
            return json.loads(answer.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f'Qdrant не ответил: {e}')


def sweep_mysql(apply: bool) -> int:
    """Считает и (если велено) сносит тестовые строки MySQL."""
    total = 0

    for table, where in RULES:
        n = int(mysql(f'SELECT COUNT(*) FROM `{table}` WHERE {where}') or 0)
        if not n:
            continue

        total += n
        print(f'  {table:<28} {n}')

        if apply:
            mysql(f'DELETE FROM `{table}` WHERE {where}')

    return total


def sweep_qdrant(apply: bool) -> int:
    """Считает и (если велено) сносит тестовые точки Qdrant.

    ⚠ **Отбираем перебором, а не фильтром Qdrant.** Фильтр по началу строки
    требует текстового индекса на поле; его на `document_id` нет, и запрос
    ответил бы либо ошибкой, либо — хуже — пустотой, и уборка «успешно» не
    удалила бы ничего.

    Точек в этих коллекциях сотни, перебор дёшев.
    """
    total = 0

    for name in COLLECTIONS:
        try:
            got = qdrant(f'/collections/{name}/points/scroll',
                         {'limit': 10_000, 'with_payload': True})
        except RuntimeError as e:
            print(f'  {name:<28} пропущена: {e}')
            continue

        # ⚠ Приставок несколько: нынешняя и унаследованные. `llm-facts-…` и
        # `llm-bio-…` — имена, которыми тесты звали собеседников до правила;
        # мусор под ними уже накоплен, и уборка обязана его видеть.
        ids = [point['id'] for point in got['result']['points']
               if str(point.get('payload', {}).get('document_id', ''))
               .startswith((MARK, 'llm-facts-', 'llm-bio-', 'llm-test-'))
               or QDRANT_DEBT.match(
                   str(point.get('payload', {}).get('document_id', '')))]

        if not ids:
            continue

        total += len(ids)
        print(f'  {name:<28} {len(ids)}')

        if apply:
            qdrant(f'/collections/{name}/points/delete?wait=true',
                   {'points': ids})

    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true',
                    help='удалить (без него — только показать)')
    args = ap.parse_args()

    print('MySQL:')
    rows = sweep_mysql(args.apply)
    print(f'  {"—" if not rows else "всего строк:":<28} {rows or "чисто"}')

    print('Qdrant:')
    points = sweep_qdrant(args.apply)
    print(f'  {"—" if not points else "всего точек:":<28} {points or "чисто"}')

    if not args.apply and (rows or points):
        print('\n⚠ Ничего не удалено. Снести — `./test_cleanup.py --apply`')

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, KeyboardInterrupt) as e:
        print(f'⚠ {e}', file=sys.stderr)
        sys.exit(1)
