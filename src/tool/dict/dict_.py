import json


async def dict_column(data: list, column_name: str):
    """
    Возвращает значения по ключу column_name из данных.
    data — список словарей (вернется список значений по ключу из каждой записи),
    словарь (вернется значение ключа) или JSON-строка одного из этих видов.
    Пустые/невалидные данные — пустая строка.
    """
    if data is None or data == '':
        return ''

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return ''

    if isinstance(data, dict):
        value = data.get(column_name)
        return '' if value is None else value

    if isinstance(data, list):
        return [row.get(column_name) for row in data if isinstance(row, dict)]

    return ''