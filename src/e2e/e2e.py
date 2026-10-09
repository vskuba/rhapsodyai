"""Результаты E2E-проверок интерфейса: запись прогона и чтение для страницы.

Таблица `test_e2e` (миграция `20261009124416_test_e2e.sql`) — строка на
**тест × ширину**: один случай даёт столько строк, сколько у него ширин, потому
что сетка, собранная на широкой, ломается на мобильной, и это разные вердикты.

Что здесь есть и чего нет. Здесь — предмет этой установки: таблица, отбор,
сборка прогона для страницы, чистка по числу прогонов. Сам прогон (копия
страницы, кадр, зонд, правила, рамки областей) живёт в общем слое
`py_modules/tests_e2e/` — он одинаков у всех проектов, и во все проекты едет
submodule-ом.

⚠ Имя и описание случая лежат в строке **копией** из YAML, а не ссылкой на файл.
Вчерашний прогон обязан читаться вчерашними словами, даже если случай с тех пор
переписали или удалили, — то же правило и по той же причине, что `object_name`
в `agent_workflow_history`.

Время в строках — UTC, как всё в проекте: в пояс настройки `timezone` переводит
страница.
"""

import json
import uuid

from mysql_.mysql_ import mysql_get_db_async

# Сколько прогонов держим. Прогон суточный, тридцать — это месяц истории:
# хватает, чтобы увидеть, когда страница поехала, и не копить кадры годами.
# ⚠ Срок считается ПРОГОНАМИ, а не днями: при ручных запусках кнопкой день
# даёт несколько прогонов, и «храним 30 дней» означало бы разное число строк.
E2E_KEEP_RUNS = 30

# Потолок строк в одном ответе: случаев у установки десятки, ширин три.
E2E_ROWS_MAX = 500


async def e2e_run_list(limit: int = 30) -> list:
    """Список прогонов — свежий сверху, по строке на прогон.

    Args:
        limit: сколько прогонов вернуть.

    Returns:
        list: `run_uuid`, `started_at`, `tests`, `failed`, `errored`, `status`.
        `status` прогона — худший из его строк: `error` важнее `fail`, `fail`
        важнее `ok`.
    """
    limit = max(1, min(int(limit or 30), 200))
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT run_uuid,'
            '       MIN(created_at)                                AS started_at,'
            '       COUNT(*)                                       AS tests,'
            '       SUM(status = %s)                               AS failed,'
            '       SUM(status = %s)                               AS errored'
            '  FROM test_e2e'
            ' GROUP BY run_uuid'
            ' ORDER BY started_at DESC'
            ' LIMIT %s',
            ('fail', 'error', limit))
        rows = await db.fetchall()

    return [_e2e_run_card(dict(row)) for row in rows]


async def e2e_run_rows(run_uuid: str = '') -> dict:
    """Один прогон целиком: его строки с разобранными областями.

    Args:
        run_uuid: какой прогон. Пусто — самый свежий.

    Returns:
        dict: `run` — карточка прогона (как в `e2e_run_list`), `rows` — строки
        теста с разобранным `areas`. Прогонов нет вовсе — `run` пустой, `rows`
        пустой список.
    """
    async with mysql_get_db_async() as db:
        if not run_uuid:
            await db.execute('SELECT run_uuid FROM test_e2e'
                             ' ORDER BY created_at DESC, id DESC LIMIT 1')
            run_uuid = str((await db.fetchone() or {}).get('run_uuid') or '')
        if not run_uuid:
            return {'run': {}, 'rows': []}

        await db.execute(
            'SELECT id, run_uuid, name, description, page, width, status,'
            '       areas_total, areas_failed, area_json, shot_path,'
            '       shot_plain_path, console_json, error, duration_ms, created_at'
            '  FROM test_e2e'
            ' WHERE run_uuid = %s'
            # Порядок показа: красное первым — на странице его и ищут. Дальше по
            # имени случая и по ширине, чтобы три ширины одного теста шли подряд.
            ' ORDER BY FIELD(status, %s, %s, %s), name, width'
            ' LIMIT %s',
            (run_uuid, 'error', 'fail', 'ok', E2E_ROWS_MAX))
        rows = await db.fetchall()

    cards = [_e2e_test_row(dict(row)) for row in rows]
    return {'run': _e2e_run_card_from_rows(run_uuid, cards), 'rows': cards}


async def e2e_row_get(row_id: int) -> dict:
    """Одна строка теста — для показа кадра и списка областей.

    Returns:
        dict: строка с разобранными `areas` и `console`; пустой dict, если нет.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, run_uuid, name, description, page, width, status,'
            '       areas_total, areas_failed, area_json, shot_path,'
            '       shot_plain_path, console_json, error, duration_ms, created_at'
            '  FROM test_e2e WHERE id = %s', (int(row_id),))
        row = await db.fetchone()

    return _e2e_test_row(dict(row)) if row else {}


async def e2e_row_write(run_uuid: str, result: dict) -> int:
    """Положить результат одного теста (случай × ширина) в таблицу.

    Args:
        run_uuid: метка прогона; все строки одного прогона несут одну.
        result: что вернул прогон случая — ключи те же, что у столбцов:
            `name`, `description`, `page`, `width`, `status`, `areas` (список),
            `shot_path`, `shot_plain_path`, `console`, `error`, `duration_ms`.

    Returns:
        int: номер записанной строки.
    """
    areas = list(result.get('areas') or [])
    failed = sum(1 for area in areas if area.get('status') != 'ok')

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO test_e2e (run_uuid, name, description, page, width,'
            '                      status, areas_total, areas_failed, area_json,'
            '                      shot_path, shot_plain_path, console_json,'
            '                      error, duration_ms)'
            ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (run_uuid,
             str(result.get('name') or '')[:190],
             result.get('description') or None,
             str(result.get('page') or '')[:190],
             int(result.get('width') or 0),
             str(result.get('status') or 'error'),
             len(areas), failed,
             json.dumps(areas, ensure_ascii=False),
             str(result.get('shot_path') or '')[:255],
             str(result.get('shot_plain_path') or '')[:255],
             json.dumps(result.get('console') or [], ensure_ascii=False),
             result.get('error') or None,
             int(result.get('duration_ms') or 0)))
        return int(db.lastrowid or 0)


def e2e_run_uuid() -> str:
    """Метка нового прогона."""
    return str(uuid.uuid4())


async def e2e_trim(keep: int = E2E_KEEP_RUNS) -> int:
    """Убрать прогоны старше `keep`-го по счёту; вернуть число снесённых строк.

    ⚠ Файлы кадров этим не трогаются: их сносит тот, кто их писал
    (`e2e_shot.py`), — иначе удаление строки оставляло бы каталог, а удаление
    каталога оставляло бы строку.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT run_uuid FROM test_e2e'
            ' GROUP BY run_uuid ORDER BY MIN(created_at) DESC'
            ' LIMIT %s OFFSET %s', (1000, max(1, int(keep))))
        stale = [str(dict(row)['run_uuid']) for row in await db.fetchall()]
        if not stale:
            return 0

        marks = ', '.join(['%s'] * len(stale))
        await db.execute(f'DELETE FROM test_e2e WHERE run_uuid IN ({marks})',
                         stale)
        return int(db.rowcount or 0)


def _e2e_run_card(row: dict) -> dict:
    """Строка `GROUP BY` → карточка прогона для списка."""
    failed = int(row.get('failed') or 0)
    errored = int(row.get('errored') or 0)
    return {
        'run_uuid': row.get('run_uuid'),
        'started_at': row.get('started_at'),
        'tests': int(row.get('tests') or 0),
        'failed': failed,
        'errored': errored,
        'status': 'error' if errored else ('fail' if failed else 'ok'),
    }


def _e2e_run_card_from_rows(run_uuid: str, cards: list) -> dict:
    """Та же карточка, посчитанная по уже прочитанным строкам: второй запрос
    к базе ради трёх чисел не нужен."""
    failed = sum(1 for card in cards if card['status'] == 'fail')
    errored = sum(1 for card in cards if card['status'] == 'error')
    return {
        'run_uuid': run_uuid,
        'started_at': min((card['created_at'] for card in cards), default=None),
        'tests': len(cards),
        'failed': failed,
        'errored': errored,
        'status': 'error' if errored else ('fail' if failed else 'ok'),
    }


def _e2e_test_row(row: dict) -> dict:
    """Строка таблицы → то, что читает страница: JSON разобран, пути — ссылками."""
    row['areas'] = _e2e_json_load(row.pop('area_json', None), [])
    row['console'] = _e2e_json_load(row.pop('console_json', None), [])
    row['shot_url'] = f'/api/e2e/shot/{row["id"]}' if row.get('shot_path') else ''
    row['shot_plain_url'] = (f'/api/e2e/shot/{row["id"]}?plain=1'
                             if row.get('shot_plain_path') else '')
    return row


def _e2e_json_load(value, default):
    """JSON из колонки: драйвер отдаёт его то строкой, то уже разобранным —
    зависит от версии MySQL. Битое значение не роняет страницу: там результат
    теста, а не её устройство."""
    if value in (None, ''):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
