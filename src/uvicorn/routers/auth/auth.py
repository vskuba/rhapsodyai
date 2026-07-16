import bcrypt
from fastapi import APIRouter, Request, HTTPException
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get, setting_set
from i18n_.i18n_ import i18n_languages_parse
from src.tool.setting.setting_ import setting_value_get

router = APIRouter()


@router.post("/auth/login")
async def login(request: Request, data: dict):
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT u.id, u.username, u.email, u.password_hash, r.name as role "
            "FROM `user` u LEFT JOIN `role` r ON r.id = u.role_id "
            "WHERE u.username = %s",
            (username,)
        )
        user = await db.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create session
    user_id = user['id']
    role = user['role'] or ''
    if user_id == 1:  # Если пользователь с ID 1, то он админ
        role = "admin"

    request.session["user_id"] = user_id
    request.session["username"] = user['username']
    request.session["role"] = role

    return {
        "message": "Успешный вход! Сессия создана.",
        "user": {
            "id": user_id,
            "username": user['username'],
            "email": user['email'],
            "role": role
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
            "SELECT u.id, u.username, u.email, r.name as role FROM `user` u LEFT JOIN role r ON r.id = u.role_id WHERE u.id = %s",
            (user_id,)
        )
        user = await db.fetchone()

        if user:
            # Получаем все связанные LLM
            await db.execute("SELECT llm_id FROM user_llm WHERE user_id = %s ORDER BY rate_limit_at ASC, `position` ASC", (user_id,))
            llm_rows = await db.fetchall()
            user['llm_ids'] = [row['llm_id'] for row in llm_rows]

    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="User not found")

    return {"user": user}


@router.get("/auth/me/languages")
async def me_languages(request: Request):
    """Языки, доступные текущему пользователю по его нодам, и его текущий выбор."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    languages = await _user_languages_get(user_id)
    current = str(await setting_get('language', '', user_id=user_id) or '').strip().lower()
    if current not in languages:
        current = None

    return {"result": {"languages": languages, "current": current}}


@router.put("/auth/me")
async def update_me(request: Request, data: dict):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    email = data.get("email")

    if email is None:
        raise HTTPException(status_code=400, detail="Email is required")

    # Язык общения: пользовательская настройка (setting c user_id),
    # принимается только язык из доступных пользователю нод
    language = str(data.get("language") or '').strip().lower()
    if language:
        if language not in await _user_languages_get(user_id):
            raise HTTPException(status_code=400, detail=f"Язык '{language}' недоступен для ваших нод")
        await setting_set('language', language, user_id=user_id)

    async with mysql_get_db_async() as db:
        # Обновляем email в user
        await db.execute(
            "UPDATE `user` SET email = %s WHERE id = %s",
            (email, user_id)
        )

        await db.execute(
            "SELECT u.id, u.username, u.email, r.name as role FROM `user` u LEFT JOIN role r ON r.id = u.role_id WHERE u.id = %s",
            (user_id,)
        )
        updated_user = await db.fetchone()

        if updated_user:
            await db.execute("SELECT llm_id FROM user_llm WHERE user_id = %s ORDER BY rate_limit_at ASC, `position` ASC", (user_id,))
            llm_rows = await db.fetchall()
            updated_user['llm_ids'] = [row['llm_id'] for row in llm_rows]

    return {"message": "Профиль успешно обновлен.", "user": updated_user}


async def _user_languages_get(user_id: int) -> list[str]:
    """Языки, доступные пользователю: объединение языков всех его нод
    (настройка 'languages', нодовая перекрывает общую). Без нод — глобальная настройка."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", (user_id,))
        node_ids = [r['node_id'] for r in await db.fetchall()]

    languages = []
    for node_id in (node_ids or [0]):
        raw = (await setting_value_get('languages', node_id, 'ru'))['value']
        for lang in i18n_languages_parse(raw):
            if lang not in languages:
                languages.append(lang)
    return languages
