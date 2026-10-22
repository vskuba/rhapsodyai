"""Сравнение двух массивов: по значениям, по ключам, по парам целиком.

⚠⚠ Сравнить два списка движок workflow не умеет: цикл читает поля, но попарно
пройти два списка нечем. Значит это работа инструмента, а не промпта.

⚠ Namespace свой, а не `list_`: тот про один список — склеить, обрезать, снять
первый. Здесь предмет другой — **два** массива и отношение между ними.

⚠⚠ Имена и смысл — **как в PHP** (`array_diff`, `array_diff_key`,
`array_diff_assoc`, `array_intersect`). Своих доводов не добавляем: знакомое имя
обязано делать знакомое дело, иначе читающий подставит чужое поведение и
ошибётся молча. Два массива на входе, массив на выходе — и всё.
"""
import json


async def array_diff(array1, array2) -> dict:
    """
    Элементы первого массива, которых нет во втором. Сравнение по значениям.

    Как `array_diff` в PHP. Ответ на вопрос «чего не хватает» или «что лишнее»:
    два набора, и нужна разница. Порядок — первого массива; ключи сохраняются,
    если на входе был словарь.

    ⚠ Работа для кода, а не для LLM. Сверка «список против списка» требует
    пройти по каждому элементу и сравнить, а модель на вопрос «всё ли на
    месте?» отвечает утвердительно почти всегда: сверки она не делает, а «да» —
    вероятный ответ.

     - array1: откуда берём. Массив, словарь либо строка JSON.
     - array2: с чем сравниваем. Пусто — весь первый массив и есть разница.

    Пример:
        result = await array_diff(["a", "b", "c"], ["b"])
        # result будет {"list": ["a", "c"], "qty": 2}

    Returns:
        A dictionary with the difference.
        list (list): Элементы первого массива, которых нет во втором.
        dict (dict): Они же с ключами, если на входе был словарь.
        qty (int): Сколько их.
    """
    one, two = _array_pairs(array1), _array_pairs(array2)
    known = {_array_text(value) for _, value in two}
    found = [(key, value) for key, value in one
             if _array_text(value) not in known]

    return _array_answer(found)


async def array_diff_key(array1, array2) -> dict:
    """
    Элементы первого массива, чьих ключей нет во втором.

    Как `array_diff_key` в PHP: сравниваются **ключи**, а значения в счёт не
    идут. Ответ на вопрос «каких полей не хватает во втором наборе».

    ⚠ Работа для кода, а не для LLM: см. `array_diff`.

     - array1: откуда берём. Словарь либо строка JSON; у массива ключ — номер.
     - array2: с чьими ключами сравниваем.

    Пример:
        result = await array_diff_key({"a": 1, "b": 2}, {"a": 9})
        # result будет {"list": [2], "dict": {"b": 2}, "qty": 1}

    Returns:
        A dictionary with the difference.
        list (list): Значения тех элементов, чьих ключей нет во втором.
        dict (dict): Они же с ключами.
        qty (int): Сколько их.
    """
    one, two = _array_pairs(array1), _array_pairs(array2)
    known = {key for key, _ in two}
    found = [(key, value) for key, value in one if key not in known]

    return _array_answer(found)


async def array_diff_assoc(array1, array2) -> dict:
    """
    Элементы первого массива, у которых во втором нет **такой же пары**
    «ключ → значение».

    Как `array_diff_assoc` в PHP: ключ ищется во втором массиве, и значения
    сравниваются. Ключа нет или значение другое — элемент попадает в ответ.

    ## ⚠⚠ Ради чего заведено

    Агент письма написал имя переменной **без скобок** — «companion_name, the
    kettle clicked off» вместо `[[companion_name]]`. Прежние проверки этого не
    видели: регулярка меток ищет только `[[…]]`, а поиск по голому имени
    находит его и внутри метки.

    Ловится парой счётов (`substr_count`): сколько раз имя
    встречается голым и сколько — в скобках. Числа обязаны совпасть, потому что
    каждое вхождение имени должно быть внутри метки. Этот инструмент сводит два
    ответа и называет, **какая именно** метка оформлена неверно.

    ⚠ Ни `array_diff`, ни `array_diff_key` такого не ловят: ключи у двух
    наборов одинаковы, значения тоже встречаются в обоих — расходится только
    **пара**. Проверено.

     - array1: откуда берём. Словарь либо строка JSON.
     - array2: с чем сравниваем.

    Пример:
        a = {"girl_name": 1, "companion_name": 1}
        b = {"girl_name": 1, "companion_name": 0}
        result = await array_diff_assoc(a, b)
        # result будет {"list": [1], "dict": {"companion_name": 1}, "qty": 1}

    Returns:
        A dictionary with the difference.
        list (list): Значения разошедшихся элементов.
        dict (dict): Они же с ключами — по ним и видно, что сломалось.
        qty (int): Сколько их.
    """
    one, two = _array_pairs(array1), _array_pairs(array2)
    known = {key: _array_text(value) for key, value in two}
    found = [(key, value) for key, value in one
             if known.get(key) != _array_text(value)]

    return _array_answer(found)


