from fastapi import HTTPException, Request, status, Depends

from logging_.logging_ import logger_info
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import AUTH_ROLE_PERMISSIONS
from src.auth.auth_session import AuthSession


class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> AuthSession:
        current_user = await get_current_user(request)

        logger_info('🔒 Текущий пользователь: ' + str(current_user))

        if current_user.role == "admin":
            return current_user

        user_permissions = AUTH_ROLE_PERMISSIONS.get(current_user.role, [])

        # 2. Проверяем, есть ли у пользователя ВСЕ необходимые для эндпоинта права
        for perm in self.required_permissions:
            if perm not in user_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас недостаточно прав для выполнения этой операции"
                )

        return current_user


async def get_current_user(request: Request) -> AuthSession:
    """Extract user from session cookie."""
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    role = request.session.get("role")

    if not user_id or not username or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    return AuthSession(user_id=user_id, username=username, role=role)