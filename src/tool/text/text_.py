import re

from i18n_.i18n_ import i18n_translit_cyr
# ⚠ Под своим именем: имя библиотечной функции совпало бы с именем инструмента
# (`text_cyrillic_has`), и обёртка звала бы саму себя — бесконечной рекурсией
# прямо на первом вызове из workflow.
from text_.text_cyrillic import text_cyrillic_has as text_cyrillic_has_check

# Разделители вилки длины: обычный дефис и оба типографских тире.
#
# ⚠ Тире здесь не прихоть: вилки жребия писем набраны именно коротким тире
# («20–30 words»), и мерка, знающая один дефис, тихо не разобрала бы ни одной
# из них — то есть пропускала бы любую длину, выглядя рабочей.
TEXT_RANGE_DASHES = '-‐‑‒–—−'

# Единицы длины, в которых умеем мерить.
TEXT_LENGTH_UNITS = ('words', 'chars', 'paragraphs')


async def text_regex_extract(text: str, pattern: str, default: str = '') -> str:
    r"""
    Извлекает из текста первую группу регулярного выражения.
    Если групп в выражении нет — возвращает все совпадение целиком.
    Если совпадения нет или выражение некорректно — значение default.
    Пример:
        text = "User: John Doe, Age: 30"
        pattern = r"Age: (\d+)"
        result = await text_regex_extract(text, pattern, default="N/A")
        # result будет "30"
    """
    try:
        match = re.search(str(pattern or ''), str(text or ''))
    except re.error:
        return str(default)

    if not match:
        return str(default)

    return match.group(1) if match.groups() else match.group(0)


async def text_regex_unknown(text: str, pattern: str, allowed: str,
                             separator: str = ',') -> dict:
    r"""
    Находит в тексте все совпадения с шаблоном и оставляет те, которых нет в списке
    разрешённых.

    Ответ на вопрос «какие метки в тексте самовольные». Регулярка ищет форму
    (`[[имя]]`, `{{имя}}`, `%имя%`), список задаёт допустимые имена — а лишним
    оказывается всё, что нашлось, но не разрешено.

    ⚠ Работа для кода, а не для LLM. Сверка «список против списка» требует пройти
    по каждому совпадению и сравнить, а модель на вопрос «все ли из списка?»
    отвечает утвердительно почти всегда: сверку она не делает, а «да» — вероятный
    ответ. Живая проверка: из четырёх писем три содержали выдуманные переменные, и
    все четыре получили от LLM-проверки «годится».

    Из совпадения берётся первая группа, если она есть, иначе всё совпадение
    целиком: `\[\[([a-z_]+)\]\]` даст `имя`, а `\[\[[a-z_]+\]\]` — `[[имя]]`.

     - text: где ищем.
     - pattern: чему должно соответствовать совпадение.
     - allowed: разрешённые значения через разделитель. Пусто — разрешено ничего,
       и все совпадения окажутся лишними.
     - separator: чем разделён список разрешённых.

    Пример:
        text = "Hi [[name]], I am from [[city]]"
        result = await text_regex_unknown(text, r"\[\[([a-z_]+)\]\]", "name,age")
        # result будет {"list": ["city"], "qty": 1, "str": "city", "found_qty": 2}

    Returns:
        A dictionary with the check result.
        list (list): Лишние значения, без повторов, в порядке появления.
        qty (int): Сколько их.
        str (str): Они же строкой через запятую — пусто, если лишних нет.
        found_qty (int): Сколько совпадений нашлось всего (0 — меток нет вовсе).
    """
    try:
        found = re.findall(str(pattern or ''), str(text or ''))
    except re.error:
        # Битый шаблон — не повод ронять workflow: считаем, что ничего не нашли.
        # Так же поступает `text_regex_extract`.
        return {"list": [], "qty": 0, "str": "", "found_qty": 0}

    # `findall` с одной группой отдаёт строки, с несколькими — кортежи. Берём
    # первую группу: остальные для этой задачи не значат ничего.
    names = [item[0] if isinstance(item, tuple) else item for item in found]
    names = [str(name).strip() for name in names if str(name).strip()]

    ok = {part.strip() for part in str(allowed or '').split(str(separator or ','))}
    ok.discard('')

    extra = []
    for name in names:
        if name not in ok and name not in extra:
            extra.append(name)

    return {"list": extra, "qty": len(extra), "str": ','.join(extra),
            "found_qty": len(names)}


