from fastapi import APIRouter, Request, Depends

from src.ai.ai_tool import ai_tools_sync
from src.mysql_.repository.tool_group_repository import ToolGroupRepository
from src.mysql_.repository.tool_repository import ToolRepository
from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.get("/tool/list")
async def tool_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db:
        sql = """
            SELECT t.*, tg.name as group_name
            FROM tool t
            LEFT JOIN tool_group tg ON t.group_id = tg.id
        """
        await db.execute(sql)
        return {"result": await db.fetchall()}


@router.get("/tool/{tool_name}")
async def tool_get(request: Request, tool_id: int):
    repo = ToolRepository()
    return {"result": await repo.find(tool_id)}


@router.get("/tool/group/list")
async def tool_group_list(request: Request):
    repo = ToolGroupRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.post("/tool/sync")
async def tool_sync(request: Request):
    return {"result": "ok", "synced_count": await ai_tools_sync(force=True)}
