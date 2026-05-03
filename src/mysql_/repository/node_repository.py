from mysql_.repository.abstract_repository import AbstractRepository


class NodeRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'node'
