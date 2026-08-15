"""Живое окно сессии: кадры страницы наружу, ввод — обратно.

Картинку даёт CDP-скринкаст (`Page.startScreencast`): Chromium сам присылает JPEG,
когда на странице что-то изменилось, и молчит, пока она неподвижна. Цикл со
скриншотами дал бы ту же картинку, но платил бы полным рендером за каждый кадр —
включая те, на которых ничего не поменялось.

Ввод возвращается настоящими событиями мыши и клавиатуры, а не `element.click()`:
страница не должна отличать наблюдателя от человека. Так работают hover, фокус,
перетаскивание и обработчики, которые смотрят на `isTrusted`.

Окно смотрит на одну страницу за раз, но сессия может держать несколько: сайт
открывает дочернее окно, и оно становится следующей вкладкой. Кадры идут только с
текущей вкладки — скринкаст со всех сразу утроил бы трафик ради картинок, на
которые никто не смотрит.
"""

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from logging_.logging_ import logger_info

from src.browser.browser_api import BROWSER_API_TOKEN
from src.browser.browser_pool import (
    BROWSER_POOL_GOTO_TIMEOUT_MS,
    BROWSER_POOL_VIEWPORT_HEIGHT,
    BROWSER_POOL_VIEWPORT_WIDTH,
    browser_pool_session_get,
)
from src.browser.browser_record import browser_record_goto

router = APIRouter()

BROWSER_VIEW_FORMAT = 'jpeg'
BROWSER_VIEW_QUALITY = 60
BROWSER_VIEW_MAX_WIDTH = 1280
BROWSER_VIEW_MAX_HEIGHT = 800

# Очередь кадров короткая намеренно. Живому окну нужен свежий кадр, а не полная
# лента: медленный клиент должен терять промежуточные кадры и видеть актуальный,
# а не отставать всё сильнее с каждой секундой.
BROWSER_VIEW_QUEUE_SIZE = 2

# Коды закрытия из приватного диапазона 4000–4999: 4401 — не тот токен,
# 4404 — сессии нет. Клиент показывает причину, а не молчаливый обрыв.
BROWSER_VIEW_CLOSE_TOKEN = 4401
BROWSER_VIEW_CLOSE_NOT_FOUND = 4404

# Текст ошибки действия в строке состояния. Сообщения Playwright многострочные,
# с «call log» на полсотни строк — в подписи под экраном от него пользы нет.
BROWSER_VIEW_ERROR_LIMIT = 200

# Сколько текста принимаем за одну вставку. Буфер обмена бывает и на мегабайт
# (скопировали страницу целиком), а вставка идёт одним сообщением сокета.
BROWSER_VIEW_PASTE_LIMIT = 100000


