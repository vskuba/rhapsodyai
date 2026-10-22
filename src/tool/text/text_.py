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


async def text_paragraph_has(text: str, needle: str) -> dict:
    r"""
    Стоит ли кусок `needle` в тексте отдельным абзацем — и стоит ли вообще.

    Отвечает на вопрос «эта вставка не окажется ли внутри чужой фразы?». Нужен
    там, где подставляемое значение само является предложением: встроенное в
    текст, оно даёт бессмыслицу вида «What are What kind of hobbies do you
    enjoy??».

    ⚠ Работа для кода. LLM это правило понимает через раз, а проверить его —
    сравнить строку с куском, ничего больше. Замер на 506 прогонах шаблонов
    писем: модель ставила такую вставку внутрь фразы в 90 случаях, то есть
    почти в каждом пятом, **при том что промпт просил обратного**.

    ## ⚠⚠ Три ответа, а не один, потому что случая три

    «Нет вовсе» и «есть, но внутри фразы» — разные беды с разным лечением, и
    сливать их в одно «не стоит отдельно» нельзя: первую чинит «впиши вставку»,
    вторую — «вынеси её в свой абзац». Вызывающий выбирает, что его волнует.

    Отдельным абзацем считается строка, в которой кроме куска нет ничего, кроме
    пробелов. Знаки препинания рядом (`[[q]]?`) отдельной строкой **не**
    считаются: значение уже содержит свой знак.

     - text: где смотрим.
     - needle: что ищем — любой кусок текста, не обязательно метка.

    Пример:
        text = "Hi there,\n\nWhat are [[q]]?\n\n[[other]]"
        result = await text_paragraph_has(text, "[[q]]")
        # result будет {"found": 1, "alone": 0, "inline": 1}

    Returns:
        A dictionary with the check result.
        found (int): 1 — кусок в тексте есть, 0 — нет вовсе.
        alone (int): 1 — есть и стоит отдельным абзацем.
        inline (int): 1 — есть, но внутри фразы. Ради него всё и затевалось.
    """
    text = str(text or '')
    needle = str(needle or '').strip()

    # ⚠ Пустой кусок — не «нашёлся везде», а «искать нечего». `'' in text` даёт
    # истину всегда, и без этой ветки пустой довод отвечал бы «всё в порядке».
    if not needle:
        return {"found": 0, "alone": 0, "inline": 0}

    found = needle in text
    alone = any(line.strip() == needle for line in text.split('\n'))

    return {"found": int(found),
            "alone": int(alone),
            "inline": int(found and not alone)}


async def text_substr_missing(text: str, items: str, separator: str = ',',
                              ignore_case: bool = False) -> dict:
    r"""
    Находит, каких кусков из списка в тексте нет.

    Множественный `text_substr`: тот отвечает про один кусок, этот — про список,
    и возвращает **недостающие**. Ответ на вопрос «всё ли обязательное на месте».

    ⚠ Поиск буквальный, по знакам — ни регулярок, ни границ слова, как и у
    `text_substr`: `кот` найдётся внутри `котлеты`.

    ⚠ Работа для кода, а не для LLM. Сверка «список против текста» требует
    пройти по каждому куску, а модель на вопрос «все ли на месте?» отвечает
    утвердительно почти всегда. Живая проверка, ради которой инструмент и
    появился: агента просили написать шаблон письма с тремя вставками, а он
    вернул текст с одной — вопрос получателю написал словами, и письмо,
    задуманное разным для каждого, вышло бы для всех одинаковым. Замер на 601
    прогоне: недостача нашлась в 220 случаях, то есть в каждом третьем.

    ⚠⚠ Ищутся **куски как есть**, а не имена чего-либо: обрамление задаёт
    вызывающий. Прежний `text_marks_missing` клеил скобки сам
    (`'[[%s]]' % name`) и этим знал про чужой предмет — про «метки письма».
    Здесь предмета нет: список может быть каким угодно.

     - text: где проверяем.
     - items: куски через разделитель. Пусто — проверять нечего.
     - separator: чем разделены куски.
     - ignore_case: не различать прописные и строчные.

    Пример:
        text = "Hi [[name]], nice to meet you"
        result = await text_substr_missing(text, "[[name]],[[city]]")
        # result будет {"list": ["[[city]]"], "qty": 1, "str": "[[city]]"}

    Returns:
        A dictionary with the check result.
        list (list): Куски, которых в тексте нет, в порядке списка.
        qty (int): Сколько их.
        str (str): Они же строкой через разделитель; пусто — на месте все.
    """
    text = str(text or '')
    wanted = [part.strip() for part in str(items or '').split(str(separator or ','))]
    wanted = [part for part in wanted if part]

    where = text.lower() if ignore_case else text

    missing = []
    for one in wanted:
        needle = one.lower() if ignore_case else one
        if needle not in where and one not in missing:
            missing.append(one)

    return {"list": missing, "qty": len(missing),
            "str": str(separator or ',').join(missing)}


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