async def array_intersect(array1, array2) -> dict:
    """
    Элементы первого массива, которые есть и во втором. Сравнение по значениям.

    Как `array_intersect` в PHP. Обратная сторона `array_diff`: та отвечает
    «чего нет», эта — «что общего». Порядок — первого массива.

    ⚠ Работа для кода, а не для LLM: см. `array_diff`.

     - array1: откуда берём. Массив, словарь либо строка JSON.
     - array2: с чем сравниваем. Пусто — общего ничего.

    Пример:
        result = await array_intersect(["a", "b", "c"], ["b", "c", "d"])
        # result будет {"list": ["b", "c"], "qty": 2}

    Returns:
        A dictionary with the intersection.
        list (list): Элементы первого массива, которые есть и во втором.
        dict (dict): Они же с ключами, если на входе был словарь.
        qty (int): Сколько их.
    """
    one, two = _array_pairs(array1), _array_pairs(array2)
    known = {_array_text(value) for _, value in two}
    found = [(key, value) for key, value in one
             if _array_text(value) in known]

    return _array_answer(found)

async def array_intersect_key(array1, array2) -> dict:
    """
    Элементы первого массива, чьи ключи есть и во втором.

    Как `array_intersect_key` в PHP: сравниваются **ключи**, значения в счёт не
    идут. Обратная сторона `array_diff_key`.

     - array1: откуда берём. Словарь либо строка JSON; у массива ключ — номер.
     - array2: с чьими ключами сравниваем.

    Пример:
        result = await array_intersect_key({"a": 1, "b": 2}, {"a": 9})
        # result будет {"list": [1], "dict": {"a": 1}, "qty": 1}

    Returns:
        A dictionary with the intersection.
        list (list): Значения совпавших по ключу элементов.
        dict (dict): Они же с ключами.
        qty (int): Сколько их.
    """
    one, two = _array_pairs(array1), _array_pairs(array2)
    known = {key for key, _ in two}

    return _array_answer([(key, value) for key, value in one if key in known])


async def array_intersect_assoc(array1, array2) -> dict:
    """
    Элементы, у которых во втором массиве есть **такая же пара** «ключ → значение».

    Как `array_intersect_assoc` в PHP. Обратная сторона `array_diff_assoc`.

     - array1: откуда берём. Словарь либо строка JSON.
     - array2: с чем сравниваем.

    Returns:
        A dictionary with the intersection.
        list (list): Значения совпавших пар.
        dict (dict): Они же с ключами.
        qty (int): Сколько их.
    """
    one, two = _array_pairs(array1), _array_pairs(array2)
    known = {key: _array_text(value) for key, value in two}

    return _array_answer([(key, value) for key, value in one
                          if known.get(key) == _array_text(value)])


async def array_merge(array1, array2) -> dict:
    """
    Склеивает два массива в один.

    Как `array_merge` в PHP: строковые ключи второго перекрывают первый,
    числовые — дописываются в конец, а не замещают.

     - array1: первый массив, словарь либо строка JSON.
     - array2: второй; его значения кладутся поверх.

    Пример:
        result = await array_merge(["a"], ["b"])
        # result будет {"list": ["a", "b"], "qty": 2}

    Returns:
        A dictionary with the merge.
        list (list): Значения итогового массива.
        dict (dict): Он же с ключами.
        qty (int): Сколько элементов.
    """
    found = list(_array_pairs(array1))
    at = len(found)
    for key, value in _array_pairs(array2):
        # ⚠ Числовой ключ — дописываем, как в PHP: иначе два массива по три
        # элемента слились бы в три, а не в шесть.
        if isinstance(key, int):
            found.append((at, value))
            at += 1
            continue

        found = [(k, v) for k, v in found if k != key]
        found.append((key, value))

    return _array_answer(found)


async def array_unique(array1) -> dict:
    """
    Убирает повторы, оставляя первое вхождение каждого значения.

    Как `array_unique` в PHP: сравнение по значению, порядок — исходный.

     - array1: массив, словарь либо строка JSON.

    Пример:
        result = await array_unique(["a", "b", "a"])
        # result будет {"list": ["a", "b"], "qty": 2}

    Returns:
        A dictionary with the result.
        list (list): Значения без повторов.
        dict (dict): Они же с исходными ключами.
        qty (int): Сколько осталось.
    """
    found, seen = [], set()
    for key, value in _array_pairs(array1):
        text = _array_text(value)
        if text in seen:
            continue
        seen.add(text)
        found.append((key, value))

    return _array_answer(found)


