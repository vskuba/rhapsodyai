import re

from mysql_.mysql_ import mysql_get_db_async


async def mysql_tables_find(substrs: list) -> dict:
    """
    Ищет таблицы базы данных по вхождению подстрок в имя (массив подстрок,
    например из text_split). Одиночная строка вместо массива тоже принимается.
    Результат объединяется без дублей и подходит для передачи в другие
    инструменты, например mysql_export_to_migration.
    Returns:
        A dictionary with the found database tables.
        tables_str (str): Имена найденных таблиц через запятую.
        tables_qty (int): Количество найденных таблиц.
    """
    if isinstance(substrs, str):
        substrs = [substrs]

    tables = set()
    async with mysql_get_db_async() as db:
        for substr in substrs or []:
            clean = re.sub(r'[^A-Za-z0-9_]', '', str(substr or ''))
            if not clean:
                continue

            # Подчеркивания в паттерне — литеральные, а не wildcard LIKE
            escaped = clean.replace('_', '\\_')
            await db.execute("SHOW TABLES LIKE %s", (f"%{escaped}%",))
            tables.update(list(row.values())[0] for row in await db.fetchall())

    tables = sorted(tables)
    return {"tables_str": ", ".join(tables), "tables_qty": len(tables)}
