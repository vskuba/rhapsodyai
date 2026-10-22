"""Сравнение двух списков: разница, пересечение, расхождение по полю.

⚠⚠ Сравнить два списка движок workflow не умеет: цикл читает поля, но попарно
пройти два списка нечем. Значит это работа инструмента, а не промпта.

⚠ Namespace свой, а не `list_`: тот про один список — склеить, обрезать, снять
первый. Здесь предмет другой — **два** списка и отношение между ними.
"""
import json


async def array_diff(array1, array2, key: str = '') -> dict:
    """
    Что есть в первом списке и чего нет во втором.

    Ответ на вопрос «чего не хватает» или «что лишнее»: два набора, и нужна
    разница. Порядок — первого списка; повторы сохраняются, их отбрасывает
    вызывающая сторона, если ей так нужно.

    ⚠ Работа для кода, а не для LLM. Сверка «список против списка» требует
    пройти по каждому элементу и сравнить, а модель на вопрос «всё ли на месте?»
    отвечает утвердительно почти всегда: сверки она не делает, а «да» —
    вероятный ответ.

    ## ⚠⚠ `key` — когда элементы это словари

    Без него сравниваются сами элементы. С ним — только значение этого поля:
    `array_diff(a, b, key="substr")` сравнит записи по `substr`, а остальные
    поля в счёт не пойдут. Так разницу ищут в ответах инструментов, где рядом
    со значением лежат `qty`, `pos` и прочее.

     - array1: откуда берём. Список либо строка JSON; пусто — пустой ответ.
     - array2: с чем сравниваем. Пусто — весь первый список и есть разница.
     - key: поле словаря для сравнения; пусто — сравниваем элементы целиком.

    Пример:
        result = await array_diff(["a", "b", "c"], ["b"])
        # result будет {"list": ["a", "c"], "qty": 2}

    Returns:
        A dictionary with the difference.
        list (list): Элементы первого списка, которых нет во втором.
        qty (int): Сколько их.
    """
    one, two = _array_items(array1), _array_items(array2)
    known = {_array_key(item, key) for item in two}
    found = [item for item in one if _array_key(item, key) not in known]

    return {"list": found, "qty": len(found)}


async def array_intersect(array1, array2, key: str = '') -> dict:
    """
    Что есть и в первом списке, и во втором.

    Обратная сторона `array_diff`: та отвечает «чего нет», эта — «что общего».
    Порядок — первого списка.

    ⚠ Работа для кода, а не для LLM: см. `array_diff`.

     - array1: откуда берём. Список либо строка JSON; пусто — пустой ответ.
     - array2: с чем сравниваем. Пусто — общего ничего.
     - key: поле словаря для сравнения; пусто — сравниваем элементы целиком.

    Пример:
        result = await array_intersect(["a", "b", "c"], ["b", "c", "d"])
        # result будет {"list": ["b", "c"], "qty": 2}

    Returns:
        A dictionary with the intersection.
        list (list): Элементы первого списка, которые есть и во втором.
        qty (int): Сколько их.
    """
    one, two = _array_items(array1), _array_items(array2)
    known = {_array_key(item, key) for item in two}
    found = [item for item in one if _array_key(item, key) in known]

    return {"list": found, "qty": len(found)}


async def array_diff_key(array1, array2, key: str, value: str,
                         name: str = '') -> dict:
    """
    Пары из двух списков, у которых разошлось значение — по одному полю.

    Ответ на вопрос «где два набора разъехались»: списки сводятся по `key`, а
    сравнивается `value`. Элемент, которому нет пары, попадает в ответ тоже —
    его отсутствие и есть расхождение.

    ## ⚠⚠ Ради чего заведено

    Агент письма написал имя переменной **без скобок** — «companion_name, the
    kettle clicked off» вместо `[[companion_name]]`. Прежние проверки этого не
    видели: регулярка меток ищет только `[[…]]`, а поиск по голому имени
    находит его и внутри метки.

    Ловится парой счётов (`text_substr` со списком): сколько раз имя встречается
    голым и сколько — в скобках. Числа обязаны совпасть, потому что каждое
    вхождение имени должно быть внутри метки. Этот инструмент и сводит два
    ответа, показывая, **какая именно** метка оформлена неверно.

     - array1: первый список словарей либо строка JSON.
     - array2: второй список словарей.
     - key: поле, по которому ищем пару. Пусто — пары берутся **по месту** в
       списке: так сводятся ответы одного инструмента, спрошенного двумя
       наборами в одном порядке (голые имена и они же в скобках — значения
       разные, а порядок один).
     - value: поле, значения которого сравниваем.
     - name: чем называть расхождение в ответе. Пусто — берётся `key`, а при
       сведении по месту — номер места, что читается плохо.

    Пример:
        a = [{"substr": "x", "qty": 1}, {"substr": "y", "qty": 2}]
        b = [{"substr": "[[x]]", "qty": 1}, {"substr": "[[y]]", "qty": 0}]
        result = await array_diff_key(a, b, key="", value="qty",
                                      name="substr")
        # result будет {"list": ["y"], "qty": 1, "str": "y"}

    Returns:
        A dictionary with the mismatches.
        list (list): Значения `key` у разошедшихся пар, в порядке первого списка.
        qty (int): Сколько их.
        str (str): Они же строкой через запятую; пусто — всё сошлось.
    """
    one, two = _array_items(array1), _array_items(array2)

    # ⚠ Чем называть расхождение: своим полем, иначе ключом сведения. При
    # сведении по месту без `name` вышел бы номер («1»), а человеку и промпту
    # нужно имя.
    kak_zvat = name or key

    if key:
        found = {_array_key(item, key): item for item in two}
        tags = [(_array_name(item, kak_zvat, at), item,
                 found.get(_array_key(item, key)))
                for at, item in enumerate(one)]
    else:
        # ⚠ Без ключа — по месту в списке: так сводятся ответы одного
        # инструмента, спрошенного двумя наборами в одном порядке.
        tags = [(_array_name(item, kak_zvat, at), item,
                 two[at] if at < len(two) else None)
                for at, item in enumerate(one)]

    bad = [tag for tag, left, right in tags
           if right is None or _array_key(left, value) != _array_key(right, value)]

    return {"list": bad, "qty": len(bad), "str": ','.join(str(one) for one in bad)}


# ── Приватное ────────────────────────────────────────────────────────────────

def _array_items(value) -> list:
    """Значение списком: сам список, JSON-строка или одиночка.

    ⚠ Пусто — пустой список, а не список из пустоты: `[""]` дал бы ложный
    элемент, и разница посчиталась бы не по тому.
    """
    if value is None or value == '':
        return []

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return [value]

    if isinstance(value, (list, tuple)):
        return list(value)

    return [value]


def _array_name(item, key: str, at: int) -> str:
    """Как назвать элемент в ответе: поле, иначе номер места.

    ⚠ Номер — последнее средство: он ничего не говорит ни человеку, ни промпту,
    и нужен только когда у элементов нет подходящего поля.
    """
    if key and isinstance(item, dict) and item.get(key) not in (None, ''):
        return str(item[key])

    return str(at)


def _array_key(item, key: str):
    """Чем сравниваем элемент: он сам или значение его поля.

    ⚠ Приводим к строке: из JSON число приезжает числом, а из workflow-переменной
    строкой, и `1 != "1"` развалило бы сравнение молча.
    """
    if key and isinstance(item, dict):
        return str(item.get(key, ''))

    return str(item)
