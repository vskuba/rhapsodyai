"""Мерки строки, которые модели не даются: длина против заданных границ.

## ⚠⚠ Зачем код там, где уже стоит судья

Длину своего ответа LLM не меряет — она её оценивает, и промахивается в обе
стороны. Счёт по живым отказам судьи писем (`dating_talk`, шаг «Валидация
ответа»): «approximately 50 words, which exceeds the allowed 20–30» — о письме,
которое в вилку укладывалось; «only 20 words… too short» — о письме при вилке
ровно «20–30». Каждый такой промах стоит полного круга переписывания, а кругов
на письмо выходило в среднем 17.9.

Поэтому мерка выносится к тому, кто считать умеет: однозначный признак считает
код, решение по нему принимает переход workflow, модель в этом не участвует.
"""
import re

# Разделители вилки: обычный дефис и оба типографских тире.
#
# ⚠ Тире здесь не прихоть: вилки жребия писем набраны именно коротким тире
# («20–30 words»), и инструмент, знающий один дефис, тихо не разобрал бы ни
# одной из них — то есть пропускал бы любую длину, выглядя рабочим.
STRING_RANGE_DASHES = '-‐‑‒–—−'

# Единицы длины, в которых умеем мерить.
STRING_LENGTH_UNITS = ('words', 'chars', 'paragraphs')


async def string_length_range_check(text: str, length_range: str,
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
    настройки, а не плохой текст. Верни инструмент `fits = 0`, workflow ушёл бы
    на переписывание бесконечно, и каждый заход стоил бы вызова модели.
    Поэтому `fits = 1`, а причина лежит в `why` — её видно в трассе шага.

    ⚠ Пустой текст — случай обратный: это измеримая длина (ноль), и в вилку
    «20-30» она не попадает честно.

    Пример:
        await string_length_range_check('one two three', '2-4')
        # {'fits': 1, 'length': 3, 'why': ''}

        await string_length_range_check('one two three', '5-7')
        # {'fits': 0, 'length': 3,
        #  'why': 'the text has only 3 words, but 5-7 are required'}
    """
    measured = str(text or '')
    kind = str(unit or '').strip().lower()

    if kind not in STRING_LENGTH_UNITS:
        kind = STRING_LENGTH_UNITS[0]

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

    found = re.findall(rf'\d+\s*[{STRING_RANGE_DASHES}]\s*\d+|\d+', given)

    if not found:
        return None, None

    parts = re.findall(r'\d+', found[0])

    if len(parts) == 1:
        return 0, int(parts[0])

    low, high = int(parts[0]), int(parts[1])

    if low > high:
        return None, None

    return low, high
