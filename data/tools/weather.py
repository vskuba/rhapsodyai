import httpx


async def weather_get(city: str, days_offset: int = 0) -> str:
    """
    Get the weather forecast for a city.
    Args:
        city: City name.
        days_offset: 0 for today, 1 for tomorrow, 2 for the day after (max 6).
    """
    # 1. Geocoding
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"

    async with httpx.AsyncClient() as client:
        try:
            geo_resp = await client.get(geo_url)
            geo_data = geo_resp.json()

            if not geo_data.get('results'):
                return f"Error: City '{city}' not found."

            location = geo_data['results'][0]
            lat, lon = location['latitude'], location['longitude']

            # 2. Daily Forecast (поддерживает прогноз на несколько дней)
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,weathercode&timezone=auto"
            )

            weather_resp = await client.get(weather_url)
            w_json = weather_resp.json()

            # Выбираем день из списка daily (0 - сегодня, 1 - завтра и т.д.)
            idx = min(max(0, days_offset), 6)
            daily = w_json['daily']

            day_date = daily['time'][idx]
            t_max = daily['temperature_2m_max'][idx]
            t_min = daily['temperature_2m_min'][idx]

            label = "today" if days_offset == 0 else ("tomorrow" if days_offset == 1 else f"in {days_offset} days")

            return (
                f"Weather in {city} for {label} ({day_date}):\n"
                f"- Max Temp: {t_max}°C\n"
                f"- Min Temp: {t_min}°C\n"
                f"- Code: {daily['weathercode'][idx]}"
            )
        except Exception as e:
            return f"Error fetching forecast: {str(e)}"
