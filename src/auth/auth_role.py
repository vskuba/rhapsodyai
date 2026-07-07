from enum import Enum

from src.auth.auth_permission import AuthPermission


class AuthRole(str, Enum):
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"


AUTH_ROLE_PERMISSIONS = {
    AuthRole.ROLE_USER: {
        AuthPermission.USER_VIEW,
        AuthPermission.ROLE_VIEW,
        AuthPermission.AGENT_VIEW,
        AuthPermission.WORKFLOW_VIEW,
        AuthPermission.NODE_VIEW,
        AuthPermission.TOOL_VIEW,
        AuthPermission.LLM_VIEW,
        AuthPermission.FACT_VIEW,
        AuthPermission.FACT_COLLECTION_VIEW,
        AuthPermission.SESSION_VIEW,
        AuthPermission.SETTING_VIEW,
        AuthPermission.QUEUE_VIEW,
    },
    # Admin gets all permissions implicitly in AuthChecker
}