from typing import List

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

cache: dict[str, List[str]] = {}


async def crawl4ai_parse_chunks_count(url: str, max_depth: int = 0) -> int:
    """
    Return the number of text chunks available for a given URL.
    This allows the LLM to know how many parts to read without exceeding token limits.
    """
    if url not in cache:
        chunks = []
        async for chunk in _crawl4ai_parse_by_url(url, max_depth):
            chunks.append(chunk)

        if not chunks:
            return 0
        cache[url] = chunks

    return len(cache[url])


async def crawl4ai_parse_by_url(url: str, chunk_index: int = 0) -> str:
    """
    Return a specific chunk of text content for a given URL.
    """
    # Авто-инициализация если LLM пропустила первый шаг
    if url not in cache:
        res = await crawl4ai_parse_chunks_count(url)
        if res == 0:
            return "Ошибка: Не удалось извлечь контент с сайта."

    chunks = cache.get(url, [])

    if 0 <= chunk_index < len(chunks):
        return chunks[chunk_index]

    return f"Ошибка: Индекс {chunk_index} вне диапазона. Всего кусков: {len(chunks)}"


async def _crawl4ai_parse_by_url(url: str, max_depth: int = 0):
    """
    Asynchronously crawls a website and extracts content, handling dynamic JavaScript loading.

    Args:
        url (str): Starting URL.
        max_depth (int): Depth for internal links (1 is usually enough for menus).
    """
    deep_crawl_strategy = BFSDeepCrawlStrategy(
        max_depth=max_depth,
        include_external=False,
        max_pages=50
    )

    # Добавляем ожидание появления элементов меню
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=['footer', 'header', 'nav', 'script', 'style', 'aside'],  # Убираем мусор
        # 'css:.menu-item' или другой селектор, характерный для этого сайта
        # Если не уверены, используем задержку в мс (например, 2000)
        wait_for="css:body",
        js_code="window.scrollTo(0, document.body.scrollHeight);",  # Прокрутка для ленивой загрузки
        stream=True
    )

    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun_many(
            urls=[url],
            deep_crawl_strategy=deep_crawl_strategy,
            config=run_config
        )

        buffer = ""
        chunk_size = 2000

        async for result in results:
            if result.success and result.markdown:
                clean_content = "\n".join([line for line in result.markdown.splitlines() if line.strip()])
                content = f"--- Source: {result.url} ---\n{clean_content}\n"
                buffer += content

                # Если в буфере накопилось больше 2000 символов — отдаем куски
                while len(buffer) >= chunk_size:
                    yield buffer[:chunk_size]
                    buffer = buffer[chunk_size:]

        # Отдаем остаток, если он есть
        if buffer:
            yield buffer

        pass
