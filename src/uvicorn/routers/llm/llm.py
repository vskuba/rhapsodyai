from fastapi import APIRouter, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/llm/list")
async def llm_list(db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    async with db:
        sql = """
            SELECT l.* 
            FROM `llm` l
            JOIN `user_llm` ul ON l.id = ul.llm_id
            WHERE ul.user_id = %s
            ORDER BY ul.rate_limit_at ASC, ul.position ASC
        """
        await db.execute(sql, (user.user_id,))
        return {"result": await db.fetchall()}