async def text_marks_inline(text: str, names: str, separator: str = ',') -> dict:
    r"""
    Находит метки `[[имя]]`, встроенные в фразу, а не стоящие отдельным абзацем.

    Ответ на вопрос «эта метка заменится целой фразой — не окажется ли она внутри
    другой?». Метка, чьё значение само является предложением, обязана стоять
    отдельно: встроенная в текст, она даёт бессмыслицу вида
    «What are What kind of hobbies do you enjoy??».

    ⚠ Работа для кода. LLM это правило понимает через раз, а проверить его —
    сравнить строку с меткой, ничего больше.

    Отдельной считается строка, в которой кроме метки нет ничего, кроме пробелов.
    Знаки препинания рядом с меткой (`[[q]]?`) отдельной строкой **не** считаются:
    значение уже содержит свой знак.

     - text: где проверяем.
     - names: имена меток через разделитель. Пусто — проверять нечего.
     - separator: чем разделены имена.

    Пример:
        text = "Hi [[name]],\n\nWhat are [[question]]?\n\n[[other]]"
        result = await text_marks_inline(text, "question,other")
        # result будет {"list": ["question"], "qty": 1, "str": "question"}

    Returns:
        A dictionary with the check result.
        list (list): Имена, встроенные в фразу, в порядке появления.
        qty (int): Сколько их.
        str (str): Они же строкой через запятую; пусто — все стоят отдельно.
    """
    text = str(text or '')
    wanted = [part.strip() for part in str(names or '').split(str(separator or ','))]
    wanted = [part for part in wanted if part]

    # Строки, состоящие ровно из одной метки: по ним и судим.
    alone = {line.strip() for line in text.split('\n') if line.strip()}

    inline = []
    for name in wanted:
        mark = '[[%s]]' % name
        if mark in text and mark not in alone and name not in inline:
            inline.append(name)

    return {"list": inline, "qty": len(inline), "str": ','.join(inline)}


async def text_marks_missing(text: str, names: str, separator: str = ',') -> dict:
    r"""
    Находит метки `[[имя]]`, которых в тексте нет, хотя они обязаны быть.

    Ответ на вопрос «все ли обязательные метки на месте». Обратная сторона
    `text_regex_unknown`: та ловит самовольные метки, эта — пропущенные. Проверки
    разные, и одна другую не заменяет: текст с единственной верной меткой лишних
    не содержит и всё же никуда не годится.

    ⚠ Живая проверка, ради которой инструмент и появился: агента просили написать
    шаблон письма с тремя метками, а он вернул текст с одной. Вопрос получателю он
    написал словами — и письмо, задуманное разным для каждого, вышло бы для всех
    одинаковым. Проверка «нет ли лишних» это пропускала: лишних и правда не было.

     - text: где проверяем.
     - names: имена обязательных меток через разделитель. Пусто — проверять нечего.
     - separator: чем разделены имена.

    Пример:
        text = "Hi [[name]], nice to meet you"
        result = await text_marks_missing(text, "name,city,question")
        # result будет {"list": ["city", "question"], "qty": 2, "str": "city,question"}

    Returns:
        A dictionary with the check result.
        list (list): Имена, которых в тексте нет, в порядке списка.
        qty (int): Сколько их.
        str (str): Они же строкой через запятую; пусто — на месте все.
    """
    text = str(text or '')
    wanted = [part.strip() for part in str(names or '').split(str(separator or ','))]
    wanted = [part for part in wanted if part]

    missing = []
    for name in wanted:
        if '[[%s]]' % name not in text and name not in missing:
            missing.append(name)

    return {"list": missing, "qty": len(missing), "str": ','.join(missing)}


async def text_split(text: str, separator: str = ',') -> dict:
    """
    Разбивает текст по разделителю в массив строк.
    Пробелы по краям элементов обрезаются, пустые элементы отбрасываются.
    Пример:
        text = "node, user, companion"
        result = await text_split(text, separator=",")
        # result будет {"list": ["node", "user", "companion"], "qty": 3}
    Returns:
        A dictionary with the split result.
        list (list): Массив строк.
        qty (int): Количество элементов.
    """
    items = [part.strip() for part in str(text or '').split(str(separator or ','))]
    items = [part for part in items if part]
    return {"list": items, "qty": len(items)}


