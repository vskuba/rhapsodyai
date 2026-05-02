from mysql_.repository.abstract_repository import AbstractRepository


class FactCollectionRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'fact_collection'
