import httpx
from bs4 import BeautifulSoup


async def web_read_page(url: str) -> str:
    """
    Opens a URL and returns the text content of the page.
    Use this to get information from the internet.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Удаляем мусор (скрипты, стили)
            for script_or_style in soup(["script", "style", "header", "footer", "nav"]):
                script_or_style.decompose()

            # Получаем текст и убираем лишние пробелы
            text = soup.get_text(separator='\n')
            clean_text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

            # Ограничиваем объем, чтобы не превысить контекстное окно LLM
            return clean_text[:5000]
        except Exception as e:
            return f"Error reading page {url}: {str(e)}"

async def web_search(query: str, limit: int = 5, region: str = 'ua-uk') -> dict:
    """
    Ищет поисковую фразу в интернете (DuckDuckGo) в реальном времени.
    Используй для проверки фактов и поиска актуальной информации.
     - query: поисковая фраза
     - limit: количество результатов
     - region: регион поиска: 'ua-uk' (Украина), 'ru-ru', 'wt-wt' (весь мир)
    Returns:
        dict: Словарь с результатами поиска, содержащий:
            results (str): нумерованный список результатов (заголовок, ссылка, фрагмент).
            qty (int): количество найденных результатов.
    """
    import asyncio

    def _search() -> list[dict]:
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(str(query), region=region, max_results=int(limit)))

    try:
        rows = await asyncio.to_thread(_search)
    except Exception as e:
        return {"results": f"Ошибка поиска: {e}", "qty": 0}

    blocks = []
    for index, row in enumerate(rows, 1):
        blocks.append(f"{index}. {row.get('title', '')}\n{row.get('href', '')}\n{row.get('body', '')}")

    return {
        "results": "\n\n".join(blocks) if blocks else "Ничего не найдено",
        "qty": len(blocks)
    }
