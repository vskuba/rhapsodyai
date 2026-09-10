"""Снимок веб-страницы для LLM — через контейнер-браузер, а не своим Chromium.

Инструмент тонкий намеренно. Раньше он поднимал **свой** `async_playwright` и свой
Chromium на каждый вызов: полторы сотни мегабайт и секунды старта ради одного
кадра, мимо пула сессий, который для того и заведён. Теперь кадр снимает
контейнер-браузер (`py_modules/browser_`), а здесь остаётся то, что делает его
инструментом: докстринг для модели и уборка сессии за собой.
"""

from src.uvicorn.routers.browser.browser_upstream import browser_upstream_request

# Сколько ждём снимок целиком: переход плюс кадр. Контейнер ждёт перехода до 30 с
# сам и отвечает на таймаут внятной 502 — здесь запас сверху, чтобы причина
# пришла оттуда, а не оборвалась безымянно тут.
WEB_SCREENSHOT_TIMEOUT = 90.0


async def web_screenshot(url: str, width: int = 1280, height: int = 800,
                         full_page: bool = False, selector: str = '') -> str:
    """
    Takes a screenshot of a web page and returns it as a `data:` image URI.

    Use to get a visual reference of a website's design, or to see what a page
    actually looks like right now.
     - url: full URL to screenshot (https://...)
     - width: viewport width in pixels (default 1280)
     - height: viewport height in pixels (default 800)
     - full_page: capture the whole scrollable page, not just the viewport
     - selector: capture only this element (CSS selector); empty means whole page
    Returns: `data:image/jpeg;base64,...` string, ready to pass to a vision model.
    """
    session_id = ''
    try:
        created = await browser_upstream_request(
            'POST', '/browser/session',
            {'name': 'снимок для агента', 'url': url,
             'viewport': {'width': int(width), 'height': int(height)}},
            timeout=WEB_SCREENSHOT_TIMEOUT)
        session_id = (created.get('session') or {}).get('session_id', '')

        shot = await browser_upstream_request(
            'POST', f'/browser/session/{session_id}/capture',
            {'selector': selector, 'full_page': bool(full_page)},
            timeout=WEB_SCREENSHOT_TIMEOUT)
    except Exception as e:
        # Инструмент возвращает ошибку строкой, а не бросает: модель должна
        # прочитать причину и решить, что делать дальше, — упавший вызов она
        # увидела бы как сбой всего шага (`tool_rules.md`).
        return f'Error taking screenshot of {url}: {e}'
    finally:
        # ⚠ Сессию гасим всегда. Она живёт в общем пуле с пределом на два десятка
        # страниц, и брошенная здесь висела бы до перезапуска контейнера — через
        # несколько вызовов пул кончился бы, и снимки перестали бы делаться вовсе.
        if session_id:
            try:
                await browser_upstream_request('DELETE', f'/browser/session/{session_id}')
            except Exception:
                pass

    if shot.get('error'):
        return f'Error taking screenshot of {url}: {shot["error"]}'

    return shot.get('image', '')
