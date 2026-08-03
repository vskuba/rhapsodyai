import asyncio

from fastapi import APIRouter, Request, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()

_browser_sessions: dict[int, dict] = {}  # user_id → {page, playwright, browser, last_used}
_browser_lock = asyncio.Lock()
_BROWSER_TTL = 300


async def _browser_session_get(user_id: int):
    from playwright.async_api import async_playwright
    import time

    async with _browser_lock:
        session = _browser_sessions.get(user_id)
        if session:
            try:
                await session['page'].title()
                session['last_used'] = time.time()
                return session['page']
            except Exception:
                try:
                    await session['browser'].close()
                except Exception:
                    pass
                try:
                    await session['playwright'].stop()
                except Exception:
                    pass
                del _browser_sessions[user_id]

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 1200})
        _browser_sessions[user_id] = {
            'playwright': pw, 'browser': browser, 'page': page,
            'last_used': time.time(),
        }
        return page


async def _browser_session_close(user_id: int):
    async with _browser_lock:
        session = _browser_sessions.pop(user_id, None)
        if session:
            try:
                await session['browser'].close()
            except Exception:
                pass
            try:
                await session['playwright'].stop()
            except Exception:
                pass


async def _page_screenshot_b64(page) -> str:
    import base64
    try:
        cdp = await page.context.new_cdp_session(page)
        result = await cdp.send('Page.captureScreenshot', {'format': 'png'})
        await cdp.detach()
        return result['data']
    except Exception:
        shot = await page.screenshot(type='png', full_page=False, timeout=5000)
        return base64.b64encode(shot).decode('utf-8')


async def _page_scroll_info(page) -> dict:
    try:
        return await page.evaluate("""() => ({
            scrollX: Math.round(window.scrollX),
            scrollY: Math.round(window.scrollY),
            scrollWidth:  document.documentElement.scrollWidth,
            scrollHeight: document.documentElement.scrollHeight,
            viewportW: window.innerWidth,
            viewportH: window.innerHeight,
        })""")
    except Exception:
        return {}


async def _maybe_resize_viewport(page, data: dict) -> None:
    w = int(data.get('viewW', 0))
    h = int(data.get('viewH', 0))
    if w < 200 or h < 200:
        return
    vp = page.viewport_size
    if not vp or vp['width'] != w or vp['height'] != h:
        await page.set_viewport_size({'width': w, 'height': h})


async def _browser_history_save(project_id: int, url: str):
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO project_design_prototype_browser_history (project_id, url, used_at)'
                ' VALUES (%s, %s, NOW())'
                ' ON DUPLICATE KEY UPDATE used_at = NOW()',
                (project_id, url[:2048])
            )
            await db.execute(
                'DELETE FROM project_design_prototype_browser_history'
                ' WHERE project_id = %s AND id NOT IN ('
                '   SELECT id FROM ('
                '     SELECT id FROM project_design_prototype_browser_history'
                '     WHERE project_id = %s ORDER BY used_at DESC LIMIT 15'
                '   ) t'
                ')',
                (project_id, project_id)
            )
    except Exception:
        pass


_PICK_ELEMENT_JS = """
(coords) => {
    const {x, y, w, h} = coords;
    const cx = x + w / 2, cy = y + h / 2;
    let el = document.elementFromPoint(cx, cy);
    if (!el) return null;

    const BLOCK = new Set(['DIV','SECTION','ARTICLE','HEADER','FOOTER','MAIN','NAV',
                           'ASIDE','UL','OL','TABLE','FIGURE','FORM']);
    while (el.parentElement && !BLOCK.has(el.tagName) && el !== document.body) {
        el = el.parentElement;
    }

    const usedSelectors = new Set();
    try {
        for (const sheet of document.styleSheets) {
            let rules;
            try { rules = sheet.cssRules || sheet.rules; } catch(e) { continue; }
            for (const rule of rules) {
                if (rule.selectorText) {
                    try {
                        if (el.matches(rule.selectorText) || el.querySelector(rule.selectorText)) {
                            usedSelectors.add(rule.cssText);
                        }
                    } catch(e) {}
                }
            }
        }
    } catch(e) {}

    const computed = window.getComputedStyle(el);
    const inlineProps = ['color','background-color','background','font-family','font-size',
        'font-weight','border-radius','padding','margin','display','flex-direction',
        'align-items','justify-content','gap','width','max-width','min-height',
        'border','box-shadow','line-height','text-align'];
    const inlineStyle = inlineProps
        .map(p => `${p}:${computed.getPropertyValue(p)}`)
        .join(';');

    return {
        html: el.outerHTML,
        css: [...usedSelectors].join('\\n'),
        inline_style: inlineStyle,
        tag: el.tagName.toLowerCase(),
        classes: el.className,
        selector: el.id ? '#' + el.id : (el.className ? '.' + el.className.trim().split(/\\s+/)[0] : el.tagName.toLowerCase()),
    };
}
"""


