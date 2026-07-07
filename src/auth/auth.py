from fastapi import HTTPException, Request, status, Depends

from logging_.logging_ import logger_info
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import AUTH_ROLE_PERMISSIONS, AUTH_PERMISSIONS_DEFAULT
from src.auth.auth_session import AuthSession


class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> AuthSession:
        current_user = await get_current_user(request)

        logger_info('🔒 Текущий пользователь: ' + str(current_user))

        if current_user.role == "admin":
            return current_user

        user_permissions = AUTH_ROLE_PERMISSIONS.get(current_user.role, AUTH_PERMISSIONS_DEFAULT)

        # 2. Проверяем, есть ли у пользователя ВСЕ необходимые для эндпоинта права
        for perm in self.required_permissions:
            if perm not in user_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас недостаточно прав для выполнения этой операции"
                )

        return current_user


async def get_current_user(request: Request) -> AuthSession:
    """Extract user from session cookie or X-API-KEY header."""
    user_id = request.session.get("user_id", 0)
    username = request.session.get("username", '')
    role = request.session.get("role", '')

    if user_id and username and role:
        return AuthSession(user_id=user_id, username=username, role=role)

    # Попробуем авторизовать по X-API-KEY хедеру
    x_api_key = request.headers.get("X-API-KEY") or request.headers.get("x-api-key")
    if x_api_key:
        from mysql_.mysql_ import mysql_get_db_async
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                SELECT u.id as user_id, u.username, r.name as role
                FROM `user_access_token` t
                JOIN `user` u ON t.user_id = u.id
                LEFT JOIN `role` r ON r.id = u.role_id
                WHERE t.token = %s
                """,
                (x_api_key,)
            )
            row = await db.fetchone()
            if row:
                user_id = row["user_id"]
                role = row["role"] or ''
                if user_id == 1: # Если пользователь с ID 1, то он admin
                    role = "admin"

                return AuthSession(user_id=user_id, username=row["username"], role=role)
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API Key"
                )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated"
    )