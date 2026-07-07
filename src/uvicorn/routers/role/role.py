from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/role/list")
async def role_list(
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.ROLE_VIEW]))
):
    async with db:
        await db.execute("SELECT id, name FROM `role` ORDER BY id")
        return {"result": await db.fetchall()}


@router.get("/role/{role_id}")
async def role_get(
        role_id: int,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.ROLE_VIEW]))
):
    async with db:
        await db.execute("SELECT id, name FROM `role` WHERE id = %s", role_id)
        role = await db.fetchone()
        if not role:
            return {"result": None}

        await db.execute("SELECT node_id FROM `role_node` WHERE role_id = %s", role_id)
        nodes = await db.fetchall()
        role["node_ids"] = [n["node_id"] for n in nodes]
        return {"result": role}


@router.post("/role")
async def role_create(
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.ROLE_CREATE]))
):
    data = await request.json()
    name = data.get("name")
    node_ids = data.get("node_ids", [])

    async with db:
        await db.execute("INSERT INTO `role` (name) VALUES (%s)", (name,))
        await db.execute("SELECT LAST_INSERT_ID()")
        role_id = (await db.fetchone())['LAST_INSERT_ID()']

        for node_id in node_ids:
            await db.execute("INSERT INTO `role_node` (role_id, node_id) VALUES (%s, %s)", (role_id, node_id))

        return {"result": {"id": role_id, "name": name}}


@router.put("/role/{role_id}")
async def role_update(
        role_id: int,
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.ROLE_UPDATE]))
):
    data = await request.json()
    name = data.get("name")
    node_ids = data.get("node_ids", [])

    async with db:
        await db.execute("UPDATE `role` SET name = %s WHERE id = %s", (name, role_id))

        await db.execute("DELETE FROM `role_node` WHERE role_id = %s", (role_id,))
        for node_id in node_ids:
            await db.execute("INSERT INTO `role_node` (role_id, node_id) VALUES (%s, %s)", (role_id, node_id))

        return {"result": {"id": role_id, "name": name}}


@router.delete("/role/{role_id}")
async def role_delete(
        role_id: int,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.ROLE_DELETE]))
):
    async with db:
        await db.execute("DELETE FROM `role` WHERE id = %s", (role_id,))
        return {"result": {"deleted": True, "id": role_id}}