@router.get('/planning/browser/history/{project_id}')
async def planning_browser_history_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT url FROM project_design_prototype_browser_history'
            ' WHERE project_id = %s ORDER BY used_at DESC LIMIT 15',
            (project_id,)
        )
        rows = await db.fetchall()
    return {'result': [r['url'] for r in rows]}


@router.post('/planning/browser/navigate')
async def planning_browser_navigate(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Загружает URL в Playwright-браузере и возвращает скриншот."""
    url = str(data.get('url') or '').strip()
    if not url:
        return {'error': 'url required'}
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    project_id = int(data.get('project_id') or 0)

    try:
        page = await _browser_session_get(user.user_id)
        await _maybe_resize_viewport(page, data)
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_timeout(800)
        screenshot = await _page_screenshot_b64(page)
        scroll = await _page_scroll_info(page)
        final_url = page.url
        if project_id and final_url and final_url != 'about:blank':
            asyncio.ensure_future(_browser_history_save(project_id, final_url))
        return {'screenshot': screenshot, 'url': final_url, 'title': await page.title(), **scroll}
    except Exception as e:
        return {'error': str(e)}


@router.post('/planning/browser/click')
async def planning_browser_click(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Кликает по координатам в браузере (навигация по ссылкам) и возвращает скриншот."""
    action = data.get('action', '')
    x, y = int(data.get('x', 0)), int(data.get('y', 0))
    try:
        page = await _browser_session_get(user.user_id)
        await _maybe_resize_viewport(page, data)
        if action == 'back':
            await page.go_back(wait_until='domcontentloaded', timeout=8000)
            await page.wait_for_timeout(400)
        elif action == 'scroll':
            delta_x = int(data.get('deltaX', 0))
            delta_y = int(data.get('deltaY', 0))
            await page.evaluate('([dx, dy]) => window.scrollBy(dx, dy)', [delta_x, delta_y])
        elif action == 'scroll_to':
            scroll_x = int(data.get('scrollX', 0))
            scroll_y = int(data.get('scrollY', -1))
            await page.evaluate(
                '([x, y]) => window.scrollTo(x < 0 ? window.scrollX : x, y < 0 ? window.scrollY : y)',
                [scroll_x, scroll_y]
            )
        else:
            await page.mouse.click(x, y)
            await page.wait_for_load_state('domcontentloaded', timeout=8000)
            await page.wait_for_timeout(500)
        screenshot = await _page_screenshot_b64(page)
        scroll = await _page_scroll_info(page)
        return {'screenshot': screenshot, 'url': page.url, 'title': await page.title(), **scroll}
    except Exception as e:
        try:
            page = await _browser_session_get(user.user_id)
            screenshot = await _page_screenshot_b64(page)
            scroll = await _page_scroll_info(page)
            return {'screenshot': screenshot, 'url': page.url, 'title': await page.title(), **scroll}
        except Exception:
            return {'error': str(e)}


@router.post('/planning/browser/pick')
async def planning_browser_pick(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Извлекает HTML+CSS элемента по координатам выделения (в пикселях скриншота 1280×800)."""
    x, y = int(data.get('x', 0)), int(data.get('y', 0))
    w, h = max(int(data.get('w', 1)), 1), max(int(data.get('h', 1)), 1)
    try:
        page = await _browser_session_get(user.user_id)
        result = await page.evaluate(_PICK_ELEMENT_JS, {'x': x, 'y': y, 'w': w, 'h': h})
        if not result:
            return {'error': 'Элемент не найден'}
        return result
    except Exception as e:
        return {'error': str(e)}


@router.post('/planning/browser/close')
async def planning_browser_close(request: Request, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Закрывает браузерную сессию пользователя."""
    await _browser_session_close(user.user_id)
    return {'result': 'ok'}
