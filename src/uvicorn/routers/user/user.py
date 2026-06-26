from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.user_repository import UserRepository

router = APIRouter()


@router.get("/user/list")
async def user_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db:
        await db.execute("SELECT * FROM user")
        return {"result": await db.fetchall()}


@router.get("/user/{user_id}")
async def user_list(request: Request, user_id: int):
    repo = UserRepository()
    return {"result": await repo.find(user_id)}


@router.post("/user")
async def user_create(request: Request, data: dict):
    repo = UserRepository()
    return {"result": await repo.add({
        "username": data.get("username"),
        "email": data.get("email")
    })}


@router.put("/user/{user_id}")
async def user_update(request: Request, user_id: int, data: dict):
    repo = UserRepository()
    return {"result": await repo.update(user_id, data)}