async def array_keys(array1) -> dict:
    """
    Только ключи массива.

    Как `array_keys` в PHP. У списка ключи — номера с нуля.

     - array1: массив, словарь либо строка JSON.

    Returns:
        A dictionary with the keys.
        list (list): Ключи в порядке массива.
        qty (int): Сколько их.
        str (str): Они же строкой через запятую — так их читает промпт.
    """
    return _array_answer([(key, str(key)) for key, _ in _array_pairs(array1)])


async def array_values(array1) -> dict:
    """
    Только значения массива, без ключей.

    Как `array_values` в PHP.

     - array1: массив, словарь либо строка JSON.

    Returns:
        A dictionary with the values.
        list (list): Значения в порядке массива.
        qty (int): Сколько их.
        str (str): Они же строкой через запятую.
    """
    return _array_answer(list(_array_pairs(array1)))


async def array_flip(array1) -> dict:
    """
    Меняет ключи и значения местами.

    Как `array_flip` в PHP: повторившееся значение затирает прежний ключ.

     - array1: массив, словарь либо строка JSON.

    Пример:
        result = await array_flip({"a": "x"})
        # result будет {"dict": {"x": "a"}, "list": ["a"], "qty": 1}

    Returns:
        A dictionary with the flip.
        dict (dict): Перевёрнутый массив.
        list (list): Его значения — прежние ключи.
        qty (int): Сколько элементов.
    """
    found = {}
    for key, value in _array_pairs(array1):
        found[_array_text(value)] = key

    return _array_answer(list(found.items()))


async def array_column(array1, column: str, index: str = '') -> dict:
    """
    Один столбец из массива словарей.

    Как `array_column` в PHP: из каждой записи берётся поле `column`, а `index`
    задаёт, каким полем её ключевать.

    ⚠ Записи без нужного поля пропускаются, как в PHP.

     - array1: массив словарей либо строка JSON.
     - column: какое поле берём.
     - index: каким полем ключевать; пусто — номерами.

    Пример:
        rows = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = await array_column(rows, "name", "id")
        # result будет {"dict": {"1": "a", "2": "b"}, "list": ["a", "b"], "qty": 2}

    Returns:
        A dictionary with the column.
        list (list): Значения столбца.
        dict (dict): Они же с ключами из `index`.
        qty (int): Сколько их.
    """
    found = []
    for at, (_, item) in enumerate(_array_pairs(array1)):
        if not isinstance(item, dict) or column not in item:
            continue
        key = item.get(index) if index and index in item else at
        found.append((key, item[column]))

    return _array_answer(found)


async def array_combine(keys, values) -> dict:
    """
    Словарь из двух массивов: первый даёт ключи, второй — значения.

    Как `array_combine` в PHP.

    ⚠ Длины не сошлись — берём по короткому, а не роняем прогон: половинчатый
    ответ честнее отказа посреди цепочки.

     - keys: откуда ключи.
     - values: откуда значения.

    Returns:
        A dictionary with the result.
        dict (dict): Собранный словарь.
        list (list): Его значения.
        qty (int): Сколько пар.
    """
    one = [key for _, key in _array_pairs(keys)]
    two = [value for _, value in _array_pairs(values)]

    return _array_answer([(_array_text(k), v) for k, v in zip(one, two)])


async def array_fill_keys(keys, value: str = '') -> dict:
    """
    Словарь из ключей, всем одно значение.

    Как `array_fill_keys` в PHP.

     - keys: откуда ключи.
     - value: что положить каждому.

    Returns:
        A dictionary with the result.
        dict (dict): Собранный словарь.
        list (list): Его значения.
        qty (int): Сколько ключей.
    """
    return _array_answer([(_array_text(key), value)
                          for _, key in _array_pairs(keys)])


async def array_slice(array1, offset: int = 0, length: int = 0) -> dict:
    """
    Кусок массива.

    Как `array_slice` в PHP: отрицательный `offset` отсчитывается с конца.

    ⚠ `length = 0` значит «до конца»: в workflow число приходит строкой и часто
    пустым, и «ноль элементов» было бы ловушкой.

     - array1: массив, словарь либо строка JSON.
     - offset: откуда берём; отрицательный — с конца.
     - length: сколько берём; 0 — до конца.

    Returns:
        A dictionary with the slice.
        list (list): Взятые значения.
        dict (dict): Они же с ключами.
        qty (int): Сколько взяли.
    """
    pairs = _array_pairs(array1)
    start = _array_int(offset, 0)
    take = _array_int(length, 0)
    found = pairs[start:] if take <= 0 else pairs[start:start + take]

    return _array_answer(found)


