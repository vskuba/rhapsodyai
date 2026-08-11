"""
Типы задач команды из таблицы `project_task_type`: справочник, по которому
`/admin/task` и `/admin/team` подписывают задачи. Только чтение — сам справочник
наполняется через seed.
"""
from src.mysql_.repository.project.task_type_repository import ProjectTaskTypeRepository


async def team_task_type_list() -> list:
    """Все типы задач в порядке добавления."""
    return await ProjectTaskTypeRepository().find_by({}, order_by='id')
