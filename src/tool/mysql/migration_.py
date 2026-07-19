import os
import re

import pymysql

from logging_.logging_ import logger_info
from src.tool.mysql.export_ import _migration_file_ownership_fix, _next_migration_file, _sql_escape, \
    _table_primary_key_columns
from mysql_.mysql_ import mysql_get_db_async

# Таблицы, которые НИКОГДА не участвуют в сравнении/синке с продом - чисто
# динамические рантайм-данные (история переписки, игровые сессии, журналы
# выполнения workflow, метрики LLM, факты, извлеченные во время диалогов,
# UUID-сессии браузера/чата) и служебные таблицы yoyo. Аналог agent.dynamic=1
# у обычного экспорта, но на уровне целых таблиц - в этих таблицах КАЖДАЯ
# строка рантаймовая. Локальные сессии никак не относятся к продовским -
# переносить их между окружениями бессмысленно.
_RUNTIME_EXCLUDED_TABLES = {
    'agent_session', 'detective_case', 'agent_workflow_run', 'agent_workflow_run_step',
    'fact', 'llm_request', 'session',
    '_yoyo_migration', '_yoyo_log', '_yoyo_version', 'yoyo_lock',
}

# Таблицы, наполняемые ai_tool_sync() из самого кода (AST-скан src/tool/**) -
# на каждом окружении они пересобираются из своего же исходника при синке
# инструментов, поэтому переносить их СОДЕРЖИМОЕ между локалью и продом не
# нужно (и вредно: id тулов на проде могут не совпадать с локальными).
_TOOL_EXCLUDED_TABLES = {'tool', 'tool_group'}

_DATA_DIFF_EXCLUDED_TABLES = _RUNTIME_EXCLUDED_TABLES | _TOOL_EXCLUDED_TABLES


async def mysql_migration_prod_create(
        prod_host: str = 'host.docker.internal', prod_port: int = 3307,
        prod_user: str = 'developer', prod_password: str = 'password', prod_database: str = 'project'
) -> dict:
    """
    Создает новую миграцию для выката локальной разработки на прод - аналог
    "migration diff" в ORM (alembic autogenerate / Django makemigrations):
    сравнивает ТЕКУЩЕЕ состояние прода с локальным и генерирует разницу.

    1. Структура: для таблиц/колонок, которые есть локально, но отсутствуют на
       проде - генерирует CREATE TABLE / ALTER TABLE ADD COLUMN. Обратные
       расхождения (что-то есть на проде, но не локально) и смена типа
       существующей колонки НЕ трогает - только сообщает в review_needed,
       такое требует ручного решения (может быть осознанным отличием прода).
    2. Данные: по каждой не-рантаймовой и не tool-sync таблице (кроме
       agent_session, detective_case, agent_workflow_run*, fact, llm_request,
       служебных таблиц yoyo - это исключительно динамический рантайм, не
       seed; и кроме tool, tool_group - их наполняет ai_tool_sync() из кода на
       каждом окружении отдельно, переносить данные между средами не нужно)
       делает построчный diff по первичному ключу: строки, полностью
       совпадающие на проде и локально, в миграцию НЕ попадают. Для строк,
       измененных локально (ключ есть на обеих сторонах, но данные другие) -
       в файл попадают ОБЕ версии (сначала прод-версия для сравнения, затем
       новая локальная - upsert, локальная побеждает), чтобы можно было
       визуально увидеть, что именно меняется. Строки без пары на другой
       стороне показываются один раз (новые локально - upsert; только на
       проде - сохраняются как есть, например заведено вручную прямо там).
       Миграция получается точечной - только реально затронутые строки, а не
       вся таблица целиком.
    3. Все пишется в СЛЕДУЮЩИЙ свободный файл миграции (mysql_migration_next_file).
       Номер выбирается по ЛОКАЛЬНЫМ файлам - если предыдущий выкаченный файл с
       этим же номером уже удален локально (что и есть штатный процесс после
       успешного деплоя), номер переиспользуется. yoyo на проде иначе молча
       пропустил бы файл с уже отмеченным migration_id, даже не открывая его -
       поэтому ПЕРЕД генерацией эта функция сама удаляет отметку "применена"
       для этого номера из _yoyo_migration на проде: writing ничего вручную не
       требует, повторный вызов всегда создает применимую миграцию.

    Требует SSH-туннель к проду: `ssh -f -N rhapsody-prod-db` (см.
    ~/.ssh/config) пробрасывает MySQL прода на localhost:3307 - отдельным
    алиасом от rhapsody-prod, чтобы не требовать остановки локального стека
    (нужен ОДНОВРЕМЕННЫЙ доступ к обеим базам).
     - prod_host/prod_port/prod_user/prod_password/prod_database: параметры
       подключения к БД прода через туннель (по умолчанию соответствуют туннелю)
    Returns:
        dict: Словарь с результатом, содержащий:
            migration_file (str): путь к созданному файлу миграции (пустая строка при ошибке подключения).
            tables_qty (int): количество таблиц с расхождениями.
            rows_qty (int): суммарное количество затронутых строк (реально отличающихся).
            schema_changes (str): список примененных изменений структуры (CREATE/ALTER) или "нет".
            review_needed (str): расхождения, требующие ручного решения (пусто, если таких нет).
            report_str (str): текстовый отчет по данным (как у mysql_export_node_to_migration).
    """
    target_file = _next_migration_file()
    migration_id = os.path.basename(target_file)[:4]

    try:
        prod_conn = pymysql.connect(
            host=prod_host, port=prod_port, user=prod_user, password=prod_password,
            database=prod_database, charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
    except Exception as e:
        return {
            "migration_file": "", "tables_qty": 0, "rows_qty": 0,
            "schema_changes": "", "review_needed": "",
            "report_str": f"не удалось подключиться к проду ({prod_host}:{prod_port}): {e}. "
                           f"Проверьте туннель: ssh -f -N rhapsody-prod-db",
        }

    try:
        _yoyo_migration_unmark(prod_conn, migration_id)
        schema_lines, review_notes = await _schema_diff_generate(prod_conn)
        data_blocks, tables_qty, rows_qty = await _data_diff_generate(prod_conn)
    finally:
        prod_conn.close()

    content_lines = [
        "-- Синхронизация с продом (сгенерировано mysql_migration_prod_create).",
        "-- Структура: CREATE/ALTER для нового, что появилось локально. Данные: построчный",
        "-- diff по первичному ключу - только затронутые строки. Для измененных строк",
        "-- показаны обе версии (прод для сравнения, затем новая локальная - upsert).",
        "",
    ]
    if schema_lines:
        content_lines.extend(schema_lines)
        content_lines.append("")
    content_lines.extend(data_blocks)

    with open(target_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content_lines))
    _migration_file_ownership_fix(target_file)

    logger_info(f"📦 Создана prod-миграция {target_file}: {tables_qty} таблиц, {rows_qty} строк")

    return {
        "migration_file": target_file,
        "tables_qty": tables_qty,
        "rows_qty": rows_qty,
        "schema_changes": '; '.join(re.sub(r'\s+', ' ', s).strip() for s in schema_lines if s.strip()) or 'нет изменений структуры',
        "review_needed": '; '.join(review_notes) or '',
        "report_str": f"файл {target_file} создан",
    }


