from fastapi import APIRouter, Request, Depends, HTTPException
import uuid
import bcrypt

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.user_repository import UserRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/user/list")
async def user_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_VIEW]))):
    async with db:
        await db.execute(
            """
            SELECT u.*, r.name AS role, s.value AS language
            FROM `user` u
            LEFT JOIN `role` r ON r.id = u.role_id
            LEFT JOIN `setting` s ON s.user_id = u.id AND s.node_id IS NULL AND s.`key` = 'language'
            WHERE u.dynamic = 0
            """
        )
        users = await db.fetchall()

        # Fetch all user_node associations
        await db.execute("SELECT user_id, node_id FROM user_node")
        user_nodes = await db.fetchall()

        # Build mapping of user_id -> list of node_ids
        mapping = {}
        for row in user_nodes:
            uid = row["user_id"]
            nid = row["node_id"]
            if uid not in mapping:
                mapping[uid] = []
            mapping[uid].append(nid)

        for u in users:
            u["node_ids"] = mapping.get(u["id"], [])

        return {"result": users}


@router.get("/user/{user_id}")
async def user_get(request: Request, user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_VIEW]))):
    async with db:
        await db.execute(
            """
            SELECT u.*, r.name AS role, s.value AS language
            FROM `user` u
            LEFT JOIN `role` r ON r.id = u.role_id
            LEFT JOIN `setting` s ON s.user_id = u.id AND s.node_id IS NULL AND s.`key` = 'language'
            WHERE u.id = %s
            """,
            user_id
        )
        user_data = await db.fetchone()
        if user_data:
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", user_id)
            rows = await db.fetchall()
            user_data["node_ids"] = [row["node_id"] for row in rows]
    return {"result": user_data}


@router.post("/user")
async def user_create(request: Request, data: dict, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_CREATE]))):
    repo = UserRepository()
    insert_data = {
        "username": data.get("username"),
        "email": data.get("email"),
    }

    password = data.get("password")
    if password:
        insert_data["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    insert_data["role_id"] = data.get("role_id")

    user_id = await repo.add(insert_data)

    async with db:
        if "node_ids" in data and data["node_ids"]:
            for nid in data["node_ids"]:
                await db.execute("INSERT INTO user_node (user_id, node_id) VALUES (%s, %s)", (user_id, nid))

        await db.execute(
            "SELECT u.*, r.name AS role FROM `user` u LEFT JOIN `role` r ON r.id = u.role_id WHERE u.id = %s",
            user_id
        )
        created_user = await db.fetchone()
        if created_user:
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", user_id)
            created_user["node_ids"] = [row["node_id"] for row in await db.fetchall()]

    return {"result": created_user}


@router.put("/user/{user_id}")
async def user_update(request: Request, user_id: int, data: dict, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_UPDATE]))):
    repo = UserRepository()
    update_data = {}
    if data.get("username") is not None:
        update_data["username"] = data.get("username")
    if data.get("email") is not None:
        update_data["email"] = data.get("email")
    if data.get("role_id") is not None:
        update_data["role_id"] = data.get("role_id")

    if data.get("password"):
        password = str(data.get("password"))
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Пароль должен быть не короче 8 символов")
        update_data["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    if update_data:
        await repo.update(user_id, update_data)

    async with db:
        if "node_ids" in data:
            node_ids = data["node_ids"] or []
            await db.execute("DELETE FROM user_node WHERE user_id = %s", user_id)
            for nid in node_ids:
                await db.execute("INSERT INTO user_node (user_id, node_id) VALUES (%s, %s)", (user_id, nid))

        await db.execute(
            "SELECT u.*, r.name AS role FROM `user` u LEFT JOIN `role` r ON r.id = u.role_id WHERE u.id = %s",
            user_id
        )
        updated_user = await db.fetchone()
        if updated_user:
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", user_id)
            updated_user["node_ids"] = [row["node_id"] for row in await db.fetchall()]

    return {"result": updated_user}


@router.delete("/user/{user_id}")
async def user_delete(request: Request, user_id: int, user=Depends(AuthChecker([AuthPermission.USER_DELETE]))):
    repo = UserRepository()
    await repo.delete(user_id)
    return {"result": {"deleted": True, "id": user_id}}


@router.get("/role/list")
async def role_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_VIEW]))):
    async with db:
        await db.execute("SELECT id, name FROM `role` ORDER BY id")
        return {"result": await db.fetchall()}


@router.get("/user/{user_id}/token")
async def user_tokens_get(user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_VIEW]))):
    async with db:
        await db.execute("SELECT id, user_id, token FROM `user_access_token` WHERE user_id = %s", user_id)
        tokens = await db.fetchall()
        return {"result": tokens}


@router.post("/user/{user_id}/token")
async def user_token_create(user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_UPDATE]))):
    new_token = str(uuid.uuid4())
    async with db:
        await db.execute(
            "INSERT INTO `user_access_token` (user_id, token) VALUES (%s, %s)",
            (user_id, new_token)
        )
        await db.execute("SELECT LAST_INSERT_ID() as id")
        row = await db.fetchone()
        token_id = row["id"] if row else None

        return {
            "result": {
                "id": token_id,
                "user_id": user_id,
                "token": new_token
            }
        }


@router.delete("/user/token/{token_id}")
async def user_token_delete(token_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USER_DELETE]))):
    async with db:
        await db.execute("DELETE FROM `user_access_token` WHERE id = %s", token_id)
        return {"result": {"deleted": True, "id": token_id}}


@router.get("/user")
async def user_get_by_api_key(
    request: Request,
    user=Depends(AuthChecker([]))
):
    return {
        "result": {
            "id": user.user_id,
            "username": user.username
        }
    }
