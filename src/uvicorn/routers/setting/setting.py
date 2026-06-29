from fastapi import APIRouter, Request, Depends

from setting_.setting_ import setting_get, setting_set
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/setting/{key}/user/{user_id}")
async def setting_get_route(request: Request, key: str, user_id: int, user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    return {"result": await setting_get(key, None, user_id)}


@router.post("/setting/{key}/user/{user_id}")
async def setting_set_route(request: Request, key: str, user_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    value = data.get("value", None)
    if not value:
        return {"result": False, "error": "Missing 'value' in request body"}

    return {"result": await setting_set(key, value, user_id)}