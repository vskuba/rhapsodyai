import json
import re


async def list_render(items: list, template: str = '%s', separator: str = ', ',
                      limit: int = 0) -> str:
    """
    Форматирует список в строку: каждый элемент подставляется в template вместо %s,
    элементы соединяются separator. Например template="[[%s]]" и separator=" "
    дают чипсы чата: [[a]] [[b]] [[c]].
     - limit: сколько элементов взять с начала; 0 — все.

    ⚠ Обрезка нужна там, где список набирают пачками и последняя пачка приносит
    больше заказанного: панель просила 14 реплик, круг дал 17. Отдать лишнее —
    соврать о заказе, а резать в промпте словами ненадёжно.

    ⚠⚠ Берётся **начало**, а не конец: в накопителе первыми лежат реплики,
    принятые раньше, и они уже прошли все проверки на повтор друг с другом.
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

    items = [one for one in items if one is not None]

    # ⚠ Число приходит workflow-переменной, то есть строкой, и бывает пустым.
    try:
        take = int(limit or 0)
    except (TypeError, ValueError):
        take = 0

    if take > 0:
        items = items[:take]

    return separator.join(
        str(template).replace('%s', str(item)) for item in items
    )


async def list_pick(items: list, numbers: str, separator: str = '\n---\n') -> dict:
    """
    Оставляет элементы списка по их номерам и склеивает в строку.
    Номера — через запятую, счёт с единицы («2,5,6»); чужие и повторные
    отбрасываются, порядок сохраняется исходный, а не порядок номеров.
     - items: JSON-массив строк (или его JSON-строка)
     - numbers: номера нужных элементов через запятую
     - separator: чем склеить отобранное
    Returns:
        A dictionary with the picked items.
        str (str): отобранные элементы, склеенные separator.
        qty (int): сколько элементов отобрано.

    ## ⚠⚠ Зачем номера, а не сам текст

    Судья пачки отбирает годные реплики, и просить его **воспроизвести** их
    дословно ненадёжно: на живом прогоне он писал «line 5 is the best and is
    kept», а в ответ клал строку line 2 — то есть терял работу молча. Номер
    модель держит точно, а текст по номеру берёт код.

    ⚠ Счёт с единицы: в промпте строки нумеруются для человека и для модели,
    и ноль там не встречается нигде.

    ⚠ Порядок — исходный. Отбор не перетасовывает пачку: реплики писались под
    приём со своим номером, и перестановка развязала бы их с ним.
    """
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (ValueError, TypeError):
            items = [items] if items else []

    if not isinstance(items, list):
        items = [items] if items else []

    # ⚠ Числа вытаскиваются из любой записи: модель пишет и «2,5», и «line 2,
    # line 5», и «2 and 5» — требовать от неё чистый список значило бы терять
    # работу на форме ответа, а не на его сути.
    #
    # ⚠⚠ Отрицательные не проходят: `(?<![\d-])` отсекает минус перед цифрой.
    # Без него «-3» становился третьим элементом, то есть заведомо негодный
    # номер молча оказывался законным.
    wanted = {int(one) for one in re.findall(r'(?<![\d-])\d+', str(numbers or ''))}

    picked = [str(one) for number, one in enumerate(items, start=1)
              if number in wanted and one is not None and str(one).strip()]

    return {'str': str(separator).join(picked), 'qty': len(picked)}


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
