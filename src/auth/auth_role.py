from enum import Enum

from src.auth.auth_permission import AuthPermission


class AuthRole(str, Enum):
    ROLE_ADMIN = "admin"


# Базовый набор прав для любой не-админской роли.
# Роли создаются динамически в таблице `role` (manager_dating, manager_cashier, ...),
# поэтому права не хардкодятся по имени роли — все не-админы получают view-набор.
AUTH_PERMISSIONS_DEFAULT = {
    AuthPermission.USER_VIEW,
    AuthPermission.ROLE_VIEW,
    AuthPermission.AGENT_VIEW,
    AuthPermission.WORKFLOW_VIEW,
    AuthPermission.WORKFLOW_VARIABLE_VIEW,
    AuthPermission.WORKFLOW_TRACE_VIEW,
    AuthPermission.WORKFLOW_VARIABLE_UPDATE,
    AuthPermission.NODE_VIEW,
    AuthPermission.TOOL_VIEW,
    AuthPermission.LLM_VIEW,
    AuthPermission.FACT_VIEW,
    AuthPermission.FACT_COLLECTION_VIEW,
    AuthPermission.PLAN_VIEW,
    AuthPermission.PLANNING_VIEW,
    AuthPermission.PLANNING_UPDATE,
    AuthPermission.SESSION_VIEW,
    AuthPermission.SETTING_VIEW,
    AuthPermission.QUEUE_VIEW,
    AuthPermission.DESIGN_VIEW,
}

# Переопределения прав для конкретных ролей (админ получает все права в AuthChecker)
AUTH_ROLE_PERMISSIONS = {}
