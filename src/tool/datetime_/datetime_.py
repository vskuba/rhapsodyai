import re
from datetime import datetime, timedelta, timezone as py_timezone


async def datetime_current_get(timezone: str = "0") -> str:
    """
    Возвращает текущую дату и время в текстовом формате на русском языке с учетом часового пояса.
    
    Args:
        timezone (str): Смещение часового пояса относительно UTC. Поддерживаются форматы: "+2", "-3", "UTC+2", "UTC-3", etc. Default "0".
    """
    try:
        # Парсим смещение часового пояса
        hours_offset = 0

        if timezone:
            clean_tz = timezone.strip().upper()
            # Ищем числовое смещение (с плюсом или минусом)
            match = re.search(r'([+-]?\d+)', clean_tz)
            if match:
                hours_offset = int(match.group(1))
        
        # Получаем текущее время UTC
        utc_now = datetime.now(py_timezone.utc)
        # Смещаем на hours_offset
        local_now = utc_now + timedelta(hours=hours_offset)
        
        # Формируем название дней недели на русском
        days_of_week = {
            0: "понедельник",
            1: "вторник",
            2: "среда",
            3: "четверг",
            4: "пятница",
            5: "суббота",
            6: "воскресенье"
        }
        
        # Формируем название месяцев на русском в родительном падеже
        months = {
            1: "января",
            2: "февраля",
            3: "марта",
            4: "апреля",
            5: "мая",
            6: "июня",
            7: "июля",
            8: "августа",
            9: "сентября",
            10: "октября",
            11: "ноября",
            12: "декабря"
        }
        
        day_of_week = days_of_week[local_now.weekday()]
        day = local_now.day
        month_name = months[local_now.month]
        year = local_now.year
        time_str = local_now.strftime("%H:%M:%S")

        # Описание временной зоны
        tz_desc = f"UTC{'+' if hours_offset >= 0 else ''}{hours_offset}"

        time_of_day = _time_of_day_describe(local_now.hour)

        result_text = f"Сегодня {day_of_week}, {day} {month_name} {year} года, точное время по {tz_desc}: {time_str} ({time_of_day})."
        return result_text
    except Exception as e:
        return f"Ошибка при получении времени: {str(e)}"


def _time_of_day_describe(hour: int) -> str:
    """Словесное описание времени суток по часу (0-23)."""
    if hour < 5:
        return "глубокая ночь"
    if hour < 7:
        return "раннее утро"
    if hour < 12:
        return "утро"
    if hour < 16:
        return "середина дня"
    if hour < 18:
        return "ближе к вечеру"
    if hour < 21:
        return "вечер"
    if hour < 23:
        return "поздний вечер"
    return "ночь"


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
