import bcrypt
from fastapi import APIRouter, Request, HTTPException
from mysql_.mysql_ import mysql_get_db_async

router = APIRouter()


@router.post("/auth/login")
async def login(request: Request, data: dict):
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, username, email, password_hash, role, llm_id FROM `user` WHERE username = %s",
            (username,)
        )
        user = await db.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create session
    request.session["user_id"] = user['id']
    request.session["username"] = user['username']
    request.session["role"] = user['role']

    return {
        "message": "Успешный вход! Сессия создана.",
        "user": {
            "id": user['id'],
            "username": user['username'],
            "email": user['email'],
            "role": user['role']
        }
    }


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Сессия успешно завершена."}


@router.get("/auth/me")
async def me(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, username, email, role, llm_id FROM `user` WHERE id = %s",
            (user_id,)
        )
        user = await db.fetchone()

    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="User not found")

    return {"user": user}