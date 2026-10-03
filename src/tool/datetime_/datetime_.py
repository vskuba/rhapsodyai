import re
from datetime import datetime, timedelta, timezone as py_timezone

# Язык, на котором отвечаем, если запрошенного нет в таблице.
#
# ⚠ Английский, а не русский: инструмент отдаёт текст **в промпт**, и фраза на
# чужом языке сбивает модель сильнее, чем кажется — она начинает отвечать на
# языке самой длинной подстановки. Английский в этой роли нейтрален.
DATETIME_LANGUAGE_DEFAULT = 'en'

# Часовые границы времени суток: до какого часа длится описание. Границы общие
# на все языки — переводятся слова, а не распорядок дня.
#
# ⚠ Пары идут по возрастанию и читаются первой подходящей; последняя строка
# закрывает остаток суток, поэтому её граница — 24.
DATETIME_DAY_PARTS = (5, 7, 12, 16, 18, 21, 23, 24)

# Слова на каждом языке. Добавить четвёртый — дописать блок, код не трогать.
#
# ⚠ `months` у русского и украинского в **родительном** падеже («3 октября»),
# у английского — в именительном: там месяц стоит перед числом («October 3»).
# Отсюда и разные шаблоны: одним порядком слов три языка не обслужить.
#
# ⚠ `parts` — ровно столько слов, сколько границ в `DATETIME_DAY_PARTS`, и в том
# же порядке. Разойдутся — время суток станет отвечать не про тот час.
DATETIME_LANGUAGES = {
    'en': {
        'days': ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                 'Saturday', 'Sunday'),
        'months': ('January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November',
                   'December'),
        'parts': ('deep night', 'early morning', 'morning', 'midday',
                  'late afternoon', 'evening', 'late evening', 'night'),
        'template': ('Today is {day_of_week}, {month} {day}, {year}, '
                     'exact time at {tz}: {time} ({part}).'),
        'error': 'Failed to get the time: {error}',
    },
    'ru': {
        'days': ('понедельник', 'вторник', 'среда', 'четверг', 'пятница',
                 'суббота', 'воскресенье'),
        'months': ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                   'июля', 'августа', 'сентября', 'октября', 'ноября',
                   'декабря'),
        'parts': ('глубокая ночь', 'раннее утро', 'утро', 'середина дня',
                  'ближе к вечеру', 'вечер', 'поздний вечер', 'ночь'),
        'template': ('Сегодня {day_of_week}, {day} {month} {year} года, '
                     'точное время по {tz}: {time} ({part}).'),
        'error': 'Ошибка при получении времени: {error}',
    },
    'uk': {
        'days': ('понеділок', 'вівторок', 'середа', 'четвер', 'п’ятниця',
                 'субота', 'неділя'),
        'months': ('січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
                   'липня', 'серпня', 'вересня', 'жовтня', 'листопада',
                   'грудня'),
        'parts': ('глупа ніч', 'ранній ранок', 'ранок', 'середина дня',
                  'ближче до вечора', 'вечір', 'пізній вечір', 'ніч'),
        'template': ('Сьогодні {day_of_week}, {day} {month} {year} року, '
                     'точний час за {tz}: {time} ({part}).'),
        'error': 'Помилка отримання часу: {error}',
    },
}


