import json


async def dict_column(data: list, column_name: str):
    """
    Возвращает значения по ключу column_name из данных.
    data — список словарей (вернется список значений по ключу из каждой записи),
    словарь (вернется значение ключа) или JSON-строка одного из этих видов.
    Пустые/невалидные данные — пустая строка.
    """
    if data is None or data == '':
        return ''

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return ''

    if isinstance(data, dict):
        value = data.get(column_name)
        return '' if value is None else value

    if isinstance(data, list):
        return [row.get(column_name) for row in data if isinstance(row, dict)]

    return ''


async def dict_fields_check(data, keys: str, separator: str = ',') -> dict:
    """
    Проверяет, что в словаре заполнены все требуемые ключи, и отдаёт его строкой.

    Ответ на вопрос «годится ли то, что вернула LLM». Ключ считается незаполненным,
    если его нет вовсе или значение пустое (пустая строка, пробелы, None). Лишние
    ключи в счёт не идут: их отбрасывает вызывающая сторона.

    ⚠ Работа для кода, а не для LLM. Спрашивать у модели, всё ли она заполнила, —
    значит просить её проверить саму себя: на вопрос «все ли поля на месте?» она
    отвечает утвердительно почти всегда.

    Сериализация здесь же, а не отдельным инструментом, намеренно: результат
    проверки и сам словарь нужны одному и тому же шагу — первый решает, повторять
    ли, второй уходит в ответ. Два вызова ради одного разбора JSON — работа
    впустую.

     - data: словарь или JSON-строка с ним.
     - keys: требуемые ключи через разделитель. Пусто — требований нет, и пустым
       окажется только сам результат проверки.
     - separator: чем разделены ключи.

    Пример:
        data = {"girl_name": "Diana", "girl_city": ""}
        result = await dict_fields_check(data, "girl_name,girl_city,girl_job")
        # result будет {"empty": "girl_city,girl_job", "empty_qty": 2,
        #               "filled_qty": 1, "json": "{\"girl_name\": \"Diana\"}"}

    Returns:
        A dictionary with the check result.
        empty (str): Незаполненные ключи через запятую; пусто — все на месте.
        empty_qty (int): Сколько их.
        filled_qty (int): Сколько заполнено.
        json (str): Словарь строкой — **только заполненные ключи**, чтобы пустые
            значения не уехали в подстановку.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            data = None

    if not isinstance(data, dict):
        data = {}

    wanted = [part.strip() for part in str(keys or '').split(str(separator or ','))]
    wanted = [part for part in wanted if part]

    filled, empty = {}, []
    for key in wanted:
        value = data.get(key)
        text = '' if value is None else str(value).strip()
        if text:
            filled[key] = text
        else:
            empty.append(key)

    return {"empty": ','.join(empty), "empty_qty": len(empty),
            "filled_qty": len(filled),
            "json": json.dumps(filled, ensure_ascii=False)}
