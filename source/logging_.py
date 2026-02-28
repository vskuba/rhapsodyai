import logging
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


def logger_info(msg: str, **kwargs):
    logger.info(msg[:5000], extra={'trace_id': trace_id} | kwargs)


def logging_init():
    # Устанавливаем минимальный уровень логирования для главного логгера
    logger.setLevel(level)

    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(threadName)s %(message)s",
        rename_fields={"levelname": "severity", "asctime": "timestamp"},
    )

    # Твой обязательный файловый хендлер
    log_handler = RotatingFileHandler(
        _logging_filename_get(),
        maxBytes=10 * 1024 * 1024,
        backupCount=7
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    # 2. Настройка Logfire
    logfire.configure(send_to_logfire=False)

    # Исправление ошибки AttributeError:
    # Вместо instrument_logging() добавляем специальный хендлер
    logger.addHandler(logfire.LogfireLoggingHandler())

    # Авто-логирование всех HTTP запросов (httpx) через Logfire
    logfire.instrument_httpx(capture_all=True)

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
    body = await request.aread()
    logger_info(
        f"🌐📤 HTTP Request: {request.method} {request.url}\n\n",
        body=body.decode(errors='ignore')
    )


async def log_response_body(response: httpx.Response):
    body = await response.aread()
    http_status = response.status_code
    http_status_icon = '✅' if http_status == 200 else '⚠️'
    logger_info(
        f"🌐📥 {http_status_icon} HTTP Response: {response.status_code}",
        body=body.decode(errors='ignore')
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
