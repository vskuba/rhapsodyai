from mysql_.repository.abstract_repository import AbstractRepository


class ToolRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'tool'
