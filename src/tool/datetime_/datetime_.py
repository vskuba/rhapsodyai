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
        
        result_text = f"Сегодня {day_of_week}, {day} {month_name} {year} года, точное время по {tz_desc}: {time_str}."
        return result_text
    except Exception as e:
        return f"Ошибка при получении времени: {str(e)}"
