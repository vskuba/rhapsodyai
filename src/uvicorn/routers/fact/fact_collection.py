from fastapi import APIRouter, Request

from src.mysql_.repository.fact_collection_repository import FactCollectionRepository

router = APIRouter()


@router.get("/collection/list")
async def fact_collection_list(request: Request):
    repo = FactCollectionRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.get("/collection/{collection_id}")
async def fact_collection_list(request: Request, collection_id: int):
    repo = FactCollectionRepository()
    return {"result": await repo.find(collection_id)}
