import ast
import importlib
import inspect
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, get_args, get_origin, Union

from logging_.logging_ import logger_info
from src.mysql_.repository.tool_group_repository import ToolGroupRepository
from src.mysql_.repository.tool_repository import ToolRepository

try:
    import types

    UNION_TYPES = (Union, types.UnionType)
except AttributeError:
    UNION_TYPES = (Union,)


async def ai_tool_sync(force: bool = False) -> int:
    tool_repo = ToolRepository()

    qty = await tool_repo.count_by({})
    if force == False and qty > 0:
        logger_info(f"⚠️ В таблице инструментов (tool) уже есть {qty} записей. Синхронизация не нужна.")
        return qty

    # Корень проекта (папка src), чтобы python видел абсолютные импорты модулей
    src_root = Path(__file__).resolve().parent.parent  # uvicorn/routers/tool -> src
    tools_dir = src_root / "tool"

    if not tools_dir.exists():
        return 0

    # Добавляем корень src в sys.path, чтобы внутренние импорты в файлах инструментов не падали
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    all_tools_data = []

    # 1. Находим все .py файлы в папке tool
    for filepath in tools_dir.rglob('*.py'):
        if filepath.name == '__init__.py':
            continue

        try:
            # 2. Находим имена функций через AST
            with open(filepath, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())

            func_names = [
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not node.name.startswith('_')
            ]

            if not func_names:
                continue

            # 3. Вычисляем правильное импортируемое имя модуля относительно src
            relative_path = filepath.relative_to(src_root)
            module_name = ".".join(relative_path.with_suffix('').parts)

            # Определяем имя группы на основе названия папки с большой буквы
            # Например: tool/github/github_.py -> папка "github" -> группа "Github"
            folder_name = filepath.parent.name
            group_name = folder_name.capitalize() if folder_name else "Общие"

            # 4. Динамический импорт с правильным контекстом путей
            spec = importlib.util.spec_from_file_location(module_name, str(filepath))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 5. Извлекаем докстринги и сигнатуру аргументов
                for name in func_names:
                    func = getattr(module, name, None)
                    if callable(func):
                        description = inspect.getdoc(func) or f"Автоматически импортированная функция {name}"

                        try:
                            sig = inspect.signature(func)

                            def clean_type_name(annotation) -> str:
                                if annotation == inspect.Parameter.empty or annotation == inspect.Signature.empty:
                                    return "Any"
                                s_raw = str(annotation)
                                if "empty" in s_raw:
                                    return "Any"
                                if hasattr(annotation, '__name__'):
                                    return annotation.__name__
                                if s_raw.startswith("<class '") and s_raw.endswith("'>"):
                                    return s_raw[8:-2]
                                return s_raw

                            # Собираем входящие аргументы (input)
                            input_dict = {}
                            for param_name, param in sig.parameters.items():
                                input_dict[param_name] = {
                                    "type": clean_type_name(param.annotation),
                                    "default": str(
                                        param.default) if param.default != inspect.Parameter.empty else "Required"
                                }

                            # Получаем базовый тип возвращаемого значения (output)
                            return_type = clean_type_name(sig.return_annotation)
                            output_payload: dict[str, Any] = {"type": return_type}

                            # Если функция возвращает dict, извлекаем ключи из её docstring
                            if return_type == "dict":
                                parsed_keys = _parse_output_keys_from_docstring(description)
                                if parsed_keys:
                                    output_payload["keys"] = parsed_keys

                            elif return_type in ("tuple", "Tuple"):
                                parsed_elements = _parse_output_tuple_from_docstring(description)
                                if parsed_elements:
                                    output_payload["keys"] = parsed_elements
                                else:
                                    if hasattr(sig.return_annotation, '__args__'):
                                        output_payload["keys"] = [
                                            clean_type_name(arg) for arg in sig.return_annotation.__args__
                                        ]

                            args_payload = {
                                "input": input_dict,
                                "output": output_payload
                            }
                            args_json = json.dumps(args_payload, ensure_ascii=False)

                        except Exception as sig_err:
                            args_json = json.dumps({
                                "input": {},
                                "output": {"type": "Any", "error": f"Не удалось распарсить сигнатуру: {sig_err}"}
                            }, ensure_ascii=False)

                        all_tools_data.append({
                            "name": name,
                            "path": str(filepath),
                            "description": description,
                            "args": args_json,
                            "raw_group_name": group_name
                        })

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Возникла ошибка: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

    # 6. Запись в базу данных
    if all_tools_data:
        try:
            group_repo = ToolGroupRepository()  # Класс должен наследоваться от AbstractRepository с table_name_get = "tool_group"

            # Локальный кэш, чтобы не дергать базу данных на каждую функцию
            db_groups_cache = {}

            # Собираем уникальные имена групп из найденных инструментов
            unique_group_names = set(tool["raw_group_name"] for tool in all_tools_data)

            # Синхронизируем группы в таблице tool_group
            for g_name in unique_group_names:
                # Ищем, существует ли уже группа с таким именем
                existing_group = await group_repo.find_one_by(criteria={"name": g_name})

                if existing_group:
                    # Извлекаем ID (учитываем формат возврата: словарь или объект)
                    if isinstance(existing_group, dict):
                        db_groups_cache[g_name] = existing_group.get('id')
                    else:
                        db_groups_cache[g_name] = getattr(existing_group, 'id', None)
                else:
                    # Если группы нет — создаем ее
                    new_group_id = await group_repo.add(data={"name": g_name})
                    db_groups_cache[g_name] = new_group_id

            # Явно пересобираем список словарей с жестко фиксированным порядком ключей под метод add_many
            final_batch = []
            for tool in all_tools_data:
                final_batch.append({
                    "name": tool["name"],
                    "path": tool["path"],
                    "description": tool["description"],
                    "args": tool["args"],
                    "group_id": db_groups_cache.get(tool["raw_group_name"], None)  # Привязываем ID группы
                })

            # Очищаем таблицу инструментов и массово вставляем структурированный батч
            await tool_repo.empty()
            await tool_repo.add_many(final_batch)

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Возникла ошибка: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            return 0

    return len(all_tools_data)