@router.websocket('/browser/view/{session_id}')
async def browser_view_socket(websocket: WebSocket, session_id: str, token: str = ''):
    """Поток кадров сессии и приём событий ввода.

    Токен принимается и заголовком `X-Browser-Token`, и параметром `?token=`:
    заголовок ставит серверный клиент (прокси в `uvicorn`), а браузерный
    `new WebSocket()` заголовки задавать не умеет вовсе — ему остаётся параметр.
    """
    await websocket.accept()

    header_token = websocket.headers.get('x-browser-token', '')
    if BROWSER_API_TOKEN and BROWSER_API_TOKEN not in (token, header_token):
        await websocket.close(code=BROWSER_VIEW_CLOSE_TOKEN, reason='неверный токен')
        return

    entry = browser_pool_session_get(session_id)
    if entry is None or entry['page'].is_closed():
        await websocket.close(code=BROWSER_VIEW_CLOSE_NOT_FOUND, reason='нет такой сессии')
        return

    context = entry['context']
    frames: asyncio.Queue = asyncio.Queue(maxsize=BROWSER_VIEW_QUEUE_SIZE)
    state = {'metadata': {}, 'page': entry['page'], 'cdp': None}
    tasks: set = set()
    send_lock = asyncio.Lock()
    switch_lock = asyncio.Lock()

    async def emit(message: dict):
        # Один сокет — одна отправка за раз: кадры идут из своей задачи, список
        # вкладок — из обработчика событий контекста. Без замка два `send_json`
        # успевают перемешать байты одного кадра. Закрытое окно не ошибка:
        # обработчик вкладок про обрыв сокета узнаёт последним.
        async with send_lock:
            try:
                await websocket.send_json(message)
            except Exception:
                pass

    def spawn(coro):
        """Фоновая задача со ссылкой в `tasks`: без неё сборщик мусора её оборвёт."""
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def view_switch(page):
        """Переводит окно на вкладку: старый скринкаст гасим, новый заводим."""
        async with switch_lock:
            if state['cdp'] is not None:
                await _cast_stop(state['cdp'])

            state['page'] = page
            state['metadata'] = {}
            while not frames.empty():
                frames.get_nowait()

            state['cdp'] = await _cast_start(page, frames, state, tasks)

        await emit(_tabs_payload(context, page))

    async def tabs_refresh():
        """Список вкладок клиенту. Закрылась текущая — окно возвращается на первую."""
        pages = _pages(context)
        if not pages:
            return
        if state['page'].is_closed():
            await view_switch(pages[0])
            return
        await emit(_tabs_payload(context, state['page']))

    def on_close(_page):
        spawn(tabs_refresh())

    def watch(page):
        """Подписка на закрытие вкладки. Пары храним, чтобы снять их в конце."""
        page.on('close', on_close)
        watched.append(page)

    def on_page(page):
        # Дочернее окно всплывает поверх родителя — окно админки идёт следом,
        # как это делает настоящий браузер: иначе всплывшая форма входа
        # осталась бы невидимой, а страница под ней — замершей.
        watch(page)
        spawn(view_switch(page))

    watched: list = []
    context.on('page', on_page)
    for page in _pages(context):
        watch(page)

    await view_switch(entry['page'])
    logger_info(f'[browser] окно открыто: {session_id}')

    sender = asyncio.create_task(_frames_send(emit, frames, state))
    try:
        while True:
            message = await websocket.receive_json()
            entry['used_at'] = time.time()

            try:
                await _message_apply(message, context, state, view_switch, emit, session_id)
            except Exception as e:
                # Неудачное действие — строка клиенту, а не конец окна. Опечатка в
                # адресе и не успевшая загрузиться страница случаются постоянно, и
                # гасить из-за них живую сессию человеку значит терять его вход.
                await emit({'type': 'error', 'text': _error_text(e)})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger_info(f'[browser] окно {session_id} оборвалось: {e}')
    finally:
        sender.cancel()
        # Подписки снимаем обязательно: контекст живёт дольше окна, и оставленный
        # обработчик копил бы задачи для давно закрытого сокета при каждом popup.
        context.remove_listener('page', on_page)
        for page in watched:
            page.remove_listener('close', on_close)
        await _cast_stop(state['cdp'])
        logger_info(f'[browser] окно закрыто: {session_id}')


