import traceback

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.auth.auth_session import AuthSession
from src.mysql_.repository.companion_repository import CompanionRepository

router = APIRouter()


class CompanionJsonRequest(BaseModel):
    name: str
    title: str | None = None


@router.get("/companion/list")
async def companion_list(
        request: Request,
        db=Depends(mysql_get_db_async),
        user: AuthSession = Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
) -> dict:
    """Справочник собеседников целиком.

    ⚠⚠ Закрыт `session:view`, а не пустым списком. Под `AuthChecker([])` сюда
    проходил всякий вошедший — в том числе анонимный гость с `/auth/guest`, —
    и получал имена всех собеседников установки разом.
    """
    repo = CompanionRepository()
    try:
        companions = await repo.find_by({}, order_by='id DESC')
        return {"result": companions}
    except Exception as e:
        logger_info(f"Error in companion_list: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/companion")
async def companion_get_or_create(
        request: Request,
        data: CompanionJsonRequest,
        db=Depends(mysql_get_db_async),
        user: AuthSession = Depends(
            AuthChecker([AuthPermission.SESSION_COMPANION_WRITE]))
) -> dict:
    """Найти собеседника по ключу либо завести — одной точкой.

    ⚠ Право то же, что у трёх `/chat/message/*`: это запись в справочник, с
    которого начинается память агента о человеке.
    """
    repo = CompanionRepository()
    name = data.name.lower()
    title = data.title or name
    try:
        entity_companion = await repo.find_one_by({"unique_id": name})
        if not entity_companion:
            # Create a new companion with name and title
            # ⚠ `name` в запросе — **ключ** записи, а не имя человека: имя
            # приходит в `title`. Столбец переименован в `unique_id`, поле
            # запроса осталось прежним — его шлют соседние проекты.
            companion_data = {"unique_id": name, "title": title}
            companion_id = await repo.add(companion_data)
            # ⚠ Ответ собирается руками и обязан совпадать с тем, что отдаёт
            # поиск: разойдись поля — вызывающий получал бы `name` у новой
            # записи и `unique_id` у найденной, то есть разное на один запрос.
            entity_companion = {"id": companion_id, "unique_id": name,
                                "title": title}
        elif data.title and entity_companion.get("title") != data.title:
            # Если title изменился, обновим его в БД
            await repo.update(entity_companion["id"], {"title": data.title})
            entity_companion["title"] = data.title

        return {"result": entity_companion}
    except Exception as e:
        logger_info(f"Error in companion_get_or_create: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
