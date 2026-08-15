"""Пул браузера: один Chromium на контейнер, сессия — отдельный BrowserContext.

Почему контекст, а не отдельный браузер на сессию: контекст изолирует cookie,
localStorage и кэш полностью — сессии друг друга не видят, — но стоит единицы
мегабайт, тогда как процесс Chromium стоит ~150 МБ. Память съедают открытые
страницы, и ограничивать надо именно их число.

Состояние модульное, а не в классе: Chromium один на процесс, и контейнер этим
пулом и является. Реестр живёт в памяти — контейнер упал, значит и сессий больше
нет, и строка в БД говорила бы неправду до первой уборки.
"""

import asyncio
import time
import uuid

from playwright.async_api import async_playwright, Browser, Playwright

from config.config import config_get
from logging_.logging_ import logger_info

# Предел на число живых страниц. Ограничение не Chromium-а — он выдержит больше, —
# а `mem_limit: 4g` контейнера. Замер на 10 сессиях: сам браузер ~200 МБ, пустая
# сессия +14 МБ, статья Википедии +83 МБ. То есть 4 ГБ — это ~45 страниц такого
# веса, а страница чата (SPA живёт дольше и растёт) стоит вдвое дороже. 25 —
# половина расчётного максимума: запас на разрастание долгоживущих страниц.
# Меняется переменной, замерять — через `GET /browser/session`, там память.
BROWSER_POOL_SESSION_LIMIT = int(config_get('BROWSER_SESSION_LIMIT', '25'))

BROWSER_POOL_VIEWPORT_WIDTH = 1280
BROWSER_POOL_VIEWPORT_HEIGHT = 800
BROWSER_POOL_GOTO_TIMEOUT_MS = 30000

# `--disable-dev-shm-usage` здесь сознательно нет: он уводит Chromium с /dev/shm
# на диск и замедляет отрисовку. Ту же болезнь (64 МБ shm по умолчанию, на которых
# тяжёлая страница роняет вкладку) лечит `shm_size: 1gb` в compose — правильно.
BROWSER_POOL_LAUNCH_ARGS = [
    '--no-sandbox',  # контейнер изолирован сам, а user namespaces внутри него недоступны
    '--disable-gpu',
]

_playwright: Playwright | None = None
_browser: Browser | None = None
_sessions: dict[str, dict] = {}
_lock = asyncio.Lock()


async def browser_pool_start():
    """Поднимает Chromium. Зовётся один раз из lifespan контейнера."""
    global _playwright, _browser

    if _browser is not None:
        return

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True, args=BROWSER_POOL_LAUNCH_ARGS)
    logger_info(f'[browser] Chromium запущен: {_browser.version}, предел сессий {BROWSER_POOL_SESSION_LIMIT}')


async def browser_pool_stop():
    """Гасит все сессии и сам браузер."""
    global _playwright, _browser

    for session_id in list(_sessions):
        await browser_pool_session_close(session_id)

    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None

    logger_info('[browser] Chromium остановлен')


async def browser_pool_session_open(name: str = '', url: str = '', storage_state: dict | None = None,
                                    viewport: dict | None = None) -> dict:
    """Заводит сессию: свой контекст, одна страница в нём.

    `storage_state` — сохранённые cookie и localStorage прошлой сессии: с ним
    страница открывается уже авторизованной, без повторного прохода по форме входа.
    """
    if _browser is None:
        raise RuntimeError('браузер не запущен')

    async with _lock:
        if len(_sessions) >= BROWSER_POOL_SESSION_LIMIT:
            raise RuntimeError(f'предел сессий исчерпан: {BROWSER_POOL_SESSION_LIMIT}')

        session_id = uuid.uuid4().hex[:12]
        context = await _browser.new_context(
            viewport=viewport or {'width': BROWSER_POOL_VIEWPORT_WIDTH, 'height': BROWSER_POOL_VIEWPORT_HEIGHT},
            storage_state=storage_state,
        )
        page = await context.new_page()

        _sessions[session_id] = {
            'session_id': session_id,
            'name': name or session_id,
            'context': context,
            'page': page,
            'created_at': time.time(),
            'used_at': time.time(),
        }

    logger_info(f'[browser] сессия открыта: {session_id} ({name or "без имени"}), всего {len(_sessions)}')

    if url:
        await browser_pool_session_goto(session_id, url)

    return _session_info(_sessions[session_id])


async def browser_pool_session_close(session_id: str) -> bool:
    """Закрывает сессию. Возвращает False, если такой сессии не было."""
    async with _lock:
        entry = _sessions.pop(session_id, None)

    if entry is None:
        return False

    # Закрытие контекста закрывает и страницы в нём; падать на уже мёртвом
    # контексте (браузер уронил вкладку) незачем — запись из реестра уже снята.
    try:
        await entry['context'].close()
    except Exception as e:
        logger_info(f'[browser] сессия {session_id} закрыта с ошибкой: {e}')

    logger_info(f'[browser] сессия закрыта: {session_id}, осталось {len(_sessions)}')
    return True


def browser_pool_session_get(session_id: str) -> dict | None:
    """Внутренняя запись сессии (со страницей и контекстом) или None."""
    return _sessions.get(session_id)


def browser_pool_session_list() -> list[dict]:
    """Список сессий для API — без объектов Playwright."""
    return [_session_info(entry) for entry in _sessions.values()]


async def browser_pool_session_goto(session_id: str, url: str, wait_until: str = 'domcontentloaded',
                                    timeout_ms: int = BROWSER_POOL_GOTO_TIMEOUT_MS) -> dict:
    """Переводит страницу сессии на URL."""
    entry = _sessions.get(session_id)
    if entry is None:
        raise KeyError(session_id)

    page = entry['page']
    if page.is_closed():
        raise RuntimeError('страница сессии закрыта')

    await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
    entry['used_at'] = time.time()

    return {**_session_info(entry), 'title': await page.title()}


async def browser_pool_storage_state(session_id: str) -> dict:
    """Cookie и localStorage сессии — чтобы открыть следующую уже авторизованной."""
    entry = _sessions.get(session_id)
    if entry is None:
        raise KeyError(session_id)

    return await entry['context'].storage_state()


def browser_pool_stat() -> dict:
    """Сводка по пулу: запущен ли браузер и сколько сессий из предела занято."""
    return {
        'running': _browser is not None,
        'version': _browser.version if _browser is not None else '',
        'sessions': len(_sessions),
        'session_limit': BROWSER_POOL_SESSION_LIMIT,
    }


def _session_info(entry: dict) -> dict:
    """Запись сессии в виде, пригодном для JSON.

    `page.url` — свойство, а не запрос в браузер: список сессий не должен зависать
    на странице, которая занята своим JavaScript. По той же причине здесь нет
    `title()` — он уходит в браузер и ждёт ответа.
    """
    page = entry['page']
    now = time.time()

    return {
        'session_id': entry['session_id'],
        'name': entry['name'],
        'url': page.url,
        'alive': not page.is_closed(),
        'uptime_sec': round(now - entry['created_at']),
        'idle_sec': round(now - entry['used_at']),
        # Запись живёт прямо в записи сессии (кладёт её `browser_record`): так она
        # гаснет вместе с сессией сама и не заводит второй реестр, который пришлось
        # бы синхронизировать. Здесь — только факт «идёт запись», для кнопки в списке.
        'recording': entry.get('record') is not None,
    }