async def _message_apply(message: dict, context, state: dict, view_switch, emit, session_id: str = ''):
    """Сообщение клиента: вкладки и буфер — здесь, всё остальное — над текущей страницей."""
    kind = message.get('type', '')

    if kind == 'copy':
        # Обратная сторона вставки: выделили в чужом Chromium, а системный буфер
        # на машине человека об этом не знает. Отдаём выделение текстом, класть
        # его в буфер — дело клиента, у сервера доступа к нему нет.
        text = await state['page'].evaluate('() => (window.getSelection() || "").toString()')
        await emit({'type': 'clipboard', 'text': (text or '')[:BROWSER_VIEW_PASTE_LIMIT]})
        return

    if kind == 'tab':
        pages = _pages(context)
        index = int(message.get('index', 0))
        if not 0 <= index < len(pages):
            raise RuntimeError('нет такой вкладки')
        await view_switch(pages[index])
        return

    if kind == 'tab_close':
        pages = _pages(context)
        index = int(message.get('index', 0))
        if index == 0:
            raise RuntimeError('первую вкладку не закрыть — это сама сессия')
        if not 0 <= index < len(pages):
            raise RuntimeError('нет такой вкладки')

        # На закрытие текущей вкладки окно вернётся на первую само: страница
        # пришлёт `close`, и `tabs_refresh` переведёт его.
        await pages[index].close()
        return

    await _input_apply(state['page'], message, state['metadata'])

    # Адресная строка — единственная навигация, которую записывает сам живой
    # экран: переход по ссылке уже описан кликом, и второй шаг `goto` рядом с ним
    # увёл бы страницу раньше, чем клик успел сработать. Записываем набранное, а
    # не итоговый `page.url`: человек показывал именно этот адрес, а куда он
    # перебросит на прогоне — дело сайта.
    if kind == 'goto' and session_id:
        url = _url_full(message.get('url', ''))
        if url:
            browser_record_goto(session_id, url)


async def _cast_start(page, frames: asyncio.Queue, state: dict, tasks: set):
    """Запускает скринкаст страницы. Возвращает CDP-сессию — её потом гасить."""
    cdp = await page.context.new_cdp_session(page)

    def on_frame(params: dict):
        # Подтверждать нужно каждый кадр, включая выброшенный: Chromium держит
        # ровно один кадр «в полёте» и без `screencastFrameAck` замолкает навсегда.
        ack = asyncio.create_task(_frame_ack(cdp, params.get('sessionId')))
        tasks.add(ack)
        ack.add_done_callback(tasks.discard)

        state['metadata'] = params.get('metadata') or {}

        if frames.full():
            frames.get_nowait()
        frames.put_nowait(params.get('data', ''))

    cdp.on('Page.screencastFrame', on_frame)
    await cdp.send('Page.startScreencast', {
        'format': BROWSER_VIEW_FORMAT,
        'quality': BROWSER_VIEW_QUALITY,
        'maxWidth': BROWSER_VIEW_MAX_WIDTH,
        'maxHeight': BROWSER_VIEW_MAX_HEIGHT,
        'everyNthFrame': 1,
    })
    return cdp


async def _frame_ack(cdp, frame_session_id):
    """Подтверждение кадра. Ошибку глотаем: окно могли закрыть между кадром и ответом."""
    try:
        await cdp.send('Page.screencastFrameAck', {'sessionId': frame_session_id})
    except Exception:
        pass


async def _frames_send(emit, frames: asyncio.Queue, state: dict):
    """Отдаёт кадры клиенту. Адрес идёт вместе с кадром — это свойство, не запрос в браузер."""
    while True:
        data = await frames.get()
        await emit({'type': 'frame', 'data': data, 'url': state['page'].url})


