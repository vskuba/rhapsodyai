from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.get("/node/list")
async def node_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        sql = """
            SELECT * FROM node ORDER BY name ASC
        """
        await cursor.execute(sql)
        return {"result": await cursor.fetchall()}