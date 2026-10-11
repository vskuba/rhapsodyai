import inspect
import traceback
from typing import cast, Callable, Awaitable, Any
from fastapi import APIRouter, Request, Depends, HTTPException

from logging_.logging_ import logger_info
from src.ai.ai_tool import ai_tool_sync, ai_tool_args_prepare
from src.mysql_.repository.tool_group_repository import ToolGroupRepository
from src.mysql_.repository.tool_repository import ToolRepository
from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/tool/list")
async def tool_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.TOOL_VIEW]))):
    """Все инструменты установки — по алфавиту: сперва группа, внутри имя.

    ## ⚠⚠ Порядок задаёт запрос, а не тот, кто показывает

    Без `ORDER BY` база отдаёт строки как ей удобно, и список в селекте шага
    `tool_invoke` выстраивался случайно: `Weather`, `List`, `Claude_`,
    `Datetime_`, … Человек, заведший инструмент в новой группе, не находил его
    глазами и решал, что выкладка не довезла, — так и случилось с `Chat` после
    деплоя 11.10.2026, хотя инструмент в реестре был.

    ⚠ Сортировка здесь, а не на фронтенде: потребителей у списка несколько, и
    каждый сортировал бы по-своему (или забывал бы вовсе).

    ⚠ Безымянная группа уходит **вниз** (`tg.name IS NULL` первым ключом): в
    MySQL `NULL` при `ASC` идёт первым, и инструменты без группы возглавили бы
    список.
    """
    async with db:
        sql = """
            SELECT t.*, tg.name as group_name
            FROM tool t
            LEFT JOIN tool_group tg ON t.group_id = tg.id
            ORDER BY tg.name IS NULL, tg.name, t.name
        """
        await db.execute(sql)
        return {"result": await db.fetchall()}


@router.get("/tool/{tool_id}")
async def tool_get(request: Request, tool_id: int, user=Depends(AuthChecker([AuthPermission.TOOL_VIEW]))):
    repo = ToolRepository()
    return {"result": await repo.find(tool_id)}


@router.get("/tool/group/list")
async def tool_group_list(request: Request, user=Depends(AuthChecker([AuthPermission.TOOL_VIEW]))):
    repo = ToolGroupRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.post("/tool/sync")
async def tool_sync(request: Request, user=Depends(AuthChecker([AuthPermission.TOOL_UPDATE]))):
    return {"result": "ok", "synced_count": await ai_tool_sync(force=True)}


@router.post("/tool/test/{tool_id}")
async def tool_test(request: Request, tool_id: int, args: dict, user=Depends(AuthChecker([AuthPermission.TOOL_TEST]))):
    """
    Роутер для изолированного тестирования динамических инструментов.
    Приводит типы аргументов на основе аннотаций функции и выполняет её.
    """
    repo = ToolRepository()
    entity_tool = await repo.find(tool_id)

    if not entity_tool:
        raise HTTPException(
            status_code=404,
            detail=f"Инструмент с ID {tool_id} не найден в базе данных."
        )

    tool_name = entity_tool.get('name')
    tool_path = entity_tool.get('path')

    try:
        # 3. Подготовка купажа (функция + типизированные аргументы)
        func, tool_args = ai_tool_args_prepare(tool_path, tool_name, args)

        if func is None:
            raise ValueError(f"Не удалось подготовить функцию '{tool_name}' к запуску (сигнатура повреждена).")

        logger_info(f"⚙️ Входящие аргументы: {args} -> Подготовленные аргументы: {tool_args}")

        # 4. Вызываем функцию с учетом асинхронности (async def / def)
        if inspect.iscoroutinefunction(func):
            async_func = cast(Callable[..., Awaitable[Any]], func)
            raw_result = await async_func(**tool_args)
        else:
            raw_result = func(**tool_args)

        # 5. Возвращаем подробный ответ для тестирования
        return {
            "status": "success",
            "result": raw_result,
        }

    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка при запуске инструмента '{tool_name}': {e}.\n"
            f"Полный стек вызовов:\n{backtrace}"
        )
        return {
            "status": "error",
            "result": str(e)
        }