import ast
import importlib
import inspect
import json
import re
import sys
import traceback
from typing import Any

from fastapi import APIRouter, Request, Depends
from pathlib import Path

from src.mysql_.repository.tool_group_repository import ToolGroupRepository
from src.mysql_.repository.tool_repository import ToolRepository
from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.get("/tool/list")
async def tool_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db:
        sql = """
            SELECT t.*, tg.name as group_name
            FROM tool t
            LEFT JOIN tool_group tg ON t.group_id = tg.id
        """
        await db.execute(sql)
        return {"result": await db.fetchall()}


@router.get("/tool/{tool_name}")
async def tool_get(request: Request, tool_id: int):
    repo = ToolRepository()
    return {"result": await repo.find(tool_id)}


@router.get("/tool/group/list")
async def tool_group_list(request: Request):
    repo = ToolGroupRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.post("/tool/sync")
async def tool_sync(request: Request):
    # Корень проекта (папка src), чтобы python видел абсолютные импорты модулей
    src_root = Path(__file__).resolve().parent.parent.parent.parent  # uvicorn/routers/tool -> src
    tools_dir = src_root / "tool"

    if not tools_dir.exists():
        return {"result": "ok", "synced_count": 0, "message": "Папка tool не найдена"}

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
                            "description": description,
                            "args": args_json,
                            "raw_group_name": group_name
                        })

        except Exception as e:
            backtrace = traceback.format_exc()
            print(f"❌ Ошибка при импорте {filepath}: {e}\n{backtrace}")

    # 6. Запись в базу данных
    if all_tools_data:
        try:
            tool_repo = ToolRepository()
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
                    "description": tool["description"],
                    "args": tool["args"],
                    "group_id": db_groups_cache.get(tool["raw_group_name"], None)  # Привязываем ID группы
                })

            # Очищаем таблицу инструментов и массово вставляем структурированный батч
            await tool_repo.empty()
            await tool_repo.add_many(final_batch)

        except Exception as db_err:
            backtrace = traceback.format_exc()
            print(f"❌ Ошибка БД при синхронизации инструментов:\n{backtrace}")
            return {"result": "error", "message": f"Ошибка записи в БД: {str(db_err)}"}

    return {"result": "ok", "synced_count": len(all_tools_data)}


def _parse_output_keys_from_docstring(doc: str) -> dict | None:
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
