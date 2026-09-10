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
