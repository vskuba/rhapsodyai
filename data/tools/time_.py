
from datetime import datetime


async def datetime_get() -> str:
    """
    Returns the current date and time as a string. Format: "YYYY-MM-DD HH:MM:SS".
    """
    return str(datetime.now())
