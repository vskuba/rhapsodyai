from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.user_repository import UserRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/user/list")
async def user_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    async with db:
        await db.execute("SELECT * FROM user")
        return {"result": await db.fetchall()}


@router.get("/user/{user_id}")
async def user_list(request: Request, user_id: int, user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    repo = UserRepository()
    return {"result": await repo.find(user_id)}


@router.post("/user")
async def user_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.USERS_CREATE]))):
    repo = UserRepository()
    user_id = await repo.add({
        "username": data.get("username"),
        "email": data.get("email"),
        "role": data.get("role", "user"),
        "llm_id": data.get("llm_id")
    })
    created_user = await repo.find(user_id)
    return {"result": created_user}


@router.put("/user/{user_id}")
async def user_update(request: Request, user_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.USERS_UPDATE]))):
    repo = UserRepository()
    # Only update fields that are provided (not None)
    update_data = {}
    if data.get("username") is not None:
        update_data["username"] = data.get("username")
    if data.get("email") is not None:
        update_data["email"] = data.get("email")
    if data.get("role") is not None:
        update_data["role"] = data.get("role")
    if data.get("llm_id") is not None:
        update_data["llm_id"] = data.get("llm_id")

    await repo.update(user_id, update_data)
    updated_user = await repo.find(user_id)
    return {"result": updated_user}


@router.delete("/user/{user_id}")
async def user_delete(request: Request, user_id: int, user=Depends(AuthChecker([AuthPermission.USERS_DELETE]))):
    repo = UserRepository()
    await repo.delete(user_id)
    return {"result": {"deleted": True, "id": user_id}}


@router.get("/role/list")
async def role_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    async with db:
        await db.execute("SELECT id, name FROM `role` ORDER BY id")
        return {"result": await db.fetchall()}
