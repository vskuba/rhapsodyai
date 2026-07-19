import json


async def list_render(items: list, template: str = '%s', separator: str = ', ') -> str:
    """
    Форматирует список в строку: каждый элемент подставляется в template вместо %s,
    элементы соединяются separator. Например template="[[%s]]" и separator=" "
    дают чипсы чата: [[a]] [[b]] [[c]].
    """
    if items is None or items == '':
        return ''

    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (ValueError, TypeError):
            items = [items]

    if not isinstance(items, list):
        items = [items]

    return separator.join(
        str(template).replace('%s', str(item)) for item in items if item is not None
    )


async def list_shift(items: list) -> dict:
    """
    Извлекает первый элемент JSON-массива объектов и возвращает его поля вместе
    с остатком списка в ключе 'rest'. Предназначено для workflow_invoke с
    repeat.until: outputs_map пишет 'rest' обратно в ту же переменную, которую
    читает inputs_map - каждая итерация забирает из очереди один элемент, пока
    until (rest empty) не остановит цикл.
     - items: JSON-массив объектов (или его JSON-строка)
    Returns:
        dict: поля первого элемента + rest (list) - остаток списка без первого элемента.
    """
    if isinstance(items, str):
        try:
            items = json.loads(items) if items.strip() else []
        except (ValueError, TypeError):
            items = []

    if not items:
        return {"rest": []}

    head, *rest = items
    result = dict(head) if isinstance(head, dict) else {"value": head}
    result["rest"] = rest
    return result