def _yoyo_migration_unmark(prod_conn, migration_id: str) -> None:
    """Снимает с прода отметку "миграция применена" (yoyo хранит примененные
    миграции в служебной таблице _yoyo_migration по migration_id - имени
    файла без пути и расширения, например '0005'). yoyo пропускает файл с уже
    отмеченным migration_id молча, даже не открывая его - поэтому перед
    генерацией файла с этим номером снимаем возможную старую отметку заранее,
    чтобы новый файл с тем же номером гарантированно применился на проде."""
    with prod_conn.cursor() as cur:
        cur.execute("DELETE FROM `_yoyo_migration` WHERE `migration_id` = %s", (migration_id,))
        if cur.rowcount:
            logger_info(f"🗑️ Прод-миграция {migration_id}: старая отметка применения снята")
    prod_conn.commit()


async def _schema_diff_generate(prod_conn) -> tuple:
    """Сравнивает структуру таблиц (локально vs прод), возвращает
    (список строк CREATE/ALTER TABLE для отсутствующего на проде,
    список пометок для ручного review - обратные расхождения/смена типа)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        )
        local_tables = {r['TABLE_NAME'] for r in await db.fetchall()} - _RUNTIME_EXCLUDED_TABLES

    with prod_conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        )
        prod_tables = {r['TABLE_NAME'] for r in cur.fetchall()} - _RUNTIME_EXCLUDED_TABLES

    schema_lines = []
    review_notes = []

    # Таблицы, которых нет на проде - переносим DDL как есть (CREATE TABLE IF NOT EXISTS)
    for table in sorted(local_tables - prod_tables):
        async with mysql_get_db_async() as db:
            await db.execute(f"SHOW CREATE TABLE `{table}`")
            ddl = (await db.fetchone())['Create Table']
        ddl = ddl.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1)
        ddl = re.sub(r'\s*AUTO_INCREMENT=\d+', '', ddl)
        schema_lines.append(ddl + ';')
        schema_lines.append('')

    # Таблиц, которые есть только на проде - не трогаем, только сообщаем
    for table in sorted(prod_tables - local_tables):
        review_notes.append(f"таблица '{table}' есть на проде, но не локально - не удаляется, проверьте вручную")

    # Общие таблицы: сравниваем колонки
    for table in sorted(local_tables & prod_tables):
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                (table,)
            )
            local_columns = {r['COLUMN_NAME']: r for r in await db.fetchall()}

        with prod_conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                (table,)
            )
            prod_columns = {r['COLUMN_NAME']: r for r in cur.fetchall()}

        for col_name, col_row in local_columns.items():
            if col_name not in prod_columns:
                schema_lines.append(f"ALTER TABLE `{table}` ADD COLUMN {_column_definition_sql(col_name, col_row)};")
            elif _column_type_normalize(col_row['COLUMN_TYPE']) != _column_type_normalize(prod_columns[col_name]['COLUMN_TYPE']):
                review_notes.append(
                    f"'{table}.{col_name}': тип отличается (локально {col_row['COLUMN_TYPE']}, "
                    f"на проде {prod_columns[col_name]['COLUMN_TYPE']}) - не изменяется автоматически"
                )

        for col_name in prod_columns:
            if col_name not in local_columns:
                review_notes.append(
                    f"'{table}.{col_name}' есть на проде, но не локально - не удаляется, проверьте вручную"
                )

    return schema_lines, review_notes


def _column_type_normalize(column_type: str) -> str:
    """Убирает display width у целочисленных типов (int(11) -> int) - MySQL
    8.0 больше не показывает его в information_schema, хотя хранение то же
    самое, что в 5.7. Без нормализации локальная (5.7) и прод (8.0) база
    выглядели бы 'разными' по каждой INT-колонке, хотя реальной разницы нет."""
    return re.sub(r'\b(tinyint|smallint|mediumint|int|bigint)\(\d+\)', r'\1', column_type)


async def _data_diff_generate(prod_conn) -> tuple:
    """Для каждой не-рантаймовой и не tool-sync таблицы - построчный diff по
    первичному ключу: строки, полностью совпадающие на проде и локально,
    пропускаются - в миграцию попадают только реально затронутые. Для строк,
    измененных локально (ключ есть на обеих сторонах, но данные отличаются) -
    показывает ОБЕ версии (сначала текущую прод-версию, затем новую локальную),
    чтобы можно было визуально сравнить, что именно меняется - не только
    точечный список задетых строк, но и видимый до/после. Строки, которых нет
    на одной из сторон, показываются один раз (новые локально - upsert;
    только на проде - сохраняются как есть). Таблицы без первичного ключа
    сравниваются и мигрируют целиком (построчное сопоставление без ключа
    ненадежно). Возвращает (список строк SQL-блоков, количество таблиц с
    расхождениями, суммарное количество затронутых строк)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        )
        tables = sorted({r['TABLE_NAME'] for r in await db.fetchall()} - _DATA_DIFF_EXCLUDED_TABLES)

    blocks = []
    tables_qty = 0
    rows_qty = 0

    for table in tables:
        async with mysql_get_db_async() as db:
            await db.execute(f"SHOW COLUMNS FROM `{table}`")
            columns = [c['Field'] for c in await db.fetchall()]
            pk_columns = await _table_primary_key_columns(db, table)

        row_filter = "WHERE `dynamic` = 0" if 'dynamic' in columns else ""
        order_by = '`' + pk_columns[0] + '`' if pk_columns else ', '.join(f'`{c}`' for c in columns)

        with prod_conn.cursor() as cur:
            cur.execute(f"SELECT * FROM `{table}` {row_filter} ORDER BY {order_by}")
            prod_rows = cur.fetchall()

        async with mysql_get_db_async() as db:
            await db.execute(f"SELECT * FROM `{table}` {row_filter} ORDER BY {order_by}")
            local_rows = await db.fetchall()

        if not pk_columns:
            # Без первичного ключа построчное сопоставление ненадежно -
            # сравниваем и (при расхождении) мигрируем таблицу целиком
            if _rows_as_sql_text(columns, prod_rows) == _rows_as_sql_text(columns, local_rows):
                continue
            prod_only_rows, changed_prod_rows, new_local_rows = [], prod_rows, local_rows
            affected_keys_qty = len(prod_rows) if not local_rows else max(len(prod_rows), len(local_rows))
        else:
            prod_by_key = {tuple(row[c] for c in pk_columns): row for row in prod_rows}
            local_by_key = {tuple(row[c] for c in pk_columns): row for row in local_rows}

            # Есть только на проде - сохраняем как есть (например, заведено вручную)
            prod_only_rows = [row for key, row in prod_by_key.items() if key not in local_by_key]
            # Есть на обеих сторонах, но данные отличаются - нужны ОБЕ версии для сравнения
            changed_keys = [
                key for key, row in local_by_key.items()
                if key in prod_by_key and _row_sql_text(columns, row) != _row_sql_text(columns, prod_by_key[key])
            ]
            changed_prod_rows = [prod_by_key[key] for key in changed_keys]
            # Новые локально (ключа еще нет на проде) - сравнивать не с чем, только upsert
            new_only_local_rows = [row for key, row in local_by_key.items() if key not in prod_by_key]
            new_local_rows = [local_by_key[key] for key in changed_keys] + new_only_local_rows
            affected_keys_qty = len(prod_only_rows) + len(changed_keys) + len(new_only_local_rows)

        if not prod_only_rows and not changed_prod_rows and not new_local_rows:
            continue

        if prod_only_rows:
            blocks.append(_upsert_block_build(table, columns, prod_only_rows, pk_columns, '-- только на проде (сохраняем)'))
            blocks.append('')
        if changed_prod_rows:
            blocks.append(_upsert_block_build(
                table, columns, changed_prod_rows, pk_columns, '-- прод: текущее значение измененных строк (для сравнения)'
            ))
            blocks.append('')
        if new_local_rows:
            blocks.append(_upsert_block_build(table, columns, new_local_rows, pk_columns, '-- локально: новое/измененное значение'))
            blocks.append('')

        tables_qty += 1
        rows_qty += affected_keys_qty

    return blocks, tables_qty, rows_qty


