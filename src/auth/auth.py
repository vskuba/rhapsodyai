from fastapi import HTTPException, Request, status, Depends

from logging_.logging_ import logger_info
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import auth_role_permissions
from src.auth.auth_session import AuthSession


class AuthChecker:
    def __init__(self, required_permissions: list[AuthPermission]):
        self.required_permissions = required_permissions

    async def __call__(self, request: Request) -> AuthSession:
        current_user = await get_current_user(request)

        logger_info('🔒 Текущий пользователь: ' + str(current_user))

        user_permissions = auth_role_permissions(current_user.role)

        # 2. Проверяем, есть ли у пользователя ВСЕ необходимые для эндпоинта права
        for perm in self.required_permissions:
            if perm not in user_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас недостаточно прав для выполнения этой операции"
                )

        return current_user


async def get_current_user(request: Request) -> AuthSession:
    """Пользователь запроса: сессия админки либо токен доступа.

    Токен принимается двумя заголовками — `Authorization: Bearer <token>` и
    `X-API-KEY`. Первый — общепринятый и им пользуются готовые клиенты; второй
    остаётся, потому что на нём уже написаны интеграции, и ломать их незачем.

    Проверка живёт здесь одна на всех: точки зовут `AuthChecker`, а он — эту
    функцию. Поэтому новый способ авторизации появляется сразу во всех точках, а
    не в тех, куда его не забыли добавить.
    """
    user_id = request.session.get("user_id", 0)
    username = request.session.get("username", '')
    role = request.session.get("role", '')

    if user_id and username and role:
        return AuthSession(user_id=user_id, username=username, role=role)

    token = auth_token_of(request)
    if token:
        return await auth_token_user(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated"
    )


def auth_token_of(request: Request) -> str:
    """Токен доступа из заголовков запроса. Нет ни одного — пустая строка.

    `Bearer` в `Authorization` необязателен: клиенты шлют и голый токен, а
    отказывать им из-за отсутствующего слова — придирка, а не безопасность.
    """
    header = (request.headers.get("Authorization") or '').strip()
    if header:
        parts = header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() in ('bearer', 'token'):
            return parts[1].strip()

        return header

    return (request.headers.get("X-API-KEY") or request.headers.get("x-api-key") or '').strip()


async def auth_token_user(token: str) -> AuthSession:
    """Владелец токена доступа. Неизвестный токен — 401, а не безымянный гость."""
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
            (token,)
        )
        row = await db.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )

    role = row["role"] or ''
    if row["user_id"] == 1:  # Если пользователь с ID 1, то он admin
        role = "admin"

    return AuthSession(user_id=row["user_id"], username=row["username"], role=role)