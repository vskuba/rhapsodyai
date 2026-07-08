# '*' = все поля
ALL_FIELDS = '*'

# Политика полей: entity -> action ('write'|'read') -> role -> набор полей.
# Роли динамические (таблица `role`), поэтому '*' — fallback для любой не-админской роли.
# admin проверять не нужно — он всегда получает ALL_FIELDS в auth_allowed_fields.
AUTH_FIELD_POLICY = {
    'agent_workflow_variable': {
        'fields': {'name', 'description', 'default', 'workflow_ids', 'node_id', 'position', 'use_as_hint'},
        'write': {
            '*': {'default'},  # не-админы пишут только поле `default`
            # 'manager_dating': {'default', 'description'},  # пример точечной настройки роли
        },
        'read': {
            # id/name/node_id нужны фронту для списка и PUT; скрываем только служебные поля
            '*': {'id', 'name', 'node_id', 'default', 'position', 'use_as_hint', 'workflow_ids'},
        },
    },
}


def auth_fields_allowed(entity: str, action: str, role: str):
    """Вернёт ALL_FIELDS или set разрешённых для роли полей."""
    if role == 'admin':
        return ALL_FIELDS
    policy = AUTH_FIELD_POLICY.get(entity, {}).get(action, {})
    return policy.get(role, policy.get('*', set()))


def auth_fields_filter_for_update(entity: str, action: str, role: str, data: dict) -> tuple[list, dict]:
    """Отфильтровать dict, оставив только разрешённые роли поля."""
    fields = [f for f in AUTH_FIELD_POLICY.get(entity, {}).get('fields', {}) if f in data]
    allowed = auth_fields_allowed(entity, action, role)
    if allowed == ALL_FIELDS:
        return fields, data
    return [f for f in fields if f in allowed], {k: v for k, v in data.items() if k in allowed}
