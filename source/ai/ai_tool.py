import ast
import asyncio
import functools
import importlib
import sys
import traceback
from pathlib import Path
from typing import cast

from numba.core.types import Callable

from source.async_ import async_waiting_start
from source.config import config_get
from source.logging_ import logger_info
from source.mcp import mcp_config_list_get, mcp_config_get
from source.queue import queue_get

all_tools: list[Callable] = []
all_tools_permanent: list[Callable] = []


def ai_tools_get() -> list[Callable]:
    global all_tools
    if all_tools:
        return all_tools

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
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при обработке файла {filepath}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

    return all_tools


def ai_tools_permanent_get() -> list[Callable]:
    global all_tools_permanent
    if all_tools_permanent:
        return all_tools_permanent

    all_tools_permanent = [ai_tool_decorator(t) for t in [

        # ------ Chat
        chat_me,
        chat_me_question,

    ]]

    return all_tools_permanent + [

        # ------ Task
        task_abort # отдельно, потому что декоратор async
    ]


def ai_tools_mcp_get() -> list[str]:
    mcp_config_list = mcp_config_list_get()
    if mcp_config_list is None:
        return []

    tools = []
    for mcp_server_name in mcp_config_list:
        mcp_config = mcp_config_get(mcp_server_name)
        tools += [t.name for t in mcp_config.tools]

    return tools


def ai_tool_decorator(tool: Callable) -> Callable:
    name = getattr(tool, "__name__", str(tool))

    @functools.wraps(tool)  # <--- Это магическая строчка
    async def wrapper(*args, **kwargs):
        arg_str = ", ".join(repr(a) for a in args)
        if kwargs:
            arg_str += ", " + ", ".join(f"{k}={repr(v)}" for k, v in kwargs.items())

        try:
            logger_info(f"🛠 Инструмент '{name}' → ({arg_str})")
            result = await tool(*args, **kwargs)
            logger_info(f"🛠 Инструмент '{name}' резудьтат  → {repr(result)}")
            return result
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ 🛠 Инструмент '{name}' ошибка → {type(e).__name__}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

    return wrapper


def task_abort(final_text: str) -> bool:
    """
    This function close active task.
    Argument final_text is used for display in task report.
    """
    queue_get()['task_abort'].put(True)
    queue_get()['chat'].put(
        {
            "text": final_text,
            "who": 'agent',
        }
    )

    return True


async def chat_me_question(question: str) -> str:
    """
    This tool allows you to ask the user a question and receive an answer.
    The function argument is 'question'. The function will return a text string containing the answer to the question.
    """
    queue_get()['chat'].put(
        {
            "text": question,
            "who": 'agent',
            "need_response": True
        }
    )

    logger_info('Задача уходит в режим ожидания моего ответа на вопрос: "%s"' % question)

    await async_waiting_start()

    chat_last_message = queue_get()['chat_response'].get_nowait()

    return f"Пользователь ответил '{chat_last_message}'"


async def chat_me(text: str) -> str:
    """
    This is a messaging tool. Use it to send a message.
    The argument is a text string containing your message.
    The tool will return the word 'Accepted' as a result, indicating that the message was delivered to the user.
    """
    queue_get()['chat'].put(
        {
            "text": text,
            "who": 'agent',
        }
    )

    return 'Accepted'