def ai_tool_args_prepare(tool_path: str, tool_name: str, raw_args: dict) -> tuple:
    """
    Загружает функцию инструмента и приводит сырые аргументы
    к ожидаемым типам на основе аннотаций.
    Возвращает кортеж: (func, tool_args) или (None, raw_args) в случае ошибки.
    """
    try:
        import importlib.util

        # Загружаем модуль или берем из кэша, если уже загружен
        module_name = f"dynamic_invoke_{tool_name}"
        if module_name in sys.modules:
            module = sys.modules[module_name]
        else:
            spec = importlib.util.spec_from_file_location(module_name, str(tool_path))
            if not spec or not spec.loader:
                raise FileNotFoundError(f"Не удалось найти файл инструмента по пути: {tool_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

        # Извлекаем целевую функцию
        func = getattr(module, tool_name, None)
        if not func or not callable(func):
            raise AttributeError(f"В модуле {tool_path} не найдена вызываемая функция с именем '{tool_name}'")

        func_signature = inspect.signature(func)
    except Exception as e:
        # Корректный возврат кортежа при ошибке, чтобы не ломать распаковку данных
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка инициализации сигнатуры для {tool_name}: {e}\n"
            f"Полный стек вызовов:\n{backtrace}"
        )
        return None, raw_args

    tool_args = {}

    for argument_name, variable_value in raw_args.items():
        if argument_name not in func_signature.parameters:
            tool_args[argument_name] = variable_value
            continue

        param = func_signature.parameters[argument_name]
        expected_type = param.annotation

        if expected_type is inspect.Parameter.empty or variable_value is None:
            tool_args[argument_name] = variable_value
            continue

        try:
            # 1. Обработка логического типа bool
            if expected_type is bool:
                if isinstance(variable_value, str):
                    tool_args[argument_name] = variable_value.lower() in ('true', '1', 'yes', 'on')
                else:
                    tool_args[argument_name] = bool(variable_value)

            # Безопасный парсинг сложных структур данных (dict и list) из JSON-строк
            elif expected_type is dict or expected_type is list:
                if isinstance(variable_value, str):
                    try:
                        # Пытаемся распарсить строку в реальный объект
                        tool_args[argument_name] = json.loads(variable_value)
                    except json.JSONDecodeError:
                        # Если строка не является JSON-ом, оставляем как есть, чтобы не упасть
                        tool_args[argument_name] = variable_value
                else:
                    tool_args[argument_name] = variable_value

            # 2. Обработка сложных типов Union / Optional (например, int | None)
            else:
                origin = get_origin(expected_type)

                if origin in UNION_TYPES:
                    sub_types = [t for t in get_args(expected_type) if t is not type(None)]
                    if sub_types:
                        target_type = sub_types[0]
                        if target_type is bool:
                            if isinstance(variable_value, str):
                                tool_args[argument_name] = variable_value.lower() in ('true', '1', 'yes', 'on')
                            else:
                                tool_args[argument_name] = bool(variable_value)
                        else:
                            tool_args[argument_name] = target_type(variable_value)
                    else:
                        tool_args[argument_name] = variable_value
                elif callable(expected_type):
                    # 3. Обычный базовый тип (int, float, str и т.д.)
                    tool_args[argument_name] = expected_type(variable_value)
                else:
                    tool_args[argument_name] = variable_value

        except (ValueError, TypeError) as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"⚠️ Ошибка приведения аргумента '{argument_name}' к типу {expected_type}: {e}. Передано сырое значение.\n"
                f"Полный стек вызовов:\n{backtrace}"
            )
            tool_args[argument_name] = variable_value

    return func, tool_args


