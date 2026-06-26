from enum import Enum

from src.auth.auth_permission import AuthPermission


class AuthRole(str, Enum):
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"


AUTH_ROLE_PERMISSIONS = {
    AuthRole.ROLE_USER: {
        AuthPermission.USERS_VIEW
    },
}