async def text_chunk_unique(text: str, separator: str = ',',
                      ignore_case: bool = False) -> dict:
    """
    Убирает повторы из текста, разрезанного разделителем, и склеивает обратно.

    Ответ на вопрос «не повторяется ли что-то в этом списке». Разрезает по
    `separator`, выбрасывает повторные вхождения, склеивает тем же разделителем.

    ⚠⚠ Остаётся **первое** вхождение, порядок прочих не меняется. Иначе текст
    перетасовался бы: у нумерованного списка сбилась бы нумерация, у пачки
    реплик — соответствие «строка N — приём N».

    ⚠ Сравнение буквальное, знак в знак. Перефразированный повтор («I bet
    you're trouble» против «You look like trouble») для него разный текст: это
    другая задача и другая цена, здесь её нет намеренно.

     - text: что чистим.
     - separator: чем разрезано — им же склеивается обратно. Пустой
       разделитель резать нечем: текст возвращается как есть одним элементом.
     - ignore_case: не различать прописные и строчные при сравнении. На сам
       текст не влияет — в ответе остаётся исходное написание первого вхождения.

    Пример:
        text = "да---нет---да"
        result = await text_chunk_unique(text, separator="---")
        # result будет {"str": "да---нет", "list": ["да", "нет"],
        #               "qty": 2, "dropped": 1}

    Returns:
        A dictionary with the cleaned text.
        str (str): Текст без повторов, склеенный тем же разделителем.
        list (list): Он же массивом — первые вхождения, в исходном порядке.
        qty (int): Сколько элементов осталось.
        dropped (int): Сколько повторов выброшено. Ноль — чистить было нечего.
    """
    # ⚠⚠ Пустые элементы отбрасываются, края обрезаются — то же, что делает
    # соседний `text_split`. Инструменты, режущие один и тот же текст, обязаны
    # резать его одинаково: разойдись они, `qty` у них перестали бы сходиться.
    line = str(separator) if separator else ''
    parts = str(text or '').split(line) if line else [str(text or '')]
    parts = [one.strip() for one in parts]
    parts = [one for one in parts if one]

    seen, kept = set(), []

    for one in parts:
        mark = one.lower() if ignore_case else one

        if mark in seen:
            continue

        seen.add(mark)
        kept.append(one)

    return {"str": line.join(kept), "list": kept, "qty": len(kept),
            "dropped": len(parts) - len(kept)}


async def text_substr(text: str, substr, ignore_case: bool = False,
                      limit: int = 1) -> dict:
    """
    Ищет подстроку в тексте: позиция первого вхождения, признак «нет» и счёт.

    Ответ на вопрос «встречается ли это слово в ответе модели, где именно и
    сколько раз». Поиск буквальный, по знакам — ни регулярок, ни границ слова:
    `substr` ищется как есть, и `кот` найдётся внутри `котлеты`.

    ⚠ Работа для кода, а не для LLM. «Есть ли в тексте эта фраза?» модель
    отвечает утвердительно почти всегда — сверку знак за знаком она не делает.

    ⚠⚠ Судить о находке в workflow — **по `found`, а не по `pos`**. Вхождение в
    самом начале строки даёт `pos = 0`, а условие на пустое значение считает ноль
    за «пусто» — и найденное прочитается как ненайденное. Отсюда и ключи:
    `found` отвечает «есть ли», `pos` — «где», `qty` — «сколько».

    ## ⚠⚠ Массив на входе — массив на выходе

    Передали список подстрок — вернётся список ответов, по одному на каждую, в
    том же порядке и с самой подстрокой в ответе. Так одним шагом проверяется
    целый набор, а не заводится шаг на каждую подстроку.

    Живой случай, ради которого счёт и список появились: агент письма написал
    имя переменной **без скобок** — «companion_name, the kettle clicked off»
    вместо `[[companion_name]]`. Такое письмо уходит как есть, и прежние
    проверки его не видели: регулярка ищет только `[[…]]`, а поиск по голому
    имени находит его и внутри метки.

    Ловится **парой счётов**: сколько раз имя встречается голым и сколько — в
    скобках. Числа обязаны совпасть, потому что каждое вхождение имени должно
    быть внутри метки; разошлись — метка оформлена неверно, и по списку сразу
    видно какая.

     - text: где ищем.
     - substr: что ищем — строка либо список строк. Пусто — искать нечего:
       `found = '0'`.
     - ignore_case: не различать прописные и строчные.
     - limit: сколько вхождений считать, дальше не ищем. `0` — считать все.
       Умолчание `1` бережёт время: обычно спрашивают «есть или нет», и на
       длинном тексте полный счёт ради этого был бы лишней работой.

    Пример:
        text = "User: John Doe, Age: 30"
        result = await text_substr(text, "Age:")
        # result будет {"found": "1", "pos": 16, "qty": 1}

        result = await text_substr(text, ["Age:", "City:"], limit=0)
        # result будет {"list": [{"substr": "Age:", ...}, {...}], "qty": 2}

    Returns:
        A dictionary with the search result.
        found (str): '1' — подстрока в тексте есть, '0' — нет.
        pos (int): Позиция первого вхождения, счёт с нуля; -1 — вхождения нет.
        qty (int): Сколько вхождений найдено, не больше `limit`.

        Для списка — `list` с такими же словарями (плюс `substr` в каждом) и
        `qty` с их количеством.
    """
    text = str(text if text is not None else '')

    # ⚠ Список — отвечаем списком, по ответу на каждую подстроку. Порядок тот же,
    # что пришёл, и сама подстрока лежит в ответе: вызывающий читает его, не
    # сверяясь со своим списком по месту.
    if isinstance(substr, (list, tuple)):
        found = []
        for one in substr:
            got = await text_substr(text, one, ignore_case, limit)
            found.append({'substr': str(one if one is not None else ''), **got})

        return {"list": found, "qty": len(found)}

    substr = str(substr if substr is not None else '')

    # Пустую иглу `str.find` находит в любом стоге на позиции 0 — для workflow это
    # ложное «нашлось»: искать не просили ничего.
    if not substr:
        return {"found": '0', "pos": -1, "qty": 0}

    stog = text.lower() if ignore_case else text
    igla = substr.lower() if ignore_case else substr

    # ⚠ Число приходит workflow-переменной, то есть строкой, и бывает пустым.
    try:
        take = int(limit or 0)
    except (TypeError, ValueError):
        take = 1

    # ⚠ Считаем **непересекающиеся** вхождения, как `str.count`: иначе «аа» в
    # «ааа» дало бы два, и счёт перестал бы отвечать на вопрос «сколько раз это
    # написано».
    pos = stog.find(igla)
    qty = 0
    at = pos
    while at >= 0 and (take <= 0 or qty < take):
        qty += 1
        at = stog.find(igla, at + len(igla))

    return {"found": '1' if pos >= 0 else '0', "pos": pos, "qty": qty}


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


