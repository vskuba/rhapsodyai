import re

from mysql_.mysql_ import mysql_get_db_async


async def mysql_tables_find(tables: list) -> dict:
    """
    Проверяет существование таблиц базы данных по точным именам (массив имен,
    например из text_split). Одиночная строка вместо массива тоже принимается.
    Результат без дублей и подходит для передачи в другие инструменты,
    например mysql_export_to_migration.
    Returns:
        A dictionary with the found database tables.
        tables_str (str): Имена найденных таблиц через запятую.
        tables_qty (int): Количество найденных таблиц.
    """
    if isinstance(tables, str):
        tables = [tables]

    found = set()
    async with mysql_get_db_async() as db:
        for table in tables or []:
            clean = re.sub(r'[^A-Za-z0-9_]', '', str(table or ''))
            if not clean:
                continue

            # Точное имя: без % по краям, подчеркивания — литеральные, а не wildcard LIKE
            await db.execute("SHOW TABLES LIKE %s", (clean.replace('_', '\\_'),))
            found.update(list(row.values())[0] for row in await db.fetchall())

    found = sorted(found)
    return {"tables_str": ", ".join(found), "tables_qty": len(found)}
