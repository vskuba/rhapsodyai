from fastapi import APIRouter, Request

from src.mysql_.repository.node_repository import NodeRepository

router = APIRouter()


@router.get("/node/list")
async def node_list(request: Request):
    repo = NodeRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.get("/node/{node_id}")
async def node_list(request: Request, node_id: int):
    repo = NodeRepository()
    return {"result": await repo.find(node_id)}
