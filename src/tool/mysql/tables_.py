import re

from mysql_.mysql_ import mysql_get_db_async


async def mysql_tables_find(substr: str) -> dict:
    """
    Ищет таблицы базы данных по вхождению подстроки в имя.
    Результат подходит для передачи в другие инструменты, например mysql_export_to_migration.
    Returns:
        A dictionary with the found database tables.
        tables_str (str): Имена найденных таблиц через запятую.
        tables_qty (int): Количество найденных таблиц.
    """
    clean = re.sub(r'[^A-Za-z0-9_]', '', str(substr or ''))
    if not clean:
        return {"tables_str": "", "tables_qty": 0}

    # Подчеркивания в паттерне — литеральные, а не wildcard LIKE
    escaped = clean.replace('_', '\\_')
    async with mysql_get_db_async() as db:
        await db.execute("SHOW TABLES LIKE %s", (f"%{escaped}%",))
        tables = sorted(list(row.values())[0] for row in await db.fetchall())

    return {"tables_str": ", ".join(tables), "tables_qty": len(tables)}
