import logging
import uuid
from logging.handlers import RotatingFileHandler

import httpx

from pathlib import Path
from source.config import config_get
from pythonjsonlogger.json import JsonFormatter

logger: logging.Logger = logging.getLogger()
trace_id: str = str(uuid.uuid4())

def logger_info(msg: str, **kwargs):
    logger.info(msg, extra={'trace_id': trace_id} | kwargs)


def logging_init():
    # Устанавливаем минимальный уровень логирования для главного логгера
    logger.setLevel(logging.INFO)

    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"levelname": "severity", "asctime": "timestamp"},
    )

    log_handler = RotatingFileHandler(
        logging_filename_get(),  # ваш текущий app.log
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=7  # хранить 7 старых файлов
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    # 3. Настройка сторонних библиотек на подробный лог
    for lib in ["github", "urllib3", "httpx", "mcp"]:
        lib_logger = logging.getLogger(lib)
        lib_logger.setLevel(logging.DEBUG)
        lib_logger.propagate = True  # Гарантируем передачу логов в наш FileHandler

    logger_info('Logging system initialized', status='ready')


def logging_filename_get() -> str:
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


async def log_request_body(request: httpx.Request):
    body = await request.aread()
    logger_info(f"HTTP Request: {request.method} {request.url}",
                body=body.decode(errors='ignore'))


async def log_response_body(response: httpx.Response):
    body = await response.aread()
    logger_info(f"HTTP Response: {response.status_code}",
                body=body.decode(errors='ignore'))

def logger_reset_trace_id():
    global trace_id
    trace_id = str(uuid.uuid4())