from fastapi import APIRouter, Depends

from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.get("/llm/list")
async def llm_list(db=Depends(mysql_get_db_async)):
    async with db:
        sql = """
            SELECT * FROM llm ORDER BY name ASC
        """
        await db.execute(sql)
        return {"result": await db.fetchall()}
