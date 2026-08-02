import asyncio
import base64


async def web_screenshot(url: str, width: int = 1280, height: int = 800) -> str:
    """
    Takes a screenshot of a web page and returns base64-encoded PNG.
    Use to get visual reference of a website's design.
     - url: full URL to screenshot (https://...)
     - width: viewport width in pixels (default 1280)
     - height: viewport height in pixels (default 800)
    Returns: base64-encoded PNG string
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={'width': width, 'height': height})
            await page.goto(url, wait_until='networkidle', timeout=30000)
            screenshot_bytes = await page.screenshot(type='png', full_page=False)
            return base64.b64encode(screenshot_bytes).decode('utf-8')
        except Exception as e:
            return f"Error taking screenshot of {url}: {e}"
        finally:
            await browser.close()