def _row_sql_text(columns: list, row: dict) -> tuple:
    """Строковое SQL-представление ОДНОЙ строки (кортеж экранированных значений
    по колонкам) - для сравнения "совпадают ли данные прода и локали по сути",
    не по внутреннему Python-типу драйвера (pymysql/aiomysql могут по-разному
    типизировать одно и то же значение - Decimal/float, datetime/str)."""
    return tuple(_sql_escape(row[c]) for c in columns)


def _rows_as_sql_text(columns: list, rows: list) -> list:
    """Строковое SQL-представление набора строк (список кортежей экранированных
    значений по колонкам, в порядке строк) - см. _row_sql_text."""
    return [_row_sql_text(columns, row) for row in rows]


def _column_definition_sql(col_name: str, col_row: dict) -> str:
    """Строит фрагмент определения колонки для ALTER TABLE ADD COLUMN
    из строки information_schema.COLUMNS."""
    parts = [f"`{col_name}`", col_row['COLUMN_TYPE']]
    parts.append('NULL' if col_row['IS_NULLABLE'] == 'YES' else 'NOT NULL')
    if col_row['COLUMN_DEFAULT'] is not None:
        default = col_row['COLUMN_DEFAULT']
        if str(default).upper() in ('CURRENT_TIMESTAMP', 'CURRENT_TIMESTAMP()'):
            parts.append(f"DEFAULT {default}")
        else:
            parts.append(f"DEFAULT {_sql_escape(default)}")
    if col_row.get('EXTRA'):
        parts.append(col_row['EXTRA'].upper())
    if col_row.get('COLUMN_COMMENT'):
        parts.append(f"COMMENT {_sql_escape(col_row['COLUMN_COMMENT'])}")
    return ' '.join(parts)


def _upsert_block_build(table: str, columns: list, rows: list, pk_columns: list, comment: str) -> str:
    """Строит один INSERT ... ON DUPLICATE KEY UPDATE блок для готового
    набора строк (общая с export_.py логика построения upsert-а)."""
    cols_sql = ', '.join(f'`{c}`' for c in columns)
    lines = [comment, f"INSERT INTO `{table}` ({cols_sql}) VALUES"]
    for idx, row in enumerate(rows):
        values = ', '.join(_sql_escape(row[c]) for c in columns)
        lines.append(f"({values})" + (',' if idx < len(rows) - 1 else ''))
    update_columns = [c for c in columns if c not in pk_columns] or pk_columns[:1]
    update_clause = ', '.join(f'`{c}` = VALUES(`{c}`)' for c in update_columns)
    lines.append(f"ON DUPLICATE KEY UPDATE {update_clause};")
    return '\n'.join(lines)
