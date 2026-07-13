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


@router.post("/collection")
async def fact_collection_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_CREATE]))):
    repo = FactCollectionRepository()
    new_id = await repo.add({
        "node_id": data.get("node_id", None),
        "name": data.get("name"),
        # Заголовок не задан — по умолчанию совпадает с системным именем
        "title": data.get("title") or data.get("name"),
        "field": data.get("field", "document_id,category,language,document,tags"),
        "position": data.get("position", 0),
        "language": data.get("language", "en,ua,ru"),
        "description": data.get("description", "")
    })
    return {"result": new_id}


@router.put("/collection/{collection_id}")
async def fact_collection_update(request: Request, collection_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_UPDATE]))):
    repo = FactCollectionRepository()
    return {"result": await repo.update(collection_id, {
        "node_id": data.get("node_id", None),
        "name": data.get("name"),
        "title": data.get("title") or data.get("name"),
        "position": data.get("position"),
        "language": data.get("language"),
        "description": data.get("description")
    })}


@router.delete("/collection/{collection_id}")
async def fact_collection_delete(request: Request, collection_id: int, user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_DELETE]))):
    repo = FactCollectionRepository()
    success = await repo.delete(collection_id)
    return {"result": success}
