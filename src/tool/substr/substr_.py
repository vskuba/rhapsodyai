"""Работа с подстрокой: вырезать, сосчитать, найти, заменить — семантика PHP.

⚠⚠ Имена и доводы взяты у PHP один в один (`substr`, `substr_count`,
`substr_replace`, `substr_position`, `substr_contains`…). Знакомое имя обязано
делать знакомое дело: назови функцию `substr`, а считай вхождения — читающий
подставит чужое поведение и ошибётся молча. Так уже было: прежний `text_substr`
искал и считал, хотя в PHP `substr` **вырезает кусок**.

⚠ Namespace свой, а не `text_`: тот про текст целиком — разрезать по
разделителю, перевести регистр, проверить длину. Здесь предмет уже — **кусок
строки** и его место.

⚠⚠ Поиск всюду **буквальный**: ни регулярок, ни границ слова. `кот` найдётся
внутри `котлеты`. Для узоров есть `text_regex_*`.

⚠ Ответ всегда словарём, даже когда значение одно: в workflow результат шага
читается по имени ключа, и голая строка не дала бы его.
"""


async def substr(string: str, offset: int = 0, length=None) -> dict:
    """
    Кусок строки с заданного места.

    Как `substr` в PHP: отрицательный `offset` отсчитывается с конца,
    отрицательная `length` отрезает столько знаков с конца.

    ⚠ `length` пустая — до конца строки. В workflow число приходит строкой и
    часто пустым, и «ноль знаков» было бы ловушкой.

     - string: откуда берём.
     - offset: с какого знака, счёт с нуля; отрицательный — с конца.
     - length: сколько знаков; пусто — до конца, отрицательная — сколько
       отрезать с конца.

    Пример:
        result = await substr("abcdef", 1, 3)
        # result будет {"str": "bcd", "len": 3}

    Returns:
        A dictionary with the part.
        str (str): Вырезанный кусок. Пустая строка — брать нечего.
        len (int): Его длина.
    """
    said = str(string if string is not None else '')
    start = _substr_int(offset, 0)
    take = _substr_int(length, None)

    part = said[start:] if take is None else (
        said[start:take] if take < 0 else said[start:start + take])

    return {'str': part, 'len': len(part)}


async def substr_count(haystack: str, needle: str,
                       ignore_case: bool = False) -> dict:
    """
    Сколько раз подстрока встречается в тексте.

    Как `substr_count` в PHP: непересекающиеся вхождения. «аа» в «ааа» даёт
    один, а не два — иначе счёт перестал бы отвечать на вопрос «сколько раз это
    написано».

    ⚠ Работа для кода, а не для LLM: «сколько раз здесь это слово?» модель
    отвечает наугад, считать знак за знаком она не умеет.

    ## ⚠⚠ Ради чего заведено

    Агент письма написал имя переменной **без скобок** — «companion_name, the
    kettle clicked off» вместо `[[companion_name]]`. Поиском этого не узнать:
    имя встречается и **внутри** метки, то есть находится всегда. Спрашивается
    счётом — сколько раз имя и сколько раз метка; числа обязаны совпасть.

     - haystack: где ищем.
     - needle: что ищем. Пусто — искать нечего, ответ `0`.
     - ignore_case: не различать регистр. ⚠ Довод сверх PHP: модель пишет одно
       слово и с заглавной, и со строчной.

    Returns:
        A dictionary with the count.
        qty (int): Сколько раз встретилась. Ноль — ни разу.
    """
    stog, igla = _substr_pair(haystack, needle, ignore_case)
    if not igla:
        return {'qty': 0}

    return {'qty': stog.count(igla)}


async def substr_position(haystack: str, needle: str, offset: int = 0,
                          ignore_case: bool = False, last: bool = False) -> dict:
    """
    Где лежит подстрока: позиция вхождения.

    Как `strpos` в PHP, а с `last = true` — как `strrpos`.

    ⚠⚠ Судить о находке в workflow — **по `found`, а не по `pos`**: вхождение в
    самом начале даёт `pos = 0`, а условие на пустое значение считает ноль за
    «пусто», и найденное прочиталось бы как ненайденное.

     - haystack: где ищем.
     - needle: что ищем. Пусто — не нашлось.
     - offset: с какого знака начинать.
     - ignore_case: не различать регистр (`stripos` в PHP).
     - last: искать последнее вхождение, а не первое.

    Returns:
        A dictionary with the position.
        found (str): '1' — подстрока есть, '0' — нет.
        pos (int): Позиция вхождения, счёт с нуля; -1 — нет.
    """
    stog, igla = _substr_pair(haystack, needle, ignore_case)
    if not igla:
        return {'found': '0', 'pos': -1}

    start = _substr_int(offset, 0)
    at = stog.rfind(igla, start) if last else stog.find(igla, start)

    return {'found': '1' if at >= 0 else '0', 'pos': at}


