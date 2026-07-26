from mysql_.repository.abstract_repository import AbstractRepository


class PlanningDocumentRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'planning_document'
