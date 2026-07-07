from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/role/list")
async def role_list(
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.ROLE_VIEW]))
):
    async with db:
        await db.execute("SELECT id, name FROM `role` ORDER BY id")
        return {"result": await db.fetchall()}
