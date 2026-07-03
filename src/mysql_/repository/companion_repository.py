from mysql_.repository.abstract_repository import AbstractRepository


class CompanionRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'companion'
