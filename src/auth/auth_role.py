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
#
# `qa` — учётная запись автотестов и ручных проверок (`vova.tkachenko`). Права
# полные, потому что сюита создаёт и удаляет пользователей, роли, агентов и
# workflow: с view-набором почти каждый тест падал бы на 403. Роль отделена от
# `admin` не по объёму прав, а чтобы прогоны и ручные операции QA было видно
# в логах и сессиях отдельно от настоящего администратора.
AUTH_ROLE_PERMISSIONS = {
    'qa': set(AuthPermission),
}


def auth_role_permissions(role: str) -> set:
    """Права роли. У `admin` — полный набор, он в таблице переопределений не значится."""
    if role == AuthRole.ROLE_ADMIN:
        return set(AuthPermission)
    return AUTH_ROLE_PERMISSIONS.get(role, AUTH_PERMISSIONS_DEFAULT)


def auth_role_is_full(role: str) -> bool:
    """
    Роль с полным набором прав — `admin` и служебные роли вроде `qa`.

    Нужна там, где раньше стояло сравнение `role == 'admin'`: такие проверки
    отсекали любую другую полноправную роль, и QA-учётка получала 403 или урезанный
    ответ, имея на бумаге все права. Сверяем набор прав, а не имя роли.
    """
    return auth_role_permissions(role) == set(AuthPermission)
