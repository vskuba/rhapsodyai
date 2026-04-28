from fastapi import APIRouter, Request

from setting_.setting_ import setting_get, setting_set

router = APIRouter()


@router.get("/setting/{key}/user/{user_id}")
async def setting(request: Request, key: str, user_id: int):
    return {"result": await setting_get(key, None, user_id)}


@router.post("/setting/{key}/user/{user_id}")
async def setting(request: Request, key: str, user_id: int, data: dict):
    value = data.get("value", None)
    if not value:
        return {"result": False, "error": "Missing 'value' in request body"}

    return {"result": await setting_set(key, value, user_id)}
