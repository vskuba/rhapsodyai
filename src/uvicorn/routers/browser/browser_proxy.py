"""Прокси к контейнеру-браузеру: админка ходит через `:8011`, а не в `:8014`.

Порт контейнера опубликован на `127.0.0.1` и только для отладки — браузер
администратора до него не дотянется ни с другой машины, ни через Caddy. Поэтому и
список сессий, и живое окно идут через основной сервер: здесь уже есть сессионная
кука и права, а до контейнера остаётся внутренняя сеть `os-net`.

Схемы запросов здесь сознательно не повторяются. Проверяет вход контейнер-браузер
(`py_modules/browser_/browser_api.py`), а прокси передаёт тело как есть и возвращает его
ответ вместе с кодом: две копии одной схемы разошлись бы на первой же правке.
"""

import asyncio

import json

import websockets
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from logging_.logging_ import logger_info

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import auth_role_permissions
from src.uvicorn.routers.browser.browser_error import browser_error_write
from src.uvicorn.routers.browser.browser_upstream import (
    browser_upstream_headers,
    browser_upstream_request,
    browser_upstream_ws_url,
)

router = APIRouter(prefix='/api/browser', tags=['browser'])

# Кадр 1280×800 в JPEG q60 весит десятки килобайт, в base64 — треть сверху.
# Предел по умолчанию у `websockets` — 1 МБ; поднимаем, чтобы тяжёлый кадр
# со сложной страницы не рвал соединение.
BROWSER_PROXY_FRAME_LIMIT = 4 * 1024 * 1024

BROWSER_PROXY_CLOSE_FORBIDDEN = 4403
BROWSER_PROXY_CLOSE_UPSTREAM = 4502

# Перехват адреса сокета открывает страницу и ждёт подключения — это минуты, а не
# секунды: сам контейнер ждёт до 120 с, и обрывать его раньше времени бессмысленно.
BROWSER_PROXY_CAPTURE_TIMEOUT = 180.0