def _parse_output_keys_from_docstring(doc: str) -> dict | None:
    """
    Пример использования:
    -----------
    Returns:
        dict: Словарь с данными пользователя, содержащий:
            user_id (int): Идентификатор в базе.
            username (str): Логин пользователя.
            is_active (bool): Статус блокировки.
            roles (list[str]): Список назначенных ролей.
    """
    if not doc:
        return None

    # 1. Находим секцию "Returns:" и забираем всё, что идет после неё до конца или до следующей крупной секции (например, Raises:)
    returns_match = re.search(r'Returns:\s*(.*)', doc, re.DOTALL | re.IGNORECASE)
    if not returns_match:
        return None

    returns_section = returns_match.group(1)

    # Прерываемся, если встретили начало другой стандартной секции docstring
    end_section_match = re.search(r'(Raises:|Args:|Examples:)', returns_section, re.IGNORECASE)
    if end_section_match:
        returns_section = returns_section[:end_section_match.start()]

    # 2. Ищем все вхождения формата "имя_ключа (тип): описание" по всей секции
    # Паттерн учитывает любые отступы в начале строки
    pattern = r'^\s*([\w_]+)\s*\(([\w_\[\], ]+)\):'
    keys_dict = {}

    for line in returns_section.split('\n'):
        match = re.search(pattern, line)
        if match:
            k_name = match.group(1)
            k_type = match.group(2)
            keys_dict[k_name] = {"type": k_type}

    return keys_dict if keys_dict else None


def _parse_output_tuple_from_docstring(doc: str) -> dict[str, Any]:
    """
        Пример использования:
        -----------
        Returns:
            tuple:
                0 (int): описание первого элемента кортежа
                1 (str): описание второго элемента кортежа
        """
    if not doc:
        return {}

    returns_match = re.search(r'Returns:\s*(.*)', doc, re.DOTALL | re.IGNORECASE)
    if not returns_match:
        return {}

    returns_section = returns_match.group(1)

    end_section_match = re.search(r'(Raises:|Args:|Examples:)', returns_section, re.IGNORECASE)
    if end_section_match:
        returns_section = returns_section[:end_section_match.start()]

    pattern = r'^\s*([\w_]+)\s*:?\s*\(([\w_\[\], ]+)\):'
    elements_dict = {}

    for line in returns_section.split('\n'):
        match = re.search(pattern, line)
        if match:
            e_name = match.group(1)
            e_type = match.group(2)
            elements_dict[e_name] = {"type": e_type}

    return elements_dict