async def datetime_current_get(timezone: str = "0",
                               language: str = DATETIME_LANGUAGE_DEFAULT) -> str:
    """
    Возвращает текущую дату и время словами, с учётом часового пояса и языка.

    Отвечает на вопрос «какое сейчас время у собеседника» — для промпта, а не
    для вычислений. Поэтому текст, а не метка: модели нужно знать, что сейчас
    поздний вечер пятницы, чтобы не писать «доброе утро».

    Args:
        timezone (str): Смещение часового пояса относительно UTC. Поддерживаются
            форматы: "+2", "-3", "UTC+2", "UTC-3". Default "0".
        language (str): Язык ответа — 'en', 'ru' или 'uk'. Незнакомый язык и
            пусто дают английский. Default 'en'.

    Returns:
        str: Например «Today is Friday, October 3, 2026, exact time at UTC+3:
        21:35:12 (late evening).»

    ⚠ Язык меняет и слова, и порядок: у английского месяц стоит перед числом
    («October 3»), у русского и украинского — после, в родительном падеже
    («3 октября»). Поэтому у каждого языка свой шаблон, а не общая склейка.

    ⚠ Время суток описывается словами («поздний вечер»), а не только цифрами:
    час `23:40` модель читает как число, а «поздний вечер» — как обстановку.

    ⚠ Не бросает: сбой разбора пояса отдаёт строку с ошибкой на том же языке.
    Шаг workflow не должен падать из-за часового пояса.
    """
    words = DATETIME_LANGUAGES.get(
        str(language or '').strip().lower(),
        DATETIME_LANGUAGES[DATETIME_LANGUAGE_DEFAULT])

    try:
        # Парсим смещение часового пояса
        hours_offset = 0

        if timezone:
            clean_tz = timezone.strip().upper()
            # Ищем числовое смещение (с плюсом или минусом)
            match = re.search(r'([+-]?\d+)', clean_tz)
            if match:
                hours_offset = int(match.group(1))

        # Получаем текущее время UTC и смещаем на hours_offset
        utc_now = datetime.now(py_timezone.utc)
        local_now = utc_now + timedelta(hours=hours_offset)

        return words['template'].format(
            day_of_week=words['days'][local_now.weekday()],
            day=local_now.day,
            month=words['months'][local_now.month - 1],
            year=local_now.year,
            tz=f"UTC{'+' if hours_offset >= 0 else ''}{hours_offset}",
            time=local_now.strftime("%H:%M:%S"),
            part=_time_of_day_describe(local_now.hour, words),
        )
    except Exception as e:
        return words['error'].format(error=str(e))


def _time_of_day_describe(hour: int, words: dict) -> str:
    """Словесное описание времени суток по часу (0-23), на языке `words`."""
    for edge, part in zip(DATETIME_DAY_PARTS, words['parts']):
        if hour < edge:
            return part

    # Сюда не дойти: последняя граница закрывает сутки целиком. Строка есть на
    # случай правки таблицы — молчаливый `None` в промпте искать дороже.
    return words['parts'][-1]


def _utc_now_str(timezone_offset: str = "+0") -> str:
    """
    Возвращает текущее время в UTC+offset в формате 'YYYY-MM-DD HH:MM:SSZ'.

    Args:
        timezone_offset: Смещение относительно UTC. Поддерживаются форматы: '+0', '+3', '-5', '+05:30'. Default '+0'.
    """
    try:
        # Парсим знак, часы и опциональные минуты:
        # '+0' → 0ч, '+3' → 3ч, '+05:30' → 5.5ч, '-05:30' → -5.5ч, '+0530' → 5.5ч
        match = re.search(r'([+-])(\d+):(\d{1,2})', str(timezone_offset))
        if not match:
            match = re.search(r'([+-])(\d{2})(\d{2})', str(timezone_offset))
        if not match:
            match = re.search(r'([+-])(\d+)', str(timezone_offset))
        if match:
            sign = 1 if match.group(1) == '+' else -1
            hours = int(match.group(2))
            minutes = int(match.group(3)) if len(match.groups()) >= 3 and match.group(3) else 0
            hours_offset = sign * (hours + minutes / 60)
        else:
            hours_offset = 0

        # Текущее время UTC, смещённое на заданный часовой пояс
        utc_now = datetime.now(py_timezone.utc)
        local_now = utc_now + timedelta(hours=hours_offset)

        return local_now.strftime("%Y-%m-%d %H:%M:%S") + "Z"
    except Exception:
        # Fallback: простой UTC
        return datetime.now(py_timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z"
