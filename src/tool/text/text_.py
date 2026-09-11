import re

from i18n_.i18n_ import i18n_translit_cyr


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


async def text_to_lower(text: str) -> str:
    return text.lower()


async def text_to_upper(text: str) -> str:
    return text.upper()