# ## ⚠⚠ Зачем код там, где уже стоит судья
#
# Длину своего ответа LLM не меряет — она её оценивает, и промахивается в обе
# стороны. Счёт по живым отказам судьи писем (`dating_talk`, шаг «Валидация
# ответа»): «approximately 50 words, which exceeds the allowed 20–30» — о
# письме, которое в вилку укладывалось; «only 20 words… too short» — о письме
# при вилке ровно «20–30». Каждый промах стоит круга переписывания с вызовом
# модели, а кругов на письмо выходило 17.9 в среднем.
#
# Та же работа, что у соседнего `text_cyrillic_has`: однозначный признак
# считает код, решение по нему принимает переход workflow, модель не участвует.
#
# ## ⚠⚠ Претензия по-английски — она едет в промпт, а не в журнал
#
# `why` кладут в переменную, которую генератор читает блоком «Judge's comment»,
# и там уже английский текст судьи. Русская вставка в английском промпте — повод
# для модели ответить не на том языке, а язык ответа в письмах стерегут
# отдельным шагом. Претензия **с числами**: «too short» модель исполняет как
# угодно, «the text has 52 words, but 20-30 are required» — однозначно.
#
# ## ⚠⚠ Нечем мерить — пропускаем, а не бракуем
#
# Пустая вилка, мусор вместо чисел, перевёрнутые границы — это поломка
# настройки, а не плохой текст. Верни мерка `fits = 0`, workflow ушёл бы на
# переписывание бесконечно, и каждый заход стоил бы вызова модели. Поэтому
# `fits = 1`, а причина лежит в `why` — её видно в трассе шага. Пустой текст —
# случай обратный: это измеримая длина (ноль), и в вилку «20-30» она не
# попадает честно.
#
# ⚠ Докстринг ниже короткий намеренно: он уезжает в базу и показывается
# человеку в панели шага. Там нужно «что делает», а не рассуждение — его место
# здесь.
async def text_length_range_check(text: str, length_range: str,
                                  unit: str = 'words') -> dict:
    """
    Проверяет, укладывается ли длина текста в заданную вилку.

    Ответ на вопрос «ответ вышел нужного размера?». Мерить умеет слова, знаки и
    абзацы. Границы включительны: «20-30» — это и ровно 20, и ровно 30.

    Args:
        text: что меряем. Пусто — это длина ноль, и в вилку она честно не
            попадает.
        length_range: вилка «мин-макс» («20-30», «150–220») либо одно число
            («30» — не больше тридцати). Пусто или неразборчиво — мерить не по
            чему: текст пропускается, причина кладётся в `why`.
        unit: `words` (по умолчанию), `chars` или `paragraphs`.

    Returns:
        A dictionary with the measurement result.
        fits (int): 1 — длина в вилке, 0 — вне её.
        length (int): сколько насчитали в этих единицах.
        why (str): претензия с числами для повторного захода, по-английски —
            она едет в промпт; уложился — пустая строка.

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
