from enum import Enum


class AuthPermission(str, Enum):
    USERS_VIEW = "users:view"
    USERS_CREATE = "users:create"
    AGENT_VIEW = "agent:view"