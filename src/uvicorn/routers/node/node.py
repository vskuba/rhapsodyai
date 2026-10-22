from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.node_repository import NodeRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/node/list")
async def node_list(request: Request, user=Depends(AuthChecker([AuthPermission.NODE_VIEW]))):
    repo = NodeRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.get("/node/{node_id}")
async def node_get(request: Request, node_id: int, user=Depends(AuthChecker([AuthPermission.NODE_VIEW]))):
    repo = NodeRepository()
    node = await repo.find(node_id)
    if node:
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT llm_id FROM node_llm WHERE node_id = %s ORDER BY rate_limit_at ASC, `position` ASC",
                node_id
            )
            llm_rows = await db.fetchall()
            node["llm_ids"] = [row["llm_id"] for row in llm_rows]
    return {"result": node}


@router.post("/node")
async def node_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.NODE_CREATE]))):
    repo = NodeRepository()
    node_id = await repo.add({
        "name": data.get("name"),
        "position": data.get("position"),
        # Колонка NOT NULL DEFAULT 1 — подставляем единицу явно, иначе None уронит вставку.
        "llm_parallel_per_agent_max": data.get("llm_parallel_per_agent_max") or 1,
    })

    llm_ids = data.get("llm_ids") or []
    async with mysql_get_db_async() as db:
        for idx, lid in enumerate(llm_ids):
            await db.execute("INSERT INTO node_llm (node_id, llm_id, `position`) VALUES (%s, %s, %s)", (node_id, lid, idx))

    return {"result": node_id}


@router.put("/node/{node_id}")
async def node_update(request: Request, node_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.NODE_UPDATE]))):
    repo = NodeRepository()
    # Обновляем только переданные поля: drag-and-drop сортировка шлет только position.
    # ⚠ Список белый: поле, которого здесь нет, форма отправит, а сервер молча
    # выбросит — ни ошибки, ни следа. Так потерялся llm_parallel_per_agent_max:
    # значение «сбрасывалось» на прежнее при каждом сохранении.
    update_data = {key: data[key] for key in ("name", "position", "llm_parallel_per_agent_max") if key in data}
    result = await repo.update(node_id, update_data)

    if "llm_ids" in data:
        llm_ids = data.get("llm_ids") or []
        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM node_llm WHERE node_id = %s", node_id)
            for idx, lid in enumerate(llm_ids):
                await db.execute("INSERT INTO node_llm (node_id, llm_id, `position`) VALUES (%s, %s, %s)", (node_id, lid, idx))

    return {"result": result}


@router.delete("/node/{node_id}")
async def node_delete(request: Request, node_id: int, user=Depends(AuthChecker([AuthPermission.NODE_DELETE]))):
    repo = NodeRepository()
    deleted = await repo.delete(node_id)
    if not deleted:
        return {"status": "error", "message": "Нода не найдена"}
    return {"status": "success", "result": "Нода удалена"}