async def _input_apply(page, message: dict, metadata: dict):
    """Разбирает сообщение клиента в действие над страницей."""
    kind = message.get('type', '')

    if kind == 'mouse':
        x, y = _point(message, metadata)
        action = message.get('action', 'click')
        button = message.get('button', 'left')

        if action == 'move':
            await page.mouse.move(x, y)
        elif action == 'down':
            await page.mouse.move(x, y)
            await page.mouse.down(button=button)
        elif action == 'up':
            await page.mouse.up(button=button)
        else:
            await page.mouse.click(x, y, button=button, click_count=int(message.get('clicks', 1)))

    elif kind == 'wheel':
        x, y = _point(message, metadata)
        await page.mouse.move(x, y)
        await page.mouse.wheel(float(message.get('dx', 0)), float(message.get('dy', 0)))

    elif kind == 'key':
        # Строка вида `Control+a` — Playwright сам разложит её на модификаторы.
        key = message.get('key', '')
        if key:
            await page.keyboard.press(key)

    elif kind == 'text':
        text = message.get('text', '')
        if text:
            await page.keyboard.type(text)

    elif kind == 'paste':
        # Буфер обмена у страницы свой, и он пуст: скопировали в системе, а
        # `Control+v` уходит в чужой Chromium, где копировать было нечего.
        # Поэтому текст приезжает вместе с сообщением, а вставляет его
        # `insert_text` — одним событием ввода, как настоящая вставка, а не
        # посимвольным набором, на котором подсказки и автодополнение сходят с ума.
        text = (message.get('text', '') or '')[:BROWSER_VIEW_PASTE_LIMIT]
        if text:
            await page.keyboard.insert_text(text)

    elif kind == 'goto':
        url = _url_full(message.get('url', ''))
        if url:
            await page.goto(url, wait_until='domcontentloaded', timeout=BROWSER_POOL_GOTO_TIMEOUT_MS)

    elif kind == 'back':
        await page.go_back()

    elif kind == 'forward':
        await page.go_forward()

    elif kind == 'reload':
        await page.reload()


def _pages(context) -> list:
    """Живые страницы сессии в порядке появления: первая — сама сессия, дальше дочерние."""
    return [page for page in context.pages if not page.is_closed()]


def _tabs_payload(context, current) -> dict:
    """Список вкладок для клиента.

    Заголовка страницы здесь нет намеренно: `page.title()` — это вызов в
    страницу, и занятый своим JavaScript сайт заставил бы окно ждать его
    ответа. Адрес — свойство объекта и берётся мгновенно.
    """
    pages = _pages(context)

    return {
        'type': 'tabs',
        'tabs': [{'index': i, 'url': page.url} for i, page in enumerate(pages)],
        'active': pages.index(current) if current in pages else 0,
    }


def _point(message: dict, metadata: dict) -> tuple[float, float]:
    """Нормированная точка кадра → CSS-пиксели viewport.

    Клиент шлёт долю ширины и высоты (0..1), а не пиксели: он рисует картинку
    произвольного размера и не обязан знать, во что Chromium её ужал под
    `maxWidth`. Обратный пересчёт делают метаданные последнего кадра —
    `deviceWidth`/`deviceHeight` там и есть viewport в CSS-пикселях.
    """
    width = float(metadata.get('deviceWidth') or BROWSER_POOL_VIEWPORT_WIDTH)
    height = float(metadata.get('deviceHeight') or BROWSER_POOL_VIEWPORT_HEIGHT)
    offset_top = float(metadata.get('offsetTop') or 0)

    x = min(max(float(message.get('x', 0)), 0.0), 1.0) * width
    y = min(max(float(message.get('y', 0)), 0.0), 1.0) * height + offset_top

    return x, y


def _url_full(value: str) -> str:
    """Адрес из строки окна. Схему дописываем, а не отвергаем.

    В REST-ручках (`browser_api`) адрес без схемы — ошибка запроса: там его шлёт
    программа, и молча угаданный `https://` скрыл бы её опечатку. Здесь адрес
    набирает человек в адресной строке, и «example.com» он пишет намеренно.
    """
    value = (value or '').strip()
    if value and '://' not in value:
        return f'https://{value}'
    return value


def _error_text(error: Exception) -> str:
    """Первая строка ошибки для подписи под экраном.

    У части исключений Playwright текст пустой — у таймаута, например, — и клиент
    получил бы пустую подпись вместо причины. Тогда показываем имя класса.
    """
    text = str(error).strip().splitlines()
    return (text[0] if text else type(error).__name__)[:BROWSER_VIEW_ERROR_LIMIT]


async def _cast_stop(cdp):
    """Гасит скринкаст и отцепляет CDP. Сессия при этом продолжает жить."""
    if cdp is None:
        return
    try:
        await cdp.send('Page.stopScreencast')
    except Exception:
        pass
    try:
        await cdp.detach()
    except Exception:
        pass
