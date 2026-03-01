import json
import logging
import time
import uuid
from logging.handlers import RotatingFileHandler

import httpx
from pathlib import Path
import logfire
from source.config import config_get
from pythonjsonlogger.json import JsonFormatter

level = logging.INFO
logger: logging.Logger = logging.getLogger()
trace_id: str = str(uuid.uuid4())
x_request_ids: dict[str, int] = {}


def logger_info(msg: str, **kwargs):
    logger.info(msg[:50000], extra={'trace_id': trace_id} | kwargs)


def logging_init():
    # Устанавливаем минимальный уровень логирования для главного логгера
    logger.setLevel(level)

    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(threadName)s %(message)s",
        rename_fields={"levelname": "severity", "asctime": "timestamp"},
        json_ensure_ascii=False
    )

    # Твой обязательный файловый хендлер
    log_handler = RotatingFileHandler(
        _logging_filename_get(),
        maxBytes=10 * 1024 * 1024,
        backupCount=7
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    # 3. Настройка сторонних библиотек
    for lib in [
        "github",
        "urllib3",
        "httpx",
        'httpcore',
        "mcp",
        'pydantic_ai',
        'xai_sdk',
        'stdio_client',
        "mcp.client.stdio",
        "anyio"
    ]:
        lib_logger = logging.getLogger(lib)
        lib_logger.setLevel(level)

    logger_info('📝 логирование включено', status='ready')


async def log_request_body(request: httpx.Request):
    x_request_id = str(uuid.uuid4())
    x_request_ids[x_request_id] = int(time.time())

    request.headers['X-Request-ID'] = x_request_id
    body = await request.aread()
    logger_info(
        f"🌐📤 HTTP Request: {request.method} {request.url}\n\n",
        body=body.decode(errors='ignore'),
        headers=dict(request.headers)
    )

    dialog = []
    if 'user-agent' in request.headers and 'pydantic-ai/' in request.headers['user-agent']:
        body = body.decode(errors='ignore')
        json_data = json.loads(body)
        if 'messages' in json_data:
            messages = json_data['messages']
            for m in messages:
                role = '🧠' if m['role'] == 'assistant' else ('🔧' if m['role'] == 'tool' else '👤')
                replica = m.get('reasoning') or m.get('content') or ''
                tool_calls = []
                if 'tool_calls' in m:
                    for tc in m['tool_calls']:
                        tool_calls.append(f"🔧 {tc['function']['name']} -> ({tc['function']['arguments']})")
                if tool_calls:
                    replica += '\n\n' + '\n'.join(tool_calls)
                dialog.append(f"\n{role}: {replica}\n")

    if dialog:
        logger_info(
            f"👤-🧠 Текущая история общения: \n"
            f"{'\n'.join(dialog)}",
        )

async def log_response_body(response: httpx.Response):
    body = await response.aread()

    request_time = None
    if 'X-Request-ID' in response.request.headers:
        x_request_id = response.request.headers['X-Request-ID']
        if x_request_id in x_request_ids:
            request_time = int(time.time()) - x_request_ids[x_request_id]
            del x_request_ids[x_request_id]

    http_status = response.status_code
    http_status_icon = '✅' if http_status == 200 else '⚠️'
    request_time_message = f", время запроса {request_time:.2f}s" if request_time else ''

    logger_info(
        f"🌐📥 {http_status_icon} HTTP Response: {response.status_code}{request_time_message}",
        body=body.decode(errors='ignore'),
        headers=dict(response.headers),
        duration=request_time
    )


def logger_reset_trace_id():
    global trace_id
    trace_id = str(uuid.uuid4())


def _logging_filename_get() -> str:
    """
    Получаем имя файла для логов
    """
    filename = '/'.join([
        config_get('data_dir'),
        config_get('log_dir'),
        f'app.log'
    ])
    file_path = Path(filename)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    return filename