async def array_reverse(array1) -> dict:
    """
    Массив задом наперёд.

    Как `array_reverse` в PHP.

     - array1: массив, словарь либо строка JSON.

    Returns:
        A dictionary with the result.
        list (list): Значения в обратном порядке.
        dict (dict): Они же с ключами.
        qty (int): Сколько элементов.
    """
    return _array_answer(list(reversed(_array_pairs(array1))))


async def array_search(array1, needle: str) -> dict:
    """
    Где лежит значение: ключ первого вхождения.

    Как `array_search` в PHP, но ответ всегда словарь.

    ⚠⚠ Судить о находке — **по `found`, а не по `key`**: первый элемент имеет
    ключ `0`, а условие на пустое значение считает ноль за «пусто» — и
    найденное прочиталось бы как ненайденное. Та же грабля, что у `substr_position`.

     - array1: где ищем.
     - needle: что ищем.

    Returns:
        A dictionary with the search result.
        found (str): '1' — значение есть, '0' — нет.
        key (str): Ключ первого вхождения; пусто — не нашлось.
    """
    igla = _array_text(needle)
    found = [(key, value) for key, value in _array_pairs(array1)
             if _array_text(value) == igla]

    # ⚠ Только первое вхождение, как в PHP: `array_search` отвечает «где
    # лежит», а не «сколько их» — на это есть `array_count_values`.
    return _array_answer(found[:1])


async def array_count_values(array1) -> dict:
    """
    Сколько раз встречается каждое значение.

    Как `array_count_values` в PHP.

     - array1: массив, словарь либо строка JSON.

    Пример:
        result = await array_count_values(["a", "b", "a"])
        # result будет {"dict": {"a": 2, "b": 1}, "qty": 2}

    Returns:
        A dictionary with the counts.
        dict (dict): «значение → сколько раз».
        list (list): Сами счётчики.
        qty (int): Сколько разных значений.
    """
    found = {}
    for _, value in _array_pairs(array1):
        text = _array_text(value)
        found[text] = found.get(text, 0) + 1

    return _array_answer(list(found.items()))


async def array_count(array1) -> dict:
    """
    Сколько элементов в массиве.

    Как `count` в PHP. Отдельным инструментом, потому что у прочих счёт едет
    довеском, а здесь это и есть вопрос.

     - array1: массив, словарь либо строка JSON.

    Returns:
        A dictionary with the count.
        qty (int): Сколько элементов. Пустой массив — 0.
    """
    return _array_answer(list(_array_pairs(array1)))



# ── Приватное ────────────────────────────────────────────────────────────────

def _array_pairs(value) -> list:
    """Значение парами «ключ, значение». У массива ключ — номер, как в PHP.

    ⚠ Пусто — пустой список, а не список из пустоты: `[""]` дал бы ложный
    элемент, и разница посчиталась бы не по тому.
    """
    if value is None or value == '':
        return []

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return [(0, value)]

    if isinstance(value, dict):
        return list(value.items())

    if isinstance(value, (list, tuple)):
        return list(enumerate(value))

    return [(0, value)]


def _array_text(value) -> str:
    """Значение для сравнения — строкой.

    ⚠ Из JSON число приезжает числом, а из workflow-переменной строкой, и
    `1 != "1"` развалило бы сравнение молча.
    """
    return str(value)


def _array_int(value, default: int) -> int:
    """Число из довода. ⚠ В workflow оно приходит строкой и часто пустым."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _array_answer(found: list) -> dict:
    """Ответ семьи — **всегда одной формы**, что бы инструмент ни делал.

    ## ⚠⚠⚠ Один набор ключей на все `array_*`

    Форм было четыре: `list/dict/qty` у большинства, `list/qty/str` у `keys` и
    `values`, `found/key` у `search`, один `qty` у `count`. Вызывающий не мог
    знать, что придёт, и в workflow это всплывало переменной в «Undefined».

    Теперь ключи одни:

        list   значения — их читает цикл промпта
        dict   они же с ключами — по нему видно, ЧТО именно сломалось
        str    значения строкой через запятую — так их подставляют в промпт
        qty    сколько элементов
        found  '1' — ответ непуст, '0' — пуст; судить в условии по нему
        key    ключ первого элемента; пусто — элементов нет

    ⚠ `found` и `key` заведены ради `array_search`, но есть у всех: «нашлось
    ли» — вопрос к любому ответу, а два разных способа его задать и были бедой.

    ⚠⚠ Судить в workflow — **по `found` или `qty`, а не по `key`**: у первого
    элемента ключ `0`, и условие на пустое значение считает ноль за «пусто».
    """
    keys = [str(key) for key, _ in found]
    values = [value for _, value in found]

    return {'list': values,
            'dict': {str(key): value for key, value in found},
            'str': ','.join(str(one) for one in values),
            'qty': len(found),
            'found': '1' if found else '0',
            'key': keys[0] if keys else ''}
