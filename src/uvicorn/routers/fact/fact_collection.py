from fastapi import APIRouter, Request

from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository

router = APIRouter()


@router.get("/collection/list")
async def fact_collection_list(request: Request):
    repo = FactCollectionRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.get("/collection/{collection_id}")
async def fact_collection_list(request: Request, collection_id: int):
    repo = FactCollectionRepository()
    collection = await repo.find(collection_id)
    collection['schema'] = await ai_fact_collection_metadata_get(collection['name'])

    return {"result": collection}


@router.put("/collection/{collection_id}")
async def node_create(request: Request, collection_id: int, data: dict):
    repo = FactCollectionRepository()
    return {"result": await repo.update(collection_id, {
        "name": data.get("name"),
        "position": data.get("position"),
        "language": data.get("language"),
        "description": data.get("description")
    })}
