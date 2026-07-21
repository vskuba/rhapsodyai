from mysql_.repository.abstract_repository import AbstractRepository


class PlanRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'plan'