@router.get('/session')
async def browser_proxy_session_list(user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Сессии контейнера-браузера и его память."""
    return await browser_upstream_request('GET', '/browser/session')


@router.post('/session', status_code=201)
async def browser_proxy_session_create(data: dict, user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Заводит сессию: `name`, `url`, `storage_state`, `viewport`."""
    return await browser_upstream_request('POST', '/browser/session', data)


@router.delete('/session/{session_id}')
async def browser_proxy_session_close(session_id: str,
                                      user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Гасит сессию. Повторный вызов не ошибка."""
    return await browser_upstream_request('DELETE', f'/browser/session/{session_id}')


@router.post('/session/{session_id}/goto')
async def browser_proxy_session_goto(session_id: str, data: dict,
                                     user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Переводит страницу сессии на URL."""
    return await browser_upstream_request('POST', f'/browser/session/{session_id}/goto', data)


@router.get('/session/{session_id}/thumb')
async def browser_proxy_session_thumb(session_id: str, fresh: bool = False,
                                      user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Миниатюра страницы сессии — строкой `data:` внутри JSON.

    Картинкой её не отдаём намеренно: прокси переносит JSON и код ответа как есть,
    и бинарный ответ потребовал бы отдельного пути ради двадцати килобайт.
    """
    return await browser_upstream_request(
        'GET', f'/browser/session/{session_id}/thumb?fresh={"true" if fresh else "false"}')


@router.get('/session/{session_id}/storage_state')
async def browser_proxy_storage_state(session_id: str,
                                      user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Cookie и localStorage сессии."""
    return await browser_upstream_request('GET', f'/browser/session/{session_id}/storage_state')


@router.post('/snapshot')
async def browser_proxy_snapshot(data: dict, user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Снимок дерева страницы для LLM: `session_id` или `url`, `selector`, `depth`."""
    return await browser_upstream_request('POST', '/browser/snapshot', data)


@router.post('/ws/capture')
async def browser_proxy_ws_capture(data: dict,
                                   user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Адреса вебсокетов, которые подняла страница: `url`, `storage_state`, `wait_sec`.

    Наружу нужно тем, кто держит сокет сам, а браузер зовёт один раз — подсмотреть
    адрес. Так работает DatingAi: вкладка Chromium стоит ~143 МБ, вебсокет-клиент
    десятки килобайт, и держать ради одного адреса открытую страницу незачем.

    Право на запись, а не на чтение: перехват открывает страницу и водит её
    (прогрев, клик по кнопке чата) — это действие, а не просмотр.
    """
    return await browser_upstream_request('POST', '/browser/ws/capture', data,
                                          timeout=BROWSER_PROXY_CAPTURE_TIMEOUT)


@router.websocket('/view/{session_id}')
async def browser_proxy_view(websocket: WebSocket, session_id: str):
    """Труба между окном админки и скринкастом контейнера.

    `Depends(AuthChecker(...))` сюда не подходит: он ждёт `Request`, которого у
    вебсокета нет. Кука та же самая — `SessionMiddleware` обслуживает и
    websocket-scope, — поэтому роль берётся из сессии напрямую.

    Сначала проверяется сама сессия, и только потом права. Одной проверки прав мало:
    у неизвестной роли — а пустая строка без куки как раз такая — набор прав
    view-по-умолчанию, в котором `BROWSER_VIEW` есть. Без первой проверки окно
    открывалось бы вообще без входа в систему.
    """
    if not websocket.session.get('user_id') or not websocket.session.get('role'):
        await websocket.close(code=BROWSER_PROXY_CLOSE_FORBIDDEN, reason='нужен вход')
        return

    role = websocket.session.get('role', '')
    if AuthPermission.BROWSER_VIEW not in auth_role_permissions(role):
        await websocket.close(code=BROWSER_PROXY_CLOSE_FORBIDDEN, reason='нет прав')
        return

    await websocket.accept()

    headers = browser_upstream_headers()
    upstream_url = browser_upstream_ws_url(f'/browser/view/{session_id}')

    try:
        async with websockets.connect(upstream_url, additional_headers=headers,
                                      max_size=BROWSER_PROXY_FRAME_LIMIT) as upstream:
            await _pipe(websocket, upstream, session_id)
    except WebSocketDisconnect:
        pass
    except websockets.exceptions.ConnectionClosed as e:
        # Причину закрытия придумал контейнер — «нет такой сессии», например.
        # Свой код здесь стёр бы её, и окно показало бы «браузер недоступен»
        # там, где на самом деле просто не тот идентификатор.
        await _close_quiet(websocket, e.code or BROWSER_PROXY_CLOSE_UPSTREAM, e.reason or '')
    except Exception as e:
        logger_info(f'[browser] прокси окна {session_id} оборвался: {e}')
        await browser_error_write('proxy', f'окно оборвалось: {e}', session_id=session_id,
                                  context={'origin': 'прокси вебсокета'})
        await _close_quiet(websocket, BROWSER_PROXY_CLOSE_UPSTREAM, 'контейнер-браузер недоступен')


async def _close_quiet(websocket: WebSocket, code: int, reason: str):
    """Закрывает сокет, не роняя обработчик: клиент мог отвалиться первым."""
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


async def _pipe(websocket: WebSocket, upstream, session_id: str = ''):
    """Гоняет текстовые кадры в обе стороны, пока жива хотя бы одна сторона."""
    down = asyncio.create_task(_pipe_down(websocket, upstream, session_id))
    up = asyncio.create_task(_pipe_up(websocket, upstream))

    done, pending = await asyncio.wait({down, up}, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
    for task in done:
        # Ошибку живой стороны надо увидеть в логе, а не потерять в задаче.
        task.result()


async def _pipe_down(websocket: WebSocket, upstream, session_id: str = ''):
    """Кадры из контейнера — в окно админки, ошибки по дороге — в журнал.

    Журнал ведёт эта сторона, а не контейнер: базы у контейнера нет. И не клиент:
    окно могли закрыть до того, как человек прочитал строку состояния, а разбираться
    с ошибкой всё равно придётся.
    """
    last_url = ''
    async for message in upstream:
        await websocket.send_text(message)

        # Разбираем уже отправленное: журнал не должен задерживать кадр.
        try:
            data = json.loads(message)
        except Exception:
            continue

        if data.get('type') == 'frame' and data.get('url'):
            last_url = str(data['url'])
        elif data.get('type') == 'error':
            await browser_error_write('view', str(data.get('text') or ''),
                                      session_id=session_id, url=last_url,
                                      context={'origin': 'живое окно'})


async def _pipe_up(websocket: WebSocket, upstream):
    """События ввода из окна админки — в контейнер."""
    while True:
        await upstream.send(await websocket.receive_text())