async def substr_contains(haystack: str, needle: str,
                          ignore_case: bool = False) -> dict:
    """
    Есть ли подстрока в тексте.

    Как `str_contains` в PHP. Отдельно от `substr_position`, потому что вопрос
    другой: тому нужно «где», этому — «есть ли», и ответ читается прямо.

     - haystack: где ищем.
     - needle: что ищем. Пусто — нет.
     - ignore_case: не различать регистр.

    Returns:
        A dictionary with the answer.
        found (str): '1' — есть, '0' — нет.
    """
    stog, igla = _substr_pair(haystack, needle, ignore_case)

    return {'found': '1' if igla and igla in stog else '0'}


async def substr_starts_with(haystack: str, needle: str,
                             ignore_case: bool = False) -> dict:
    """
    Начинается ли текст с подстроки.

    Как `str_starts_with` в PHP.

    ⚠ Пустая игла — `'0'`, а не `'1'`: в PHP пустая строка считается началом
    любой, но для workflow это ложное «да» на незаполненной переменной.

    Returns:
        A dictionary with the answer.
        found (str): '1' — начинается, '0' — нет.
    """
    stog, igla = _substr_pair(haystack, needle, ignore_case)

    return {'found': '1' if igla and stog.startswith(igla) else '0'}


async def substr_ends_with(haystack: str, needle: str,
                           ignore_case: bool = False) -> dict:
    """
    Кончается ли текст подстрокой.

    Как `str_ends_with` в PHP.

    ⚠ Пустая игла — `'0'`, по той же причине, что у `substr_starts_with`.

    Returns:
        A dictionary with the answer.
        found (str): '1' — кончается, '0' — нет.
    """
    stog, igla = _substr_pair(haystack, needle, ignore_case)

    return {'found': '1' if igla and stog.endswith(igla) else '0'}


async def substr_replace(string: str, replace: str, offset: int = 0,
                         length=None) -> dict:
    """
    Заменить кусок строки по месту.

    Как `substr_replace` в PHP: кусок с `offset` длиной `length` заменяется на
    `replace`.

    ⚠ `length` пустая — до конца строки, как и у `substr`.

     - string: что правим.
     - replace: чем заменяем. Пусто — кусок просто вырезается.
     - offset: с какого знака; отрицательный — с конца.
     - length: сколько знаков заменить; пусто — до конца.

    Returns:
        A dictionary with the result.
        str (str): Строка после замены.
        len (int): Её длина.
    """
    said = str(string if string is not None else '')
    new = str(replace if replace is not None else '')
    start = _substr_int(offset, 0)
    take = _substr_int(length, None)

    if start < 0:
        start = max(len(said) + start, 0)
    end = len(said) if take is None else (
        len(said) + take if take < 0 else start + take)
    out = said[:start] + new + said[max(end, start):]

    return {'str': out, 'len': len(out)}


async def substr_str_replace(haystack: str, needle: str, replace: str,
                             ignore_case: bool = False) -> dict:
    """
    Заменить все вхождения подстроки.

    Как `str_replace` в PHP (с `ignore_case` — как `str_ireplace`).

    ⚠ Пустая игла ничего не меняет: `''.replace` вставил бы замену между каждой
    парой знаков.

     - haystack: что правим.
     - needle: что заменяем.
     - replace: на что.
     - ignore_case: не различать регистр.

    Returns:
        A dictionary with the result.
        str (str): Строка после замены.
        qty (int): Сколько вхождений заменено.
    """
    said = str(haystack if haystack is not None else '')
    igla = str(needle if needle is not None else '')
    new = str(replace if replace is not None else '')

    if not igla:
        return {'str': said, 'qty': 0}

    if not ignore_case:
        return {'str': said.replace(igla, new), 'qty': said.count(igla)}

    # ⚠ Без регистра — идём по найденным местам: `str.replace` регистр
    # различает всегда, а менять надо сам текст, а не его нижний вид.
    out, at, qty = [], 0, 0
    low_said, low_igla = said.lower(), igla.lower()
    while True:
        found = low_said.find(low_igla, at)
        if found < 0:
            break
        out.append(said[at:found])
        out.append(new)
        at = found + len(igla)
        qty += 1
    out.append(said[at:])

    return {'str': ''.join(out), 'qty': qty}


async def substr_length(string: str) -> dict:
    """
    Длина строки в знаках.

    Как `strlen` в PHP, но считает **символы**, а не байты: у нас текст
    юникодный, и «байт» ответил бы не на тот вопрос.

    Returns:
        A dictionary with the length.
        len (int): Сколько знаков. Пусто — 0.
    """
    return {'len': len(str(string if string is not None else ''))}


# ── Приватное ────────────────────────────────────────────────────────────────

def _substr_pair(haystack, needle, ignore_case: bool) -> tuple:
    """Стог и игла строками, приведённые к одному регистру при надобности."""
    stog = str(haystack if haystack is not None else '')
    igla = str(needle if needle is not None else '')

    if ignore_case:
        return stog.lower(), igla.lower()

    return stog, igla


def _substr_int(value, default):
    """Число из довода. ⚠ В workflow оно приходит строкой и часто пустым."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
