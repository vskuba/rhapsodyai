import re

from py_modules.mysql_.mysql_ import mysql_get_db_async

# Имена таблиц/колонок приходят из metadata шагов workflow — в SQL попадают
# только валидные идентификаторы, значения передаются параметрами
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


async def mysql_find_by(table_name: str, criteria: dict, limit: int = 100) -> list:
    """
    Универсальный поиск записей в таблице по критериям равенства.
    criteria — словарь {колонка: значение}; значение-список превращается в IN (...),
    None — в IS NULL, пустой словарь возвращает все записи (не более limit).
    Returns:
        Список словарей-записей таблицы (колонка: значение).
    """
    where_sql, params = _where_build(table_name, criteria)

    async with mysql_get_db_async() as db:
        await db.execute(
            f'SELECT * FROM `{table_name}` WHERE {where_sql} LIMIT %s',
            params + [max(1, int(limit))]
        )
        rows = await db.fetchall()

    return [_row_json_safe(row) for row in rows]


async def mysql_find_one_by(table_name: str, criteria: dict) -> dict:
    """
    Универсальный поиск одной записи в таблице по критериям равенства.
    Если запись не найдена — ошибка (workflow останавливается с понятным сообщением).
    Returns:
        Словарь-запись таблицы: каждая колонка становится переменной
        {tool}_{step_id}_result_{column}.
    """
    rows = await mysql_find_by(table_name, criteria, limit=1)
    if not rows:
        raise ValueError(f'Запись не найдена: {table_name} по критериям {criteria}')

    return rows[0]


def _row_json_safe(row: dict) -> dict:
    # datetime и прочие не-JSON типы приводим к строке: результат попадает
    # в переменные workflow и сериализуется в трейс/снапшот сессии
    return {
        k: v if isinstance(v, (str, int, float, bool, list, dict)) or v is None else str(v)
        for k, v in row.items()
    }


def _where_build(table_name: str, criteria: dict) -> tuple:
    if not _IDENTIFIER.match(table_name or ''):
        raise ValueError(f'Недопустимое имя таблицы: "{table_name}"')

    conditions, params = [], []
    for column, value in (criteria or {}).items():
        if not _IDENTIFIER.match(str(column)):
            raise ValueError(f'Недопустимое имя колонки: "{column}"')

        if isinstance(value, (list, tuple)):
            if not value:
                conditions.append('1 = 0')  # пустой IN — заведомо пустой результат
                continue
            placeholders = ', '.join(['%s'] * len(value))
            conditions.append(f'`{column}` IN ({placeholders})')
            params.extend(value)
        elif value is None:
            conditions.append(f'`{column}` IS NULL')
        else:
            conditions.append(f'`{column}` = %s')
            params.append(value)

    where_sql = ' AND '.join(conditions) if conditions else '1 = 1'
    return where_sql, params
