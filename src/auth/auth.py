from fastapi import HTTPException, status

from logging_.logging_ import logger_info
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import AUTH_ROLE_PERMISSIONS
from src.auth.auth_session import AuthSession


class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    def __call__(self):
        current_user = get_current_user()

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


def get_current_user() -> AuthSession:
    # Здесь должен быть ваш код извлечения сессии из Header/Cookie
    # Например: payload = jwt.decode(token, SECRET_KEY)
    return AuthSession(user_id=1, username="ivan_admin", role="admin")