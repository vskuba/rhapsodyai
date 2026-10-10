"""Случаи установки и их выключатель: что лежит в `tests_e2e/` и что гонять.

Две половины сходятся здесь. Файлы случаев читает общий каркас
(`py_modules/tests_e2e/tests_e2e_case.py`) — он про YAML и ничего не знает про
базу. Признак «включён» живёт в таблице `test_e2e_case` — он про установку и в
файл не уезжает.

⚠ Строки в таблице нет — случай **включён**. Заводит её только переключатель,
поэтому новый случай работает сразу, без строки и без миграции.

⚠⚠ Ключ — **имя файла**, а не название случая: название правят ради
формулировки, и привязка выключателя терялась бы молча.
"""

import os

from mysql_.mysql_ import mysql_get_db_async
from tests_e2e.tests_e2e_case import tests_e2e_case_list


async def e2e_case_list(folder: str) -> list:
    """Случаи каталога с проставленным признаком «включён».

    Args:
        folder: каталог с `*.yaml`.

    Returns:
        list: по словарю на случай — `file` (имя файла), `name`,
        `description`, `page`, `widths`, `areas`, `checks`, `enabled`.
        Порядок — по имени файла, как у каркаса.
    """
    cases = tests_e2e_case_list(folder)
    state = await e2e_case_state()

    out = []
    for case in cases:
        name = os.path.basename(case.get('file') or '')
        out.append({
            'file': name,
            'name': case['name'],
            'description': case['description'],
            'page': case['page'],
            'widths': case['widths'],
            'areas': len(case['areas']),
            'checks': len(case['checks']),
            'enabled': state.get(name, True),
        })
    return out


async def e2e_case_state() -> dict:
    """Что переключали: `имя файла` → `enabled`. Нет строки — нет и ключа."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT case_file, enabled FROM test_e2e_case')
        rows = await db.fetchall()
    return {str(dict(row)['case_file']): bool(dict(row)['enabled']) for row in rows}


async def e2e_case_enable(case_file: str, enabled: bool, name: str = '') -> bool:
    """Включить или выключить случай; вернуть новое состояние.

    Args:
        case_file: имя файла случая («workflow_trace_error_today.yaml»).
        enabled: True — гонять, False — пропускать.
        name: название на момент переключения, копией — чтобы в отчёте было
            видно, что именно выключено, если файл потом переименуют.

    ⚠ Запись идёт и при включении: отсутствие строки означает «включён», но
    строка со значением `1` отличает «включили обратно» от «не трогали» —
    по `updated_at` видно, когда это было.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO test_e2e_case (case_file, enabled, name)'
            ' VALUES (%s, %s, %s)'
            ' ON DUPLICATE KEY UPDATE enabled = VALUES(enabled), name = VALUES(name)',
            (str(case_file)[:190], 1 if enabled else 0, str(name or '')[:190]))
    return enabled


async def e2e_case_runnable(folder: str) -> tuple:
    """Случаи, которые надо гонять, и имена пропущенных.

    Returns:
        tuple: (`список случаев каркаса`, `список имён пропущенных`).
        Случаи — в том виде, в каком их отдаёт каркас: прогон работает с ними,
        а не с карточками для страницы.
    """
    cases = tests_e2e_case_list(folder)
    state = await e2e_case_state()

    run, skipped = [], []
    for case in cases:
        if state.get(os.path.basename(case.get('file') or ''), True):
            run.append(case)
        else:
            skipped.append(case['name'])
    return run, skipped
