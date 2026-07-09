from fastapi import APIRouter, Request, Depends

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
    return {"result": await repo.find(node_id)}


@router.post("/node")
async def node_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.NODE_CREATE]))):
    repo = NodeRepository()
    return {"result": await repo.add({
        "name": data.get("name"),
        "position": data.get("position")
    })}


@router.put("/node/{node_id}")
async def node_update(request: Request, node_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.NODE_UPDATE]))):
    repo = NodeRepository()
    # Обновляем только переданные поля: drag-and-drop сортировка шлет только position
    update_data = {key: data[key] for key in ("name", "position") if key in data}
    return {"result": await repo.update(node_id, update_data)}