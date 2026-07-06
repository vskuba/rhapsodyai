from fastapi import APIRouter, Request, Depends, Header, HTTPException
import uuid
import bcrypt

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.user_repository import UserRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/user/list")
async def user_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    async with db:
        await db.execute("SELECT * FROM user")
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

        # Build mapping of user_id -> list of llm_ids
        await db.execute("SELECT user_id, llm_id FROM user_llm ORDER BY rate_limit_at ASC, `position` ASC")
        user_llms = await db.fetchall()

        llm_mapping = {}
        for row in user_llms:
            uid = row["user_id"]
            lid = row["llm_id"]
            if uid not in llm_mapping:
                llm_mapping[uid] = []
            llm_mapping[uid].append(lid)

        for u in users:
            u["node_ids"] = mapping.get(u["id"], [])
            u["llm_ids"] = llm_mapping.get(u["id"], [])

        return {"result": users}


@router.get("/user/{user_id}")
async def user_get(request: Request, user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    repo = UserRepository()
    user_data = await repo.find(user_id)
    if user_data:
        async with db:
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", user_id)
            rows = await db.fetchall()
            user_data["node_ids"] = [row["node_id"] for row in rows]

            await db.execute("SELECT llm_id FROM user_llm WHERE user_id = %s ORDER BY rate_limit_at ASC, `position` ASC", user_id)
            llm_rows = await db.fetchall()
            user_data["llm_ids"] = [row["llm_id"] for row in llm_rows]
    return {"result": user_data}


@router.post("/user")
async def user_create(request: Request, data: dict, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_CREATE]))):
    repo = UserRepository()
    insert_data = {
        "username": data.get("username"),
        "email": data.get("email"),
        "role": data.get("role", "user")
    }

    password = data.get("password")
    if password:
        insert_data["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    user_id = await repo.add(insert_data)

    # Insert user_llm relations if llm_ids or llm_id are passed
    llm_ids = data.get("llm_ids")
    if llm_ids is None and data.get("llm_id") is not None:
        llm_ids = [data.get("llm_id")]
    llm_ids = llm_ids or []

    async with db:
        for idx, lid in enumerate(llm_ids):
            await db.execute("INSERT INTO user_llm (user_id, llm_id, `position`) VALUES (%s, %s, %s)", (user_id, lid, idx))

        # Insert user_node relations if node_ids are passed
        if "node_ids" in data and data["node_ids"]:
            for nid in data["node_ids"]:
                await db.execute("INSERT INTO user_node (user_id, node_id) VALUES (%s, %s)", (user_id, nid))

        created_user = await repo.find(user_id)
        if created_user:
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", user_id)
            rows = await db.fetchall()
            created_user["node_ids"] = [row["node_id"] for row in rows]

            await db.execute("SELECT llm_id FROM user_llm WHERE user_id = %s ORDER BY rate_limit_at ASC, `position` ASC", user_id)
            llm_rows = await db.fetchall()
            created_user["llm_ids"] = [row["llm_id"] for row in llm_rows]

    return {"result": created_user}


@router.put("/user/{user_id}")
async def user_update(request: Request, user_id: int, data: dict, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_UPDATE]))):
    repo = UserRepository()
    # Only update fields that are provided (not None)
    update_data = {}
    if data.get("username") is not None:
        update_data["username"] = data.get("username")
    if data.get("email") is not None:
        update_data["email"] = data.get("email")
    if data.get("role") is not None:
        update_data["role"] = data.get("role")

    if update_data:
        await repo.update(user_id, update_data)

    async with db:
        # Sync user_llm relations if llm_ids or llm_id are passed
        if "llm_ids" in data or "llm_id" in data:
            llm_ids = data.get("llm_ids")
            if llm_ids is None and data.get("llm_id") is not None:
                llm_ids = [data.get("llm_id")]
            llm_ids = llm_ids or []

            # Delete old relations
            await db.execute("DELETE FROM user_llm WHERE user_id = %s", user_id)
            # Insert new relations
            for idx, lid in enumerate(llm_ids):
                await db.execute("INSERT INTO user_llm (user_id, llm_id, `position`) VALUES (%s, %s, %s)", (user_id, lid, idx))

        # Sync user_node relations if node_ids are passed in data
        if "node_ids" in data:
            node_ids = data["node_ids"] or []
            # Delete old relations
            await db.execute("DELETE FROM user_node WHERE user_id = %s", user_id)
            # Insert new relations
            for nid in node_ids:
                await db.execute("INSERT INTO user_node (user_id, node_id) VALUES (%s, %s)", (user_id, nid))

        updated_user = await repo.find(user_id)
        if updated_user:
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", user_id)
            rows = await db.fetchall()
            updated_user["node_ids"] = [row["node_id"] for row in rows]

            await db.execute("SELECT llm_id FROM user_llm WHERE user_id = %s ORDER BY rate_limit_at ASC, `position` ASC", user_id)
            llm_rows = await db.fetchall()
            updated_user["llm_ids"] = [row["llm_id"] for row in llm_rows]

    return {"result": updated_user}


@router.delete("/user/{user_id}")
async def user_delete(request: Request, user_id: int, user=Depends(AuthChecker([AuthPermission.USERS_DELETE]))):
    repo = UserRepository()
    await repo.delete(user_id)
    return {"result": {"deleted": True, "id": user_id}}


@router.get("/role/list")
async def role_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    async with db:
        await db.execute("SELECT id, name FROM `role` ORDER BY id")
        return {"result": await db.fetchall()}


@router.get("/user/{user_id}/token")
async def user_tokens_get(user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_VIEW]))):
    async with db:
        await db.execute("SELECT id, user_id, token FROM `user_access_token` WHERE user_id = %s", user_id)
        tokens = await db.fetchall()
        return {"result": tokens}


@router.post("/user/{user_id}/token")
async def user_token_create(user_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_UPDATE]))):
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
async def user_token_delete(token_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.USERS_DELETE]))):
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
