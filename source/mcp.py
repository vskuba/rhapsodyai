import json
import os
import traceback
from typing import Any

from source.config import config_get
from source.logging_ import logger_info


def mcp_config_filename() -> str:
    data_dir = config_get('data_dir', 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "mcp_servers.json")


def mcp_config_save(config: dict[str, Any]):
    """
    Сохраняет список конфигураций MCP серверов в JSON файл.
    Принимает список словарей.
    """
    filename = mcp_config_filename()

    # Создаем папку, если она еще не существует (например, /data/)
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            # indent=4 делает файл читаемым для человека
            # ensure_ascii=False позволяет сохранять кириллицу корректно
            json.dump(config, f, indent=4, ensure_ascii=False)
        print(f"Конфигурация MCP успешно сохранена в {filename}")
    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка при сохранении MCP конфига: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )


def mcp_config_load() -> dict[str, Any]:
    filename = mcp_config_filename()
    if not os.path.exists(filename):
        return {}

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка при чтении MCP конфига: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )
        return {}
