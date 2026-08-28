from src.auth.auth_role import auth_role_is_full

# '*' = все поля
ALL_FIELDS = '*'

# Политика полей: entity -> action ('write'|'read') -> role -> набор полей.
# Роли динамические (таблица `role`), поэтому '*' — fallback для любой урезанной роли.
# Полноправные роли (`admin`, `qa`) сюда не попадают — им ALL_FIELDS в auth_field_policy_fields_allowed.
AUTH_FIELD_POLICY = {
    'node_variable': {
        'fields': {'name', 'title', 'description', 'default', 'node_id', 'position', 'type', 'role_ids', 'workflow_ids'},
        'write': {
            '*': {'default'},  # не-админы пишут только поле `default`
            # 'manager_dating': {'default', 'description'},  # пример точечной настройки роли
        },
        'read': {
            # id/name/node_id нужны фронту для списка и PUT; скрываем только служебные поля
            '*': {'id', 'name', 'title', 'node_id', 'default', 'position', 'type'},
        },
    },
}


def auth_field_policy_fields_allowed(entity: str, action: str, role: str):
    """Вернёт ALL_FIELDS или set разрешённых для роли полей."""
    if auth_role_is_full(role):
        return ALL_FIELDS
    policy = AUTH_FIELD_POLICY.get(entity, {}).get(action, {})
    return policy.get(role, policy.get('*', set()))


def auth_field_policy_fields_filter_for_update(entity: str, action: str, role: str, data: dict) -> tuple[list, dict]:
    """Отфильтровать dict, оставив только разрешённые роли поля."""
    fields = [f for f in AUTH_FIELD_POLICY.get(entity, {}).get('fields', {}) if f in data]
    allowed = auth_field_policy_fields_allowed(entity, action, role)
    if allowed == ALL_FIELDS:
        return fields, data
    return [f for f in fields if f in allowed], {k: v for k, v in data.items() if k in allowed}
