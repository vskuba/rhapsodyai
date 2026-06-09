from mysql_.repository.abstract_repository import AbstractRepository


class WorkflowRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'workflow'
