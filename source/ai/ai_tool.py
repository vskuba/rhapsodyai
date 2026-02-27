import ast
import functools
import importlib
import sys
from pathlib import Path
from typing import cast

from numba.core.types import Callable
from source.config import config_get
from source.logging_ import logger_info


def ai_tools_get() -> list[Callable]:
    """
    Сканирует папку tools, импортирует файлы и возвращает список всех функций.
    """
    all_tools: list[Callable] = []

    # Путь к папке с инструментами
    tools_dir = Path(config_get('data_dir')) / 'tools'
    if not tools_dir.exists():
        tools_dir.mkdir(parents=True, exist_ok=True)
        return []

    # 1. Находим все .py файлы
    for filepath in tools_dir.rglob('*.py'):
        # Пропускаем __init__.py
        if filepath.name == '__init__.py':
            continue

        try:
            # 2. Парсим файл через AST, чтобы найти имена функций
            with open(filepath, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())

            func_names = [
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not node.name.startswith('_')  # Пропускаем приватные функции
            ]

            if not func_names:
                continue

            # 3. Динамический импорт модуля
            module_name = filepath.stem
            spec = importlib.util.spec_from_file_location(module_name, str(filepath))

            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 4. Извлекаем объекты функций и добавляем в общий список
                for name in func_names:
                    func = getattr(module, name, None)
                    if callable(func):
                        all_tools.append(
                            cast(Callable, func)
                        )
                    else:
                        logger_info(f"Предупреждение: {name} в {filepath} не является callable")

        except Exception as e:
            logger_info(f"Ошибка при обработке файла {filepath}: {e}")

    return all_tools


def ai_tool_monitoring(tool: Callable) -> Callable:
    """Оборачивает инструмент в логирование всех вызовов с сохранением сигнатуры"""

    name = getattr(tool, "__name__", str(tool))

    @functools.wraps(tool)  # <--- Это магическая строчка
    async def wrapper(*args, **kwargs):
        arg_str = ", ".join(repr(a) for a in args)
        if kwargs:
            arg_str += ", " + ", ".join(f"{k}={repr(v)}" for k, v in kwargs.items())

        logger_info(f"🛠 Инструмент '{name}' → ({arg_str})")

        try:
            result = await tool(*args, **kwargs)
            logger_info(f"🛠 Инструмент '{name}' резудьтат  → {repr(result)}")
            return result
        except Exception as e:
            logger_info(f"✗🛠 Инструмент '{name}' ошибка → {type(e).__name__}: {e}")
            raise

    return wrapper
