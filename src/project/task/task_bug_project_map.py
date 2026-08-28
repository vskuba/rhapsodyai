"""
Определение project_id по workflow_id для авто-создания баг-задач.

Публичные функции:
    task_bug_project_map_for_workflow — lookup project_id по workflow_id
"""
import json

from config.config import config_get


def task_bug_project_map_for_workflow(workflow_id: int) -> int:
    """
    Определяет project_id по workflow_id.

    Сначала проверяет конфигурационную мапу BUG_TASK_WORKFLOW_PROJECT_MAP.
    Если workflow не найден — возвращает BUG_TASK_DEFAULT_PROJECT_ID.

    Args:
        workflow_id: ID workflow из agent_workflow_trace.workflow_id.

    Returns:
        project_id для создания баг-задачи.
    """
    default = int(config_get('BUG_TASK_DEFAULT_PROJECT_ID', '1'))

    raw_map = config_get('BUG_TASK_WORKFLOW_PROJECT_MAP', '{}')
    try:
        workflow_map = json.loads(raw_map)
    except (json.JSONDecodeError, TypeError):
        return default

    wid = str(workflow_id)
    for wid_key, value in workflow_map.items():
        if str(wid_key) == wid:
            # value может быть числом или объектом {"project_id": 7}
            if isinstance(value, dict):
                return int(value.get('project_id', default))
            return int(value)

    return default
