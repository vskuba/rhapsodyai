from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.get("/user/list")
async def user_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        await cursor.execute("SELECT * FROM user")
        return {"result": await cursor.fetchall()}
