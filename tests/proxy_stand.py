"""Стенд-прокси: настоящий HTTP-прокси на сорок строк, чтобы проверять реестр.

⚠ **Это стенд, а не инструмент.** Он нужен ровно затем, чтобы проверить дорогу
целиком — реестр → проверка → выдача места → сессия браузера → запросы соседа, —
не покупая для этого платный канал и не завися от чужого сервиса в прогоне.
Наружу он ничего не скрывает: выходит с того же адреса, что и машина, на которой
запущен. Для проверки этого достаточно: вопрос «прошёл ли запрос через прокси»
решается по журналу стенда, а не по увиденному IP.

Умеет ровно две вещи, обе нужны:

* **CONNECT** — так через прокси ходит всё, что по HTTPS (а это весь наш обиход);
* **Basic-авторизацию** — пароль в прокси главный источник молчаливых ошибок
  (`@` в пароле, забытое экранирование), и стенд без пароля не проверил бы её
  вовсе.

Запуск внутри контейнера, чтобы адрес был виден в общей сети docker:

    docker exec -d uvicorn python3 tests/proxy_stand.py --port 8899 --user u --password 'p@ss'

Проверка: `curl -x http://u:p%40ss@uvicorn:8899 https://api.ipify.org?format=json`
"""

import argparse
import asyncio
import base64

PROXY_STAND_BUFFER = 64 * 1024


async def proxy_stand_serve(port: int, user: str, password: str) -> None:
    """Поднимает прокси и работает, пока его не остановят."""
    want = base64.b64encode(f'{user}:{password}'.encode()).decode() if user else ''

    async def _client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await _handle(reader, writer, want)
        except Exception as e:
            print(f'[стенд] сорвалось: {type(e).__name__}: {e}', flush=True)
        finally:
            writer.close()

    server = await asyncio.start_server(_client, '0.0.0.0', port)
    print(f'[стенд] прокси на :{port}, авторизация: {"да" if want else "нет"}', flush=True)

    async with server:
        await server.serve_forever()


async def _handle(reader, writer, want: str) -> None:
    """Один запрос: разбор заголовков, авторизация, труба до цели."""
    head = await reader.readuntil(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    method, target, _ = lines[0].split(' ', 2)

    if want:
        given = ''
        for line in lines[1:]:
            if line.lower().startswith('proxy-authorization:'):
                given = line.split(' ')[-1].strip()
        if given != want:
            # 407, как настоящий прокси: по нему клиент понимает, что дело в
            # пароле, а не в недоступности цели.
            writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\n'
                         b'Proxy-Authenticate: Basic realm="stand"\r\n\r\n')
            await writer.drain()
            print('[стенд] отказ: не тот пароль', flush=True)

            return

    if method.upper() == 'CONNECT':
        host, _, port = target.partition(':')
        print(f'[стенд] CONNECT {target}', flush=True)
        up_reader, up_writer = await asyncio.open_connection(host, int(port or 443))
        writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
        await writer.drain()
    else:
        # Обычный HTTP: цель — абсолютный адрес в первой строке.
        rest = target.split('://', 1)[1] if '://' in target else target
        host_port, _, path = rest.partition('/')
        host, _, port = host_port.partition(':')
        print(f'[стенд] {method} {target}', flush=True)
        up_reader, up_writer = await asyncio.open_connection(host, int(port or 80))
        head = head.replace(target.encode('latin-1'), ('/' + path).encode('latin-1'), 1)
        up_writer.write(head)
        await up_writer.drain()

    await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer),
                         return_exceptions=True)


async def _pipe(reader, writer) -> None:
    """Перекладывает байты в одну сторону до конца потока."""
    try:
        while True:
            chunk = await reader.read(PROXY_STAND_BUFFER)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        writer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Стенд-прокси для проверки реестра')
    parser.add_argument('--port', type=int, default=8899)
    parser.add_argument('--user', default='')
    parser.add_argument('--password', default='')
    args = parser.parse_args()

    asyncio.run(proxy_stand_serve(args.port, args.user, args.password))
