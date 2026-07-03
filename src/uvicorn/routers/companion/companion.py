import traceback

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
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
        user: AuthSession = Depends(AuthChecker([]))
) -> dict:
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
        user: AuthSession = Depends(AuthChecker([]))
) -> dict:
    repo = CompanionRepository()
    name = data.name
    title = data.title or name
    try:
        entity_companion = await repo.find_one_by({"name": name})
        if not entity_companion:
            # Create a new companion with name and title
            companion_data = {"name": name, "title": title}
            companion_id = await repo.add(companion_data)
            entity_companion = {"id": companion_id, "name": name, "title": title}
        elif data.title and entity_companion.get("title") != data.title:
            # Если title изменился, обновим его в БД
            await repo.update(entity_companion["id"], {"title": data.title})
            entity_companion["title"] = data.title

        return {"result": entity_companion}
    except Exception as e:
        logger_info(f"Error in companion_get_or_create: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