async def text_substr(text: str, substr: str, ignore_case: bool = False) -> dict:
    """
    Ищет подстроку в тексте: отдаёт позицию первого вхождения или признак «нет».

    Ответ на вопрос «встречается ли это слово в ответе модели и где именно».
    Поиск буквальный, по знакам — ни регулярок, ни границ слова: `substr` ищется
    как есть, и `кот` найдётся внутри `котлеты`.

    ⚠ Работа для кода, а не для LLM. «Есть ли в тексте эта фраза?» модель
    отвечает утвердительно почти всегда — сверку знак за знаком она не делает.

    ⚠⚠ Судить о находке в workflow — **по `found`, а не по `pos`**. Вхождение в
    самом начале строки даёт `pos = 0`, а условие на пустое значение считает ноль
    за «пусто» — и найденное прочитается как ненайденное. Отсюда и два ключа:
    `found` отвечает «есть ли», `pos` — «где».

     - text: где ищем.
     - substr: что ищем. Пусто — считаем, что искать нечего: `found = '0'`.
     - ignore_case: не различать прописные и строчные.

    Пример:
        text = "User: John Doe, Age: 30"
        result = await text_substr(text, "Age:")
        # result будет {"found": "1", "pos": 16}

    Returns:
        A dictionary with the search result.
        found (str): '1' — подстрока в тексте есть, '0' — нет.
        pos (int): Позиция первого вхождения, счёт с нуля; -1 — вхождения нет.
    """
    text = str(text if text is not None else '')
    substr = str(substr if substr is not None else '')

    # Пустую иглу `str.find` находит в любом стоге на позиции 0 — для workflow это
    # ложное «нашлось»: искать не просили ничего.
    if not substr:
        return {"found": '0', "pos": -1}

    if ignore_case:
        pos = text.lower().find(substr.lower())
    else:
        pos = text.find(substr)

    return {"found": '1' if pos >= 0 else '0', "pos": pos}


async def text_translit_cyr_to_lat(text: str) -> str:
    """
    Трансформация кириллицы в латиницу.

    Таблица общая (`i18n_translit_cyr`), позиционно-независимая, покрывает и
    украинские буквы, и русские.

    ⚠ Рядом в общем слое живёт `i18n_translit` — официальная украинская запись
    (КМУ № 55), и она даёт **другой** результат: Юрій → Yurii против Yuriy здесь.
    Переключать этот инструмент на неё нельзя: его выводом заводится имя агента
    (`agent.name`, уникальное), и смена буквы не найдёт заведённую запись, а
    создаст рядом вторую.
    """
    return i18n_translit_cyr(text)


async def text_cyrillic_has(text: str) -> dict:
    """
    Проверяет, есть ли в тексте кириллица: хоть один знак — да.

    Ответ на вопрос «модель ответила не на том языке?». Промпт просит ответ
    по-английски, а возвращается русский — знак кириллицы в тексте и есть
    дешёвый признак того, что строка поехала не туда. Дальше шаг перехода
    отправляет её на повтор.

    ⚠ Работа для кода, а не для LLM. «Это на английском?» модель отвечает
    утвердительно почти всегда — проверять собственный ответ ей нечем. Здесь
    же ответ однозначен: буква из блока есть или её нет.

    ⚠⚠ Это марка **алфавита, а не языка**. Кириллицей пишут и украинский, и
    болгарский, и казахский; и наоборот — в английском тексте человек может
    привести фамилию (`Толстой`), и кириллица там законна. Достаточно ли
    одного знака, чтобы браковать ответ, решает workflow, а не инструмент.

    ⚠ Проверяется весь блок `U+0400`–`U+04FF`, а не привычное `[а-яА-Я]`: в
    тот диапазон не входят ни `ё`, ни украинские `є і ї ґ`. Разбор и причины —
    `py_modules/text_/text_cyrillic.py`, шапка.

    Пример:
        text = "Спорю, ты сейчас улыбнулся"
        result = await text_cyrillic_has(text)
        # result будет {"has_cyrillic": "1"}

    Returns:
        A dictionary with the check result.
        has_cyrillic (str): '1' — кириллица в тексте есть, '0' — нет.
    """
    return {"has_cyrillic": '1' if text_cyrillic_has_check(text) else '0'}


