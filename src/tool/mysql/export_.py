import os
import re

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async


async def mysql_export_to_migration(tables: str, migration_file: str = 'migrations/0002.sql') -> dict:
    """
    Экспортирует указанные таблицы из базы данных в файл миграции: находит
    соответствующие INSERT-блоки и заменяет их актуальными данными. Порядок блоков
    в файле сохраняется (важно для FK).
    tables — имена таблиц через запятую (например: 'agent_workflow, agent_workflow_step');
    migration_file — путь к файлу миграции относительно корня проекта.
    Returns:
        A dictionary with the export report.
        tables_qty (int): Количество экспортированных таблиц.
        rows_qty (int): Суммарное количество экспортированных строк.
        report_str (str): Отчет: обновленные таблицы и причины пропусков.
    """
    table_names = [t.strip() for t in str(tables or '').split(',') if t.strip()]
    if not table_names:
        return {"tables_qty": 0, "rows_qty": 0, "report_str": "не переданы имена таблиц"}

    # Имена таблиц попадают в SQL напрямую — разрешаем только безопасные идентификаторы
    for table in table_names:
        if not re.fullmatch(r'[A-Za-z0-9_]+', table):
            raise ValueError(f"Недопустимое имя таблицы: '{table}'")

    exports = {}
    skipped = []
    async with mysql_get_db_async() as db:
        for table in table_names:
            # Существование таблицы: имя с литеральными подчеркиваниями
            await db.execute("SHOW TABLES LIKE %s", (table.replace('_', '\\_'),))
            if not await db.fetchall():
                skipped.append(f"{table} (нет в БД)")
                continue

            await db.execute(f"SHOW COLUMNS FROM `{table}`")
            columns = [c['Field'] for c in await db.fetchall()]

            # Детерминированный порядок строк: по id, для связок — по всем колонкам
            order_by = '`id`' if 'id' in columns else ', '.join(f'`{c}`' for c in columns)
            await db.execute(f"SELECT * FROM `{table}` ORDER BY {order_by}")
            exports[table] = (columns, await db.fetchall())

    path = os.path.abspath(migration_file)
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')

    replaced = []
    rows_total = 0

    for table, (columns, rows) in exports.items():
        header_prefix = f"INSERT INTO `{table}` ("
        start = next((i for i, line in enumerate(lines) if line.startswith(header_prefix)), None)

        if start is None:
            skipped.append(f"{table} (нет INSERT-блока в файле)")
            continue
        if not rows:
            skipped.append(f"{table} (таблица пуста, блок оставлен как есть)")
            continue

        end = start
        while end < len(lines) and not re.search(r';\s*(?:--.*)?$', lines[end]):
            end += 1

        # Терминатор не найден: пропускаем таблицу, иначе замена снесла бы файл до конца
        if end >= len(lines):
            skipped.append(f"{table} (не найден конец INSERT-блока ';')")
            continue

        cols_sql = ', '.join(f'`{c}`' for c in columns)
        block = [f"INSERT INTO `{table}` ({cols_sql}) VALUES"]
        for idx, row in enumerate(rows):
            values = ', '.join(_sql_escape(row[c]) for c in columns)
            block.append(f"({values})" + (',' if idx < len(rows) - 1 else ';'))

        lines[start:end + 1] = block
        replaced.append(table)
        rows_total += len(rows)
        logger_info(f"📦 Экспорт {table}: {len(rows)} строк -> {migration_file}")

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    report = ', '.join(replaced) or 'ничего'
    if skipped:
        report += ' | пропущено: ' + '; '.join(skipped)

    return {
        "tables_qty": len(replaced),
        "rows_qty": rows_total,
        "report_str": report,
    }


def _sql_escape(value) -> str:
    """Экранирует значение для SQL-литерала MySQL.
    Порядок важен: сначала backslash, затем остальные спецсимволы."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    text = text.replace('\\', '\\\\')
    text = text.replace("'", "\\'")
    text = text.replace('\0', '\\0')
    text = text.replace('\n', '\\n')
    text = text.replace('\r', '\\r')
    text = text.replace('\t', '\\t')
    return f"'{text}'"
