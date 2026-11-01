from fastapi import APIRouter, Depends
from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/detective/case_agents")
async def detective_case_agents(
        session_uuid: str,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.CHAT_ASK]))):
    """
    Агенты текущего дела игровой сессии detective (подозреваемые + сержант) с их
    id - для PWA-фронтенда (apps/detective): клик по чипсу с именем подозреваемого
    резолвит agent_id и переключает текущего агента чата. Динамические агенты
    дела создаются по конвенции 'case_<session_uuid>_sN' / 'sergeant_<session_uuid>'
    (см. src/tool/detective/detective_.py, detective_suspects_queue_build).
    Returns:
        result.suspects (list): [{id, title}, ...] в порядке создания.
        result.sergeant (dict|None): {id, title} последнего дела сессии, либо None.
    """
    async with db:
        await db.execute(
            "SELECT id, title, greeting FROM agent WHERE name LIKE %s ORDER BY id ASC",
            (f"case_{session_uuid}_%",)
        )
        suspects = await db.fetchall()

        await db.execute(
            "SELECT id, title, greeting FROM agent WHERE name = %s",
            (f"sergeant_{session_uuid}",)
        )
        sergeant = await db.fetchone()

    return {"result": {"suspects": suspects, "sergeant": sergeant}}