async def text_length_range_check(text: str, length_range: str,
                                  unit: str = 'words') -> dict:
    """
    Проверяет, укладывается ли длина текста в заданную вилку.

    Ответ на вопрос «ответ вышел нужного размера?». Вилка задаётся строкой
    («20-30», «150–220») или одним числом («30» — не больше тридцати), мерить
    умеет слова, знаки и абзацы.

    Args:
        text: что меряем.
        length_range: вилка «мин-макс» либо одно число — верхняя граница.
            Пусто или неразборчиво — мерить не по чему, см. ниже.
        unit: `words` (по умолчанию), `chars` или `paragraphs`.

    Returns:
        A dictionary with the measurement result.
        fits (int): 1 — длина в вилке, 0 — вне её.
        length (int): сколько насчитали в этих единицах.
        why (str): претензия с числами для повторного захода; уложился —
            пустая строка.

    ## ⚠⚠ Зачем код там, где уже стоит судья

    Длину своего ответа LLM не меряет — она её оценивает, и промахивается в обе
    стороны. Счёт по живым отказам судьи писем (`dating_talk`, шаг «Валидация
    ответа»): «approximately 50 words, which exceeds the allowed 20–30» — о
    письме, которое в вилку укладывалось; «only 20 words… too short» — о письме
    при вилке ровно «20–30». Каждый промах стоит круга переписывания с вызовом
    модели, а кругов на письмо выходило 17.9 в среднем.

    Та же работа, что у `text_cyrillic_has` рядом: однозначный признак считает
    код, решение по нему принимает переход workflow, модель не участвует.

    ## ⚠⚠ Претензия по-английски — она едет в промпт, а не в журнал

    `why` кладут в переменную, которую генератор читает блоком «Judge's
    comment», и там уже английский текст судьи. Русская вставка в английском
    промпте — повод для модели ответить не на том языке, а язык ответа в
    письмах стерегут отдельным шагом.

    ⚠ Претензия **с числами**: «too short» модель исполняет как угодно, «the
    text has 52 words, but 20-30 are required» — однозначно.

    ## ⚠ Границы включительны

    «20-30» — это и ровно 20, и ровно 30. Человек, задавая вилку в жребии,
    имеет в виду именно это; исключи мы концы, каждая вилка молча сузилась бы
    на две длины.

    ## ⚠⚠ Нечем мерить — пропускаем, а не бракуем

    Пустая вилка, мусор вместо чисел, перевёрнутые границы — это поломка
    настройки, а не плохой текст. Верни мерка `fits = 0`, workflow ушёл бы на
    переписывание бесконечно, и каждый заход стоил бы вызова модели. Поэтому
    `fits = 1`, а причина лежит в `why` — её видно в трассе шага.

    ⚠ Пустой текст — случай обратный: это измеримая длина (ноль), и в вилку
    «20-30» она не попадает честно.

    Пример:
        await text_length_range_check('one two three', '2-4')
        # {'fits': 1, 'length': 3, 'why': ''}

        await text_length_range_check('one two three', '5-7')
        # {'fits': 0, 'length': 3,
        #  'why': 'the text has only 3 words, but 5-7 are required'}
    """
    measured = str(text or '')
    kind = str(unit or '').strip().lower()

    if kind not in TEXT_LENGTH_UNITS:
        kind = TEXT_LENGTH_UNITS[0]

    length = _length_of(measured, kind)
    low, high = _range_parse(length_range)

    if low is None:
        return {'fits': 1, 'length': length,
                'why': f'length range "{length_range}" is not readable, '
                       f'nothing to check against'}

    if low <= length <= high:
        return {'fits': 1, 'length': length, 'why': ''}

    shown = f'{low}-{high}' if low != high else f'{high}'
    side = 'only ' if length < low else ''

    return {'fits': 0, 'length': length,
            'why': f'the text has {side}{length} {kind}, '
                   f'but {shown} are required'}


async def text_to_lower(text: str) -> str:
    return text.lower()


async def text_to_upper(text: str) -> str:
    return text.upper()


def _length_of(text: str, unit: str) -> int:
    """Длина текста в заданных единицах."""
    if unit == 'chars':
        return len(text.strip())

    if unit == 'paragraphs':
        # ⚠ Считаем непустые строки, а не куски по «\n\n»: разделитель абзацев
        # в письмах бросается жребием и бывает одинарным переводом строки.
        # Пустые строки отбрасываются, поэтому оба разделителя дают одно число.
        return len([line for line in text.split('\n') if line.strip()])

    return len(text.split())


def _range_parse(length_range: str) -> tuple:
    """Вилка строкой → `(мин, макс)`; не разобрать — `(None, None)`.

    ⚠ Одно число — это **верхняя** граница («30» значит «не больше тридцати»),
    а не точная длина: так вилки и читают, задавая их словами.

    ⚠ Перевёрнутую вилку («30-20») не чиним перестановкой: опечатка в настройке
    должна быть видна, а не молча работать не тем, что написано.
    """
    given = str(length_range or '').strip()

    if not given:
        return None, None

    found = re.findall(rf'\d+\s*[{TEXT_RANGE_DASHES}]\s*\d+|\d+', given)

    if not found:
        return None, None

    parts = re.findall(r'\d+', found[0])

    if len(parts) == 1:
        return 0, int(parts[0])

    low, high = int(parts[0]), int(parts[1])

    if low > high:
        return None, None

    return low, high
