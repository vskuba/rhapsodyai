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
