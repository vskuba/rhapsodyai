from fastapi import APIRouter, Request, Depends

from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/collection/list")
async def fact_collection_list(request: Request, user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_VIEW]))):
    repo = FactCollectionRepository()
    return {"result": await repo.find_by({}, 'name ASC')}


@router.get("/collection/{collection_id}")
async def fact_collection_get(request: Request, collection_id: int, user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_VIEW]))):
    repo = FactCollectionRepository()
    collection = await repo.find(collection_id)
    collection['schema'] = await ai_fact_collection_metadata_get(collection['name'])

    return {"result": collection}


@router.put("/collection/{collection_id}")
async def fact_collection_update(request: Request, collection_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_UPDATE]))):
    repo = FactCollectionRepository()
    return {"result": await repo.update(collection_id, {
        "name": data.get("name"),
        "position": data.get("position"),
        "language": data.get("language"),
        "description": data.get("description")
    })}