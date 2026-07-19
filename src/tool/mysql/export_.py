import os
import re

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Node-scoped таблицы для mysql_export_node_to_migration: как связать строки
# таблицы с node_id при экспорте ОДНОГО подпроекта отдельно от остальных.
# agent_workflow/agent несут node_id напрямую; шаги и переменные - только
# через workflow_id (agent_workflow_variable к своим workflow привязана
# исключительно через join-таблицу agent_workflow_variable_workflow).
# agent: dynamic=0 исключает агентов, созданных ЖИВЫМ workflow во время игры
# (девушки в dating, подозреваемые/сержант в detective) - иначе экспорт
# запекал бы реальные игровые данные игроков в seed-миграцию подпроекта.
_NODE_SCOPED_TABLE_QUERIES = {
    'agent_workflow': "SELECT * FROM `agent_workflow` WHERE `node_id` = %s ORDER BY `id`",
    'agent': "SELECT * FROM `agent` WHERE `node_id` = %s AND `dynamic` = 0 ORDER BY `id`",
    'agent_workflow_step': (
        "SELECT s.* FROM `agent_workflow_step` s "
        "JOIN `agent_workflow` w ON w.id = s.workflow_id "
        "WHERE w.node_id = %s ORDER BY s.id"
    ),
    'agent_workflow_variable_workflow': (
        "SELECT vw.* FROM `agent_workflow_variable_workflow` vw "
        "JOIN `agent_workflow` w ON w.id = vw.workflow_id "
        "WHERE w.node_id = %s ORDER BY vw.variable_id, vw.workflow_id"
    ),
    'agent_workflow_variable': (
        "SELECT DISTINCT v.* FROM `agent_workflow_variable` v "
        "JOIN `agent_workflow_variable_workflow` vw ON vw.variable_id = v.id "
        "JOIN `agent_workflow` w ON w.id = vw.workflow_id "
        "WHERE w.node_id = %s ORDER BY v.id"
    ),
}


async def mysql_export_to_migration(tables: str, migration_file: str = 'migrations/0002.sql') -> dict:
    """
    Экспортирует указанные таблицы из базы данных в файл миграции ЦЕЛИКОМ (без
    фильтрации по ноде/подпроекту) - находит соответствующие INSERT-блоки и
    заменяет их актуальными данными. Порядок блоков в файле сохраняется (важно
    для FK). Для таблиц, общих для всех подпроектов (node, role, user, tool и
    т.п.). Для экспорта данных ОДНОГО подпроекта используйте
    mysql_export_node_to_migration - иначе экспорт смешает строки всех нод
    в одном файле.
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

    return _migration_file_splice(migration_file, exports, skipped)


async def mysql_export_node_to_migration(node_id: int, migration_file: str = '') -> dict:
    """
    Экспортирует данные ОДНОЙ НОДЫ (подпроекта) - её workflow, шаги, переменные
    и агентов - в собственный файл миграции подпроекта, без смешивания с
    данными других нод. В отличие от mysql_export_to_migration (весь стол
    целиком), каждая таблица здесь фильтруется по принадлежности к ноде:
    agent_workflow/agent - по node_id напрямую, шаги/переменные - через
    workflow_id. Если для таблицы в файле еще нет INSERT-блока (новый
    подпроект/файл миграции) - блок дописывается в конец файла.
     - node_id: ID ноды-подпроекта (см. таблицу node)
     - migration_file: путь к файлу миграции; если не передан - берется
       из node.migration_file (задается на странице Node в админке)
    Returns:
        dict: отчет экспорта - tables_qty, rows_qty, report_str (как у mysql_export_to_migration).
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT `name`, `migration_file` FROM `node` WHERE `id` = %s", (node_id,))
        node_row = await db.fetchone()

    if not node_row:
        return {"tables_qty": 0, "rows_qty": 0, "report_str": f"нода {node_id} не найдена"}

    target_file = (migration_file or node_row.get('migration_file') or '').strip()
    if not target_file:
        return {
            "tables_qty": 0, "rows_qty": 0,
            "report_str": f"для ноды '{node_row['name']}' не задан migration_file (и не передан явно вторым аргументом)"
        }

    exports = {}
    skipped = []
    async with mysql_get_db_async() as db:
        for table, query in _NODE_SCOPED_TABLE_QUERIES.items():
            await db.execute(f"SHOW COLUMNS FROM `{table}`")
            columns = [c['Field'] for c in await db.fetchall()]

            await db.execute(query, (node_id,))
            rows = await db.fetchall()
            if rows:
                exports[table] = (columns, rows)
            else:
                skipped.append(f"{table} (нет строк для ноды '{node_row['name']}')")

    return _migration_file_splice(target_file, exports, skipped)


def _migration_file_splice(migration_file: str, exports: dict, skipped: list) -> dict:
    """Общая логика замены/добавления INSERT-блоков в файле миграции.
    Используется mysql_export_to_migration и mysql_export_node_to_migration.
    Если для таблицы в файле уже есть INSERT-блок - заменяет его. Если блока
    еще нет (например, свежий пустой файл миграции нового подпроекта) -
    дописывает новый блок в конец файла, а не пропускает таблицу."""
    path = os.path.abspath(migration_file)
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')

    replaced = []
    rows_total = 0

    for table, (columns, rows) in exports.items():
        if not rows:
            skipped.append(f"{table} (таблица пуста, блок оставлен как есть)")
            continue

        cols_sql = ', '.join(f'`{c}`' for c in columns)
        block = [f"INSERT INTO `{table}` ({cols_sql}) VALUES"]
        for idx, row in enumerate(rows):
            values = ', '.join(_sql_escape(row[c]) for c in columns)
            block.append(f"({values})" + (',' if idx < len(rows) - 1 else ';'))

        header_prefix = f"INSERT INTO `{table}` ("
        start = next((i for i, line in enumerate(lines) if line.startswith(header_prefix)), None)

        if start is None:
            # Блока еще нет в файле - дописываем в конец, а не пропускаем
            if lines and lines[-1].strip():
                lines.append('')
            lines.extend(block)
            replaced.append(f"{table} (новый блок)")
            rows_total += len(rows)
            logger_info(f"📦 Экспорт {table}: {len(rows)} строк -> {migration_file} (новый INSERT-блок)")
            continue

        end = start
        while end < len(lines) and not re.search(r';\s*(?:--.*)?$', lines[end]):
            end += 1

        # Терминатор не найден: пропускаем таблицу, иначе замена снесла бы файл до конца
        if end >= len(lines):
            skipped.append(f"{table} (не найден конец INSERT-блока ';')")
            continue

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
