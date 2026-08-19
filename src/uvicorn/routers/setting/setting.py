from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
import os

from mysql_.mysql_ import mysql_get_db_async
from py_modules.setting_.setting_ import setting_get, setting_set, setting_delete
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.setting.setting_config import setting_config_public

router = APIRouter()


class SettingSaveJsonRequest(BaseModel):
    key: str
    value: str = ''
    node_id: int | None = None


@router.get("/setting/list")
async def setting_list_route(request: Request, user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    """Общие и нодовые настройки (пользовательские user_id-настройки не показываем)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, `key`, node_id, value FROM setting WHERE user_id IS NULL AND dynamic = 0 ORDER BY `key` ASC"
        )
        return {"result": await db.fetchall()}


@router.post("/setting")
async def setting_save_route(
        request: Request,
        json_request: SettingSaveJsonRequest,
        user=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))
):
    """Upsert настройки: пустое значение удаляет запись (нодовая ячейка возвращается к общей)."""
    key = json_request.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key is required")

    node_id = json_request.node_id or None

    if json_request.value == '':
        await setting_delete(key, node_id=node_id)
    else:
        await setting_set(key, json_request.value, node_id=node_id)

    return {"result": True}


@router.delete("/setting/key/{key}")
async def setting_delete_key_route(
        request: Request,
        key: str,
        user=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))
):
    """Удаляет настройку целиком: общее значение и все нодовые переопределения."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM setting WHERE `key` = %s AND user_id IS NULL",
            (key,)
        )
        await db.connection.commit()
    return {"result": True}


@router.get("/setting/{key}/user/{user_id}")
async def setting_get_route(request: Request, key: str, user_id: int, user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    return {"result": await setting_get(key, None, user_id)}


@router.post("/setting/{key}/user/{user_id}")
async def setting_set_route(request: Request, key: str, user_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.SETTING_UPDATE]))):
    value = data.get("value", None)
    if not value:
        return {"result": False, "error": "Missing 'value' in request body"}

    return {"result": await setting_set(key, value, user_id)}


@router.get("/setting/config")
async def setting_config_route(request: Request, user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    """Конфигурационные переменные для фронтенда админки.

    Mini App ходит не сюда, а в `/telegram-app/config`: у него своя авторизация, и
    `AuthChecker` его не пропускает — см. `src/setting/setting_config.py`.
    """
    return {"result": setting_config_public()}
