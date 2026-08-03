from mysql_.repository.abstract_repository import AbstractRepository


class PlanningProjectRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'project'
