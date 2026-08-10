from py_modules.mysql_.repository.abstract_repository import AbstractRepository


class ProjectTaskTypeRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'project_task_